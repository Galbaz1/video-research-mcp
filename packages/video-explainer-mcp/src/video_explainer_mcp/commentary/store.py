"""Project location, canonical digests and write-once JSON records for commentary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

from ..config import get_config
from ..evidence import atomic_write
from ..file_io import open_regular
from ..render_artifacts import file_revision

PROJECT_SCHEMA = "vrm/movie-commentary-project/v1"
PLAN_SCHEMA = "vrm/movie-commentary-plan/v1"
SHARD_SCHEMA = "vrm/movie-commentary-shard/v1"
APPROVAL_SCHEMA = "vrm/movie-commentary-approval/v1"
REPORT_SCHEMA = "vrm/movie-commentary-exec-report/v1"
QA_SCHEMA = "vrm/movie-commentary-final-qa/v1"
MAX_SOURCE_BYTES = 64 * 1024 ** 3
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_SHARD_VIDEO_BYTES = 8 * 1024 ** 3


def project_root(project_id: str) -> Path:
    """Commentary projects live in a dot directory the explainer scanner skips."""
    return get_config().resolved_projects_path / ".movie-commentary" / project_id


def canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def revision(path: Path, max_bytes: int = MAX_RECORD_BYTES) -> dict:
    """Bounded sha256+size of a regular, non-symlinked file."""
    return file_revision(path, max_bytes)


def read_record(path: Path) -> dict:
    value = json.loads(read_bytes(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return value


def read_bytes(path: Path) -> bytes:
    """Read at most one record bound from a held, nonblocking regular descriptor."""
    with open_regular(path) as (stream, info):
        if info.st_size > MAX_RECORD_BYTES:
            raise ValueError(f"Expected a bounded regular record: {path.name}")
        body = stream.read(MAX_RECORD_BYTES + 1)
        if len(body) > MAX_RECORD_BYTES:
            raise ValueError(f"Expected a bounded regular record: {path.name}")
    return body


def write_record(path: Path, value: dict) -> None:
    """Replaceable record (project state)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, canonical(value).decode("utf-8"))


def write_once(path: Path, value: dict) -> str:
    """Create once; accept a stable identical rewrite, refuse changed or unstable records."""
    body = canonical(value)
    if len(body) > MAX_RECORD_BYTES:
        raise ValueError(f"Expected a bounded regular record: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".immutable-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = read_bytes(path)
            except (OSError, ValueError) as error:
                raise FileExistsError(f"Immutable record could not be verified: {path.name}") from error
            if existing != body:
                raise FileExistsError(f"Immutable record differs: {path.name}") from None
    finally:
        temporary.unlink(missing_ok=True)
    return sha256(body)


def inside(root: Path, relative: str, base: str) -> Path | None:
    """Resolve a project-relative path that must stay under ``root/base`` without links."""
    pure = PurePosixPath(relative)
    fence, path = root / base, root / pure
    if pure.is_absolute() or ".." in pure.parts or not path.is_relative_to(fence) or path == fence:
        return None
    current = fence
    for part in (None, *path.relative_to(fence).parts):
        current = current if part is None else current / part
        if current.is_symlink():
            return None
    return path
