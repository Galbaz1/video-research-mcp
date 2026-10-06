"""Confined reads and exact source closure for operator-frozen production projects."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .file_io import open_regular
from .planning_sources import canonical, read_object

MIB = 1024 * 1024


def confined_path(project: Path, name: str) -> Path:
    """Reject noncanonical relative paths and symlinks in every existing component."""
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or ":" in name
        or "\x00" in name
        or PurePosixPath(name).is_absolute()
        or any(part in {"", ".", ".."} for part in name.split("/"))
    ):
        raise ValueError("Project paths must be confined canonical relative paths")
    path = project
    for part in name.split("/"):
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Project path cannot contain a symlink: {name}")
    return path


def file_pin(path: Path, limit: int) -> dict:
    """Hash bounded regular bytes using the existing stable-read descriptor helper."""
    sha = hashlib.sha256()
    size = 0
    with open_regular(path) as (stream, info):
        if info.st_size > limit:
            raise ValueError(f"Project file exceeds byte ceiling: {path.name}")
        while body := stream.read(min(MIB, limit + 1 - size)):
            size += len(body)
            if size > limit:
                raise ValueError(f"Project file exceeds byte ceiling: {path.name}")
            sha.update(body)
    return {"sha256": sha.hexdigest(), "size_bytes": size}


def project_object(project: Path, name: str) -> tuple[dict, dict]:
    """Apply the production JSON ceiling before the current duplicate-safe parser."""
    path = confined_path(project, name)
    pin = file_pin(path, MIB)
    value, sha = read_object(path, project)
    if sha != pin["sha256"]:
        raise ValueError(f"Project JSON changed during normalization: {name}")
    canonical(value)
    return value, pin


def scene_sources(project: Path) -> list[str]:
    """Enumerate all TypeScript sources explicitly, refusing unreadable/symlink trees."""
    root = confined_path(project, "scenes")
    directories = [root]
    files = []
    while directories:
        directory = directories.pop()
        info = directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or not info.st_mode & 0o444
            or not info.st_mode & 0o111
            or not os.access(directory, os.R_OK | os.X_OK)
        ):
            raise ValueError("Scene source directory must be regular and readable")
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise ValueError("Scene source tree cannot contain symlinks")
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    if Path(entry.name).suffix not in {".ts", ".tsx"}:
                        raise ValueError("Scene source tree permits only .ts/.tsx files")
                    files.append(Path(entry.path).relative_to(project).as_posix())
                else:
                    raise ValueError("Scene source tree contains a nonregular entry")
    if "scenes/index.ts" not in files:
        raise ValueError("Production scene registry requires scenes/index.ts")
    return sorted(files)


def freeze_project(
    project: Path, pins: dict, json_pins: dict, sources: list[str], audio: set[str]
) -> dict:
    """Require the externally supplied exact closure before reading admitted sources."""
    names = set(json_pins) | set(sources) | audio
    if not isinstance(pins, dict) or set(pins) != names:
        raise ValueError("External project_sha256 must bind the exact project closure")
    if any(
        not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) for sha in pins.values()
    ):
        raise ValueError("External project_sha256 requires lowercase SHA256 values")
    revisions = dict(json_pins)
    source_bytes = 0
    for name in sources:
        revisions[name] = file_pin(confined_path(project, name), MIB)
        source_bytes += revisions[name]["size_bytes"]
        if source_bytes > 16 * MIB:
            raise ValueError("Scene sources exceed the 16 MiB total byte ceiling")
    for name in sorted(audio):
        revisions[name] = file_pin(confined_path(project, name), 64 * MIB)
        if not revisions[name]["size_bytes"]:
            raise ValueError("Selected audio asset must not be empty")
    if any(revisions[name]["sha256"] != pins[name] for name in names):
        raise ValueError("Externally frozen project source or asset hash changed")
    return revisions
