"""Shared SQLite ownership and byte-integrity receipts; never submit external work."""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from uuid import uuid4

_ACTIVE = ("queued", "running", "cancel_requested", "unknown")
_TERMINAL = ("completed", "failed", "partial", "cancelled")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
 job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, request_json TEXT NOT NULL,
 request_sha256 TEXT NOT NULL, source_revision TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','cancel_requested',
 'unknown','completed','failed','partial','cancelled')),
 owner TEXT, lease_until REAL, external_id TEXT, result_json TEXT,
 result_sha256 TEXT, artifact_hashes_json TEXT NOT NULL DEFAULT '{}',
 created_at REAL NOT NULL, updated_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 error_json TEXT, exclusive_key TEXT,
 CHECK ((owner IS NULL) = (lease_until IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_exclusive_active ON jobs(exclusive_key)
 WHERE exclusive_key IS NOT NULL AND status IN ('queued','running','cancel_requested','unknown');
CREATE UNIQUE INDEX IF NOT EXISTS jobs_external ON jobs(kind,external_id)
 WHERE external_id IS NOT NULL;
"""


def _canonical(value) -> str:
    """Freeze Unicode JSON without nonfinite numeric values."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request_digest(kind, request, source_revision, exclusive_key) -> str:
    """Commit the complete immutable request envelope, including its source/settings scope."""
    return _digest(
        _canonical(
            {
                "kind": kind,
                "request": request,
                "source_revision": source_revision,
                "exclusive_key": exclusive_key,
            }
        )
    )


def _result_digest(result, request_sha256, external_id, artifact_hashes) -> str:
    """Bind result bytes to their frozen request, operation and exact artifact commitments."""
    return _digest(
        _canonical(
            {
                "result": result,
                "request_sha256": request_sha256,
                "external_id": external_id,
                "artifact_hashes": artifact_hashes,
            }
        )
    )


def _clock(now) -> float:
    value = time.time() if now is None else float(now)
    if not math.isfinite(value):
        raise ValueError("Finite epoch time required")
    return value


def _duration(value) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Positive finite lease_seconds required")
    return value


def _text(value, field) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Nonempty {field} required")
    return value


def _artifacts(values) -> dict:
    """Accept exact absolute artifact commitments, leaving path authorization to adapters."""
    if not isinstance(values, dict) or any(
        not isinstance(path, str)
        or not Path(path).is_absolute()
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        for path, digest in values.items()
    ):
        raise ValueError("artifact_hashes must map absolute paths to complete lowercase SHA256")
    return values


def _artifact_readback(values, check=None) -> tuple[str, dict]:
    """Stream regular original files; missing, changed and symlink outputs are unverified."""
    details = {}
    try:
        _artifacts(values)
    except ValueError:
        return "invalid", details
    for name, expected in values.items():
        if check:
            check()
        actual, status = None, "unavailable"
        try:
            if Path(name).is_symlink():
                raise ValueError("Symlink artifact")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(name, flags)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Nonregular artifact")
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    if check:
                        check()
                    digest.update(chunk)
                actual = digest.hexdigest()
            status = "verified" if actual == expected else "mismatch"
        except (OSError, ValueError):
            if check:
                check()
        details[name] = {"expected_sha256": expected, "actual_sha256": actual, "status": status}
    if check:
        check()
    states = {item["status"] for item in details.values()}
    for state in ("unavailable", "mismatch"):
        if state in states:
            return state, details
    return ("verified" if details else "absent"), details


def _read_json(raw) -> tuple[object, str]:
    if raw is None:
        return None, "absent"
    try:
        value = json.loads(raw)
        _canonical(value)
        return value, "verified"
    except (ValueError, TypeError):
        return None, "invalid"


def _request_state(row, request, parsed) -> str:
    if parsed != "verified" or not isinstance(request, dict):
        return "invalid"
    expected = _request_digest(row["kind"], request, row["source_revision"], row["exclusive_key"])
    return "verified" if expected == row["request_sha256"] else "mismatch"


def _verified_request(row) -> dict:
    """Reject corrupted requests before ownership grants or checkpoint writes."""
    request, parsed = _read_json(row["request_json"])
    if _request_state(row, request, parsed) != "verified":
        raise ValueError("Frozen job request integrity failed")
    return request


def _result_state(row, result, parsed, artifacts, artifact_state, request_state) -> str:
    if parsed == "invalid" or artifact_state == "invalid":
        return "invalid"
    if request_state != "verified":
        return "mismatch"
    if row["result_json"] is None and not artifacts:
        return "absent" if row["result_sha256"] is None else "mismatch"
    expected = _result_digest(result, row["request_sha256"], row["external_id"], artifacts)
    return "verified" if row["result_sha256"] == expected else "mismatch"


def _record(row, readback_check=None) -> dict | None:
    """Attest readback bytes separately from retained lifecycle status or semantic truth."""
    if row is None:
        return None
    result = dict(row)
    result["request"], parsed_request = _read_json(result.pop("request_json"))
    request_state = _request_state(row, result["request"], parsed_request)
    result["result"], parsed_result = _read_json(result.pop("result_json"))
    result["error"], _ = _read_json(result.pop("error_json"))
    result["artifact_hashes"], _ = _read_json(result.pop("artifact_hashes_json"))
    artifact_state, details = _artifact_readback(result["artifact_hashes"], readback_check)
    result_state = _result_state(
        row,
        result["result"],
        parsed_result,
        result["artifact_hashes"],
        artifact_state,
        request_state,
    )
    result["attestation"] = {
        "request_integrity": request_state,
        "result_integrity": result_state,
        "artifact_integrity": artifact_state,
        "artifacts": details,
        "checked_at": time.time(),
        "verified": request_state == "verified"
        and result_state in {"verified", "absent"}
        and artifact_state in {"verified", "absent"}
        and (result_state == "verified" or artifact_state == "verified"),
    }
    return result


def _checkpoint_values(row, target, external_id, result, error, artifacts, release, now):
    """Compute controller digests and serialized fields without changing immutable identity."""
    if external_id is not None:
        _text(external_id, "external_id")
    _verified_request(row)
    encoded = _canonical(result) if result is not None else row["result_json"]
    old_artifacts = _artifacts(json.loads(row["artifact_hashes_json"]))
    old_result = json.loads(row["result_json"]) if row["result_json"] is not None else None
    if result is None and row["result_sha256"] is not None:
        expected = _result_digest(
            old_result, row["request_sha256"], row["external_id"], old_artifacts
        )
        if expected != row["result_sha256"]:
            raise ValueError("Existing job result integrity failed")
    current_artifacts = json.loads(artifacts) if artifacts is not None else old_artifacts
    current_result = result if result is not None else old_result
    operation = external_id or row["external_id"]
    digest = (
        _result_digest(current_result, row["request_sha256"], operation, current_artifacts)
        if encoded is not None or current_artifacts
        else None
    )
    released = release or target in _TERMINAL
    return (
        target,
        external_id or row["external_id"],
        encoded,
        digest,
        _canonical(error) if error is not None else row["error_json"],
        artifacts if artifacts is not None else row["artifact_hashes_json"],
        None if released else row["owner"],
        None if released else row["lease_until"],
        now,
        row["job_id"],
        row["owner"],
        now,
    )


def _secure_database(path: Path) -> None:
    """Protect new state and database bytes before SQLite creates private WAL sidecars."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Job database must be a regular file")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _initialize(db) -> None:
    """Bound WAL-bootstrap contention; SQLite BUSY/LOCKED never becomes adapter resubmission."""
    deadline = time.monotonic() + 5
    while True:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        db.execute(f"PRAGMA busy_timeout={remaining_ms}")
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            db.execute("PRAGMA busy_timeout=5000")
            return
        except sqlite3.OperationalError as error:
            code = getattr(error, "sqlite_errorcode", 0) & 255
            if (
                code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(0.01)


class JobStore:
    """Durable lease/CAS store shared by adapters; recovered ownership never permits resubmission."""

    def __init__(self, path=None, *, readback_check=None):
        """Resolve the shared location without opening the database at import/construction."""
        self.path = Path(
            path or os.getenv("VRM_JOB_DB") or "~/.local/state/video-research-mcp/jobs.sqlite3"
        ).expanduser()
        self.readback_check = readback_check

    @contextmanager
    def _connect(self):
        _secure_database(self.path)
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            _initialize(db)
            yield db
        finally:
            db.close()

    def create(
        self, kind, request: dict, source_revision: str, *, job_id=None, exclusive_key=None
    ) -> dict:
        """Create an immutable request or return its identical explicit-id retry."""
        _text(kind, "kind"), _text(source_revision, "source_revision")
        if not isinstance(request, dict):
            raise ValueError("Dictionary request required")
        encoded = _canonical(request)
        digest = _request_digest(kind, request, source_revision, exclusive_key)
        now = time.time()
        job_id = _text(job_id or uuid4().hex, "job_id")
        if exclusive_key is not None:
            _text(exclusive_key, "exclusive_key")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is not None:
                if (
                    row["kind"],
                    row["request_sha256"],
                    row["source_revision"],
                    row["exclusive_key"],
                ) != (kind, digest, source_revision, exclusive_key):
                    raise ValueError("Existing job immutable binding differs")
            else:
                try:
                    db.execute(
                        "INSERT INTO jobs(job_id,kind,request_json,request_sha256,source_revision,status,created_at,updated_at,exclusive_key) VALUES(?,?,?,?,?,'queued',?,?,?)",
                        (job_id, kind, encoded, digest, source_revision, now, now, exclusive_key),
                    )
                except sqlite3.IntegrityError as error:
                    raise ValueError("Active or unknown job already uses exclusive_key") from error
                row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            db.commit()
        return _record(row, self.readback_check)

    def get(self, job_id) -> dict | None:
        """Return current byte attestations without promoting retained status text."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _record(row, self.readback_check)

    def find_external(self, external_id, *, kind=None) -> dict | None:
        """Find terminal as well as active operations; ambiguous cross-kind IDs do not bind."""
        with self._connect() as db:
            if kind is None:
                rows = db.execute(
                    "SELECT * FROM jobs WHERE external_id=? LIMIT 2", (external_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM jobs WHERE external_id=? AND kind=?", (external_id, kind)
                ).fetchall()
        return _record(rows[0], self.readback_check) if len(rows) == 1 else None

    def claim(self, job_id, owner, *, lease_seconds=30, now=None) -> dict | None:
        """Acquire queued or stale/unowned work for reconciliation, never an external retry."""
        _text(owner, "owner")
        now = _clock(now)
        until = now + _duration(lease_seconds)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if current is not None and current["status"] in _ACTIVE:
                _verified_request(current)
            changed = db.execute(
                "UPDATE jobs SET status=CASE WHEN status='queued' THEN 'running' ELSE status END,owner=?,lease_until=?,updated_at=?,attempts=attempts+1 WHERE job_id=? AND status IN ('queued','running','cancel_requested','unknown') AND (owner IS NULL OR lease_until<=?)",
                (owner, until, now, job_id, now),
            ).rowcount
            row = (
                db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                if changed
                else None
            )
            db.commit()
        return _record(row, self.readback_check)

    def heartbeat(self, job_id, owner, *, lease_seconds=30, now=None) -> bool:
        """Extend only this unexpired owner; terminal and expired leases remain closed."""
        now = _clock(now)
        until = now + _duration(lease_seconds)
        with self._connect() as db:
            return bool(
                db.execute(
                    "UPDATE jobs SET lease_until=?,updated_at=? WHERE job_id=? AND owner=? AND lease_until>? AND status IN ('running','cancel_requested','unknown')",
                    (until, now, job_id, owner, now),
                ).rowcount
            )

    def checkpoint(
        self,
        job_id,
        owner,
        *,
        status=None,
        external_id=None,
        result=None,
        error=None,
        artifact_hashes=None,
        release=False,
        now=None,
    ) -> bool:
        """CAS a live lease, preserving cancellation and immutable external-operation binding."""
        now = _clock(now)
        if status is not None and status not in (*_ACTIVE, *_TERMINAL):
            raise ValueError("Unknown job status")
        encoded_artifacts = (
            _canonical(_artifacts(artifact_hashes)) if artifact_hashes is not None else None
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if (
                row is None
                or row["owner"] != owner
                or row["lease_until"] is None
                or row["lease_until"] <= now
                or row["status"] in _TERMINAL
            ):
                return False
            target = status or row["status"]
            if target == "queued" or (
                row["status"] == "cancel_requested"
                and target not in ("cancel_requested", "cancelled", "failed", "partial")
            ):
                return False
            if external_id is not None and row["external_id"] not in (None, external_id):
                return False
            values = _checkpoint_values(
                row, target, external_id, result, error, encoded_artifacts, release, now
            )
            try:
                changed = db.execute(
                    "UPDATE jobs SET status=?,external_id=?,result_json=?,result_sha256=?,error_json=?,artifact_hashes_json=?,owner=?,lease_until=?,updated_at=? WHERE job_id=? AND owner=? AND lease_until>?",
                    values,
                ).rowcount
            except sqlite3.IntegrityError:
                return False
            if self.readback_check:
                self.readback_check()
            db.commit()
        return bool(changed)

    def cancel(self, job_id) -> dict | None:
        """Cancel queued work immediately; active/unknown work requires adapter acknowledgement."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is not None and row["status"] in _ACTIVE:
                target = "cancelled" if row["status"] == "queued" else "cancel_requested"
                db.execute(
                    "UPDATE jobs SET status=?,updated_at=? WHERE job_id=?",
                    (target, time.time(), job_id),
                )
                row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            db.commit()
        return _record(row, self.readback_check)

    def list_active(self, kind) -> list[dict]:
        """Retain all queued, active, cancellation-requested and uncertain jobs for reconciliation."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE kind=? AND status IN ('queued','running','cancel_requested','unknown') ORDER BY created_at,job_id",
                (kind,),
            ).fetchall()
        return [_record(row, self.readback_check) for row in rows]
