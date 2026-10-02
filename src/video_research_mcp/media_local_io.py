"""Bounded regular local media reads, exact-byte snapshots and cancellation checks."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
import time
from pathlib import Path

from .config import get_config


def _open_regular(path: Path):
    """Open the actual regular file without following a substituted symlink."""
    initial = path.lstat()
    if not stat.S_ISREG(initial.st_mode):
        raise PermissionError("Media assets and inputs must be regular files")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    actual = os.fstat(fd)
    if not stat.S_ISREG(actual.st_mode) or (initial.st_dev, initial.st_ino) != (
        actual.st_dev,
        actual.st_ino,
    ):
        os.close(fd)
        raise PermissionError("Media assets and inputs must be regular files")
    return os.fdopen(fd, "rb")



def _copy_hash(
    source: Path,
    target: Path | None = None,
    *,
    cancelled: threading.Event | None = None,
    max_bytes: int | None = None,
) -> tuple[str, int]:
    """Hash the same bounded bytes that are copied; detect changes during reading."""
    h, size = hashlib.sha256(), 0
    deadline = time.monotonic() + get_config().media_acquire_timeout_seconds
    ceiling = (
        min(get_config().media_max_input_bytes, max_bytes)
        if max_bytes is not None
        else get_config().media_max_input_bytes
    )
    with _open_regular(source) as reader:
        before = os.fstat(reader.fileno())
        if before.st_size > ceiling:
            raise ValueError("Media exceeds MEDIA_MAX_INPUT_BYTES")
        writer = target.open("xb") if target else None
        try:
            if writer:
                os.fchmod(writer.fileno(), 0o600)
            while size < ceiling:
                chunk = reader.read(min(64 * 1024, ceiling - size))
                if not chunk:
                    break
                if time.monotonic() > deadline or (cancelled and cancelled.is_set()):
                    raise TimeoutError(
                        "Media read canceled or exceeded MEDIA_ACQUIRE_TIMEOUT_SECONDS"
                    )
                size += len(chunk)
                h.update(chunk)
                if writer:
                    writer.write(chunk)
            after = os.fstat(reader.fileno())
            current = source.lstat()
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("Media path changed while reading")
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or size != before.st_size:
                raise ValueError("Media changed while reading; retry from a stable source")
            if not size:
                raise ValueError("Media input is empty")
            if writer:
                writer.flush()
                os.fsync(writer.fileno())
        finally:
            if writer:
                writer.close()
    return h.hexdigest(), size

