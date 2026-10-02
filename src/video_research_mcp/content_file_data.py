"""Fenced regular-file content reads under the document payload ceiling."""

from __future__ import annotations

import os
from pathlib import Path

from .config import get_config
from .local_path_policy import enforce_local_access_root, resolve_path
from .media_local_io import _open_regular


def read_content_bytes(path: Path, max_bytes: int) -> bytes:
    """Reject special files, oversize payloads and changed bytes before inference."""
    path = enforce_local_access_root(resolve_path(str(path)))
    ceiling = min(get_config().doc_max_download_bytes, max_bytes)
    with _open_regular(path) as reader:
        before = os.fstat(reader.fileno())
        if before.st_size > ceiling:
            raise ValueError("Content exceeds DOC_MAX_DOWNLOAD_BYTES or remaining compare budget")
        data = reader.read(ceiling + 1)
        after = os.fstat(reader.fileno())
    if len(data) > ceiling:
        raise ValueError("Content exceeds DOC_MAX_DOWNLOAD_BYTES or remaining compare budget")
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ) or len(data) != before.st_size:
        raise ValueError("Content changed while reading; retry from a stable source")
    return data
