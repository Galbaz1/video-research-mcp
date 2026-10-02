"""Nonblocking regular-file descriptors for bounded local source readback."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat


@contextmanager
def open_regular(path: Path):
    """Reject replaced devices/FIFOs before reading and mutation during a read."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Expected a regular source or artifact file")
        yield stream, before
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Source or artifact changed during readback")
