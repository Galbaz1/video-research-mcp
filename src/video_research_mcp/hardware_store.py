"""Small serialized simulator states, independent audit gates and durable receipts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from .hardware_authority import canonical, digest
from .media_local_io import _open_regular

DEFAULTS = {"simulator/lamp": {"on": False, "brightness": 0},
            "simulator/camera": {"exposure_ms": 10}}
MAX_COMMANDS = 512
MAX_FILES = 64
MAX_FILE_BYTES = 1024 * 1024


def private_directory(path: Path) -> None:
    """Create an owned directory and reject symlink components or non-owner leaves."""
    if ".." in path.parts or not path.is_absolute():
        raise ValueError("Simulator storage requires an absolute confined path")
    for part in reversed([path, *path.parents]):
        part.mkdir(mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(part.lstat().st_mode):
            raise PermissionError("Simulator directory components must be actual directories")
    if path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o022:
        raise PermissionError("Simulator directory must be owner-controlled")


class HardwareStore:
    """Own two device rows and at most 512 durable bounded command identities."""

    def __init__(self, database: Path, artifacts: Path, check):
        self.database, self.artifacts, self.check = database.absolute(), artifacts.absolute(), check
        check()
        private_directory(self.database.parent)
        private_directory(self.artifacts)
        try:
            fd = os.open(self.database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        with self.transaction() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS hardware_devices (id TEXT PRIMARY KEY, state TEXT NOT NULL, audit TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS hardware_commands (id TEXT PRIMARY KEY, intent TEXT NOT NULL, intent_sha TEXT NOT NULL, receipt TEXT NOT NULL, approval_sha TEXT UNIQUE)")
            for identifier, values in DEFAULTS.items():
                state = {"revision": 0, "mode": "online", "outputs_enabled": True, "values": values}
                audit = {"health_required": False, "failure_count": 0, "health_generation": 0,
                         "last_health": None}
                connection.execute("INSERT OR IGNORE INTO hardware_devices VALUES (?,?,?)",
                                   (identifier, canonical(state).decode(), canonical(audit).decode()))

    @contextmanager
    def transaction(self):
        """Serialize one operation, fencing database identity and cancellation at commit."""
        self.check()
        with _open_regular(self.database) as reader:
            identity = os.fstat(reader.fileno())
            if identity.st_uid != os.geteuid() or identity.st_mode & 0o077 or identity.st_size > 4 * 1024 * 1024:
                raise PermissionError("Simulator database must be a private bounded owner file")
            connection = sqlite3.connect(self.database, timeout=1, isolation_level=None)
            try:
                connection.execute("PRAGMA max_page_count=1024")
                connection.execute("BEGIN IMMEDIATE")
                self._identity(identity)
                yield connection
                self._identity(identity)
                self.check()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _identity(self, before) -> None:
        with _open_regular(self.database) as reader:
            after = os.fstat(reader.fileno())
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise PermissionError("Simulator database path changed during operation")
        if after.st_uid != os.geteuid() or after.st_mode & 0o077:
            raise PermissionError("Simulator database ownership or private mode changed")

    def has_capacity(self, connection, intent: dict, *, project_reset: bool) -> bool:
        """Keep one durable stop slot for each device that would remain online."""
        states = {identifier: json.loads(state) for identifier, state in
                  connection.execute("SELECT id,state FROM hardware_devices")}
        online = sum(state["mode"] == "online" for state in states.values())
        if project_reset and intent["action"] == "reset" and intent["device_id"] in states:
            if intent["mode"] in {"estop", "soft"}:
                online += int(intent["mode"] == "soft") - int(states[intent["device_id"]]["mode"] == "online")
        count = connection.execute("SELECT COUNT(*) FROM hardware_commands").fetchone()[0]
        additional = int(self.command(connection, intent["command_id"]) is None)
        return count + additional + online <= MAX_COMMANDS

    def device(self, connection, identifier: str) -> tuple[dict, dict]:
        """Read the fixed registered device's values separately from its audit gate."""
        row = connection.execute("SELECT state,audit FROM hardware_devices WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown registered simulator device")
        return json.loads(row[0]), json.loads(row[1])

    def update(self, connection, identifier: str, state: dict, audit: dict) -> None:
        """Persist state and audit in the same command transaction."""
        connection.execute("UPDATE hardware_devices SET state=?,audit=? WHERE id=?",
                           (canonical(state).decode(), canonical(audit).decode(), identifier))

    def command(self, connection, identifier: str) -> tuple[dict, dict] | None:
        """Return the exact original intent and its last proposal or terminal receipt."""
        row = connection.execute("SELECT intent,receipt FROM hardware_commands WHERE id=?", (identifier,)).fetchone()
        return (json.loads(row[0]), json.loads(row[1])) if row else None

    def save_command(self, connection, intent: dict, receipt: dict, approved: bool = False) -> None:
        """Bound receipt population/bytes and uniquely consume an executed approval."""
        if not self.has_capacity(connection, intent, project_reset=receipt["status"] == "approval_required"):
            raise ValueError("Simulator receipt capacity must preserve a stop slot per online device")
        encoded = canonical(receipt)
        if len(encoded) > 16 * 1024:
            raise ValueError("Simulator command receipt exceeds 16 KiB")
        approval = receipt["commitment_sha256"] if approved else None
        connection.execute("INSERT INTO hardware_commands VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET receipt=excluded.receipt,approval_sha=excluded.approval_sha",
                           (intent["command_id"], canonical(intent).decode(), digest(intent), encoded.decode(), approval))

    def publish(self, files: dict[str, bytes]) -> list[dict]:
        """Publish exact tiny generated artifacts exclusively under the owned directory."""
        private_directory(self.artifacts)
        fd = os.open(self.artifacts, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        directory_identity = os.fstat(fd)
        created, records = [], []
        try:
            names = os.listdir(fd)
            if len(set(names) | set(files)) > MAX_FILES:
                raise ValueError("Simulator artifacts reached the 64-file limit")
            sizes = []
            for name in names:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise PermissionError("Simulator artifacts must be regular owned files")
                sizes.append(info.st_size)
            if sum(sizes) + sum(len(value) for name, value in files.items() if name not in names) > MAX_FILE_BYTES:
                raise ValueError("Simulator artifacts exceed the 1 MiB aggregate limit")
            for name, data in files.items():
                self.check()
                path = self.artifacts / name
                if name in names:
                    with _open_regular(path) as reader:
                        existing = reader.read(MAX_FILE_BYTES + 1)
                    if existing != data:
                        raise ValueError("Simulator artifact existing bytes differ from commitment")
                else:
                    output = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=fd)
                    created.append(name)
                    with os.fdopen(output, "wb") as writer:
                        os.fchmod(writer.fileno(), 0o600)
                        writer.write(data)
                records.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            current = self.artifacts.lstat()
            if (current.st_dev, current.st_ino) != (directory_identity.st_dev, directory_identity.st_ino):
                raise PermissionError("Simulator artifact directory changed during publication")
            for record in records:
                with _open_regular(Path(record["path"])) as reader:
                    actual = reader.read(MAX_FILE_BYTES + 1)
                if hashlib.sha256(actual).hexdigest() != record["sha256"]:
                    raise ValueError("Simulator published artifact changed before readback")
            self.check()
            return records
        except BaseException:
            for name in created:
                os.unlink(name, dir_fd=fd)
            raise
        finally:
            os.close(fd)
