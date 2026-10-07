"""Bind render requests and outputs to exact local file revisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .file_io import open_regular

MAX_RENDER_BYTES = 512 * 1024 * 1024


def file_revision(path: Path, max_bytes: int | None = None) -> dict:
    """Hash a regular file, rejecting mutation during the read."""
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Expected a regular file: {path}")
    digest = hashlib.sha256()
    total = 0
    with open_regular(path) as (stream, info):
        if max_bytes is not None and info.st_size > max_bytes:
            raise ValueError(f"File exceeds the {max_bytes}-byte read bound: {path}")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ValueError(f"File exceeds the {max_bytes}-byte read bound: {path}")
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": info.st_size}


def project_revision(project_dir: Path) -> dict:
    """Record all regular project inputs, excluding generated render output."""
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project not found: {project_dir}")
    files = {}
    for path in sorted(project_dir.rglob("*")):
        relative = path.relative_to(project_dir)
        if relative.parts[0] == "output":
            continue
        if path.is_symlink():
            raise ValueError(f"Cannot bind a symlinked project input: {relative}")
        if path.is_file():
            files[str(relative)] = file_revision(path)
        elif not path.is_dir():
            raise ValueError(f"Cannot bind a nonregular project input: {relative}")
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": files}


def render_outputs(output_dir: Path) -> dict[str, dict]:
    """Hash existing regular, nonempty video files for fresh-output admission."""
    outputs = {}
    if output_dir.is_symlink():
        raise ValueError("Cannot bind a symlinked render output directory")
    for path in output_dir.glob("*"):
        if path.suffix.lower() not in {".mp4", ".webm"} or path.is_symlink():
            continue
        if path.is_file() and path.stat().st_size > 0:
            outputs[str(path)] = file_revision(path, MAX_RENDER_BYTES)
    return outputs


def verify_output(artifact: dict, max_bytes: int = MAX_RENDER_BYTES) -> bool:
    """Read back the exact accepted output bytes; a path alone proves nothing."""
    try:
        return file_revision(Path(artifact["path"]), max_bytes) == {
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
        }
    except (OSError, ValueError, KeyError):
        return False
