"""Owned, fenced exact-byte media snapshots with joined cancellation cleanup."""

from __future__ import annotations

import asyncio
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import get_config
from .local_path_policy import enforce_local_access_root, resolve_path
from .media_acquisition import _wait_worker
from .media_local_io import _copy_hash


def checked_path(value: str) -> Path:
    """Reject symlinks and URI inputs before resolving the configured fence."""
    if len(value) > 4096:
        raise ValueError("Native media paths must not exceed 4096 characters")
    resolve_path(value)  # Reject protocols before constructing a filesystem path.
    path = Path(value).expanduser().absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise PermissionError("Native media paths must not contain symlinks")
    return enforce_local_access_root(path)


def view_directory() -> Path:
    """Allocate one private view directory within the configured local fence."""
    base = checked_path(str(Path(get_config().cache_dir) / "media" / "views"))
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = base / uuid.uuid4().hex
    directory.mkdir(mode=0o700)
    return directory


async def copy_hash(source: Path, target: Path | None = None) -> tuple[str, int]:
    """Join cooperative hashing threads before any caller may remove staging."""
    canceled = threading.Event()
    task = asyncio.create_task(
        asyncio.to_thread(_copy_hash, source, target, cancelled=canceled)
    )
    return await _wait_worker(task, canceled)


def _identity(path: Path) -> tuple:
    value = path.lstat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


@dataclass
class Snapshot:
    """A single operation's owned bytes, deadline and original revision binding."""

    original: Path
    path: Path
    directory: Path
    sha256: str
    size: int
    identity: tuple
    deadline: float

    def remaining(self) -> float:
        """Return time left under the operation's single overall deadline."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Native media operation exceeded its configured timeout")
        return remaining

    async def verify(self) -> None:
        """Verify original identity and both full hashes before publishing artifacts."""
        checked_path(str(self.original))
        if _identity(self.original) != self.identity:
            raise ValueError("Source media changed during the operation")
        expected = self.sha256, self.size
        if await copy_hash(self.path) != expected or await copy_hash(self.original) != expected:
            raise ValueError("Source media or owned snapshot changed during the operation")


@asynccontextmanager
async def snapshot(file_path: str, expected_source_sha256: str | None = None):
    """Retain outputs only after original and snapshot revision readbacks succeed."""
    original = checked_path(file_path)
    identity = _identity(original)
    directory = view_directory()
    try:
        timeout = get_config().media_acquire_timeout_seconds
        async with asyncio.timeout(timeout):
            deadline = time.monotonic() + timeout
            target = directory / ("source" + original.suffix.lower())
            digest, size = await copy_hash(original, target)
            if expected_source_sha256 is not None and digest != expected_source_sha256:
                raise ValueError("Source SHA256 differs from the requested source revision")
            owned = Snapshot(original, target, directory, digest, size, identity, deadline)
            if _identity(original) != identity:
                raise ValueError("Source media changed before snapshot completion")
            yield owned
            await owned.verify()
            target.unlink()
        if not any(directory.iterdir()):
            directory.rmdir()
    except BaseException:
        shutil.rmtree(directory)
        raise
