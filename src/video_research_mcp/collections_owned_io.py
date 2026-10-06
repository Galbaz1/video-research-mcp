"""Descriptor-bound creation and promotion of exclusively owned collection bytes."""

import hashlib
import os
import time

from .config import get_config
from .media_local_io import _open_regular
from .media_snapshot import checked_path


def verify_root(root, fd):
    """Require the private configured path to still name the held directory."""
    current, opened = checked_path(str(root)).stat(), os.fstat(fd)
    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino) or opened.st_mode & 0o077:
        raise PermissionError("Owned root changed during admission")


def open_owned(root):
    """Hold the verified directory before its quota reservation is committed."""
    before = root.stat()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        verify_root(root, fd)
        opened = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise PermissionError("Owned root changed before reservation")
    except Exception:
        os.close(fd)
        raise
    return fd


def verify_output(target, fd, identity):
    """Bind promotion to the exact regular output created through the held directory."""
    verify_root(target.parent, fd)
    actual = os.stat(target.name, dir_fd=fd, follow_symlinks=False)
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    if identity.st_nlink != 1 or any(getattr(actual, key) != getattr(identity, key) for key in fields):
        raise PermissionError("Owned output changed before promotion")


def copy_owned(source, target, fd, max_bytes):
    """Copy bounded regular source bytes to an exclusive nonfollowing relative output."""
    digest, size = hashlib.sha256(), 0
    config = get_config()
    ceiling = min(config.media_max_input_bytes, max_bytes)
    deadline = time.monotonic() + config.media_acquire_timeout_seconds
    with _open_regular(source) as reader:
        before = os.fstat(reader.fileno())
        if before.st_size > ceiling:
            raise ValueError("Media exceeds MEDIA_MAX_INPUT_BYTES")
        verify_root(target.parent, fd)
        output = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(output, "wb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            created = os.fstat(writer.fileno())
            while size < ceiling:
                chunk = reader.read(min(64 * 1024, ceiling - size))
                if not chunk:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Media read exceeded MEDIA_ACQUIRE_TIMEOUT_SECONDS")
                size += len(chunk)
                digest.update(chunk)
                writer.write(chunk)
            after, current = os.fstat(reader.fileno()), source.lstat()
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("Media path changed while reading")
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or size != before.st_size:
                raise ValueError("Media changed while reading; retry from a stable source")
            if not size:
                raise ValueError("Media input is empty")
            writer.flush()
            os.fsync(writer.fileno())
            identity = os.fstat(writer.fileno())
            if (created.st_dev, created.st_ino) != (identity.st_dev, identity.st_ino) or identity.st_size != size:
                raise PermissionError("Owned output changed while copying")
    return (digest.hexdigest(), size), identity
