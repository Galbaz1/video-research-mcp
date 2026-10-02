"""Fenced glob discovery with bounded entry visits and compatible file counts."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .local_path_policy import enforce_local_access_root, resolve_path

MAX_SCAN_ENTRIES = 5000


def discover_files(directory: Path, pattern: str, extensions: dict, max_files: int) -> list[Path]:
    """Return sorted supported files, rejecting traversal and bounding input discovery."""
    parts = Path(pattern).parts
    if Path(pattern).is_absolute() or ".." in parts:
        raise PermissionError("glob_pattern must stay within the selected directory")
    if not parts:
        raise ValueError("glob_pattern must not be empty")
    if pattern.endswith("/"):
        return []  # Directory-only globs select no input files.
    visited = 0

    def entries(path):
        """Count every inspected directory entry before filtering."""
        nonlocal visited
        with os.scandir(path) as iterator:
            for entry in iterator:
                # Count nonmatches too: narrow globs must not hide unbounded scans.
                visited += 1
                if visited > MAX_SCAN_ENTRIES:
                    raise ValueError(f"Directory scan exceeds {MAX_SCAN_ENTRIES} entries; narrow the directory")
                yield entry

    def walk(path, segments):
        """Match path segments without following directory symlinks."""
        if not segments:
            return
        first, *rest = segments
        if first == "**":
            yield from walk(path, rest)
        for entry in entries(path):
            candidate = Path(entry.path)
            if first == "**":
                if entry.is_dir(follow_symlinks=False):
                    yield from walk(candidate, segments)
                elif not rest and entry.is_file():
                    yield enforce_local_access_root(resolve_path(str(candidate)))
            elif fnmatch.fnmatchcase(entry.name, first):
                checked = enforce_local_access_root(resolve_path(str(candidate)))
                if rest:
                    if entry.is_symlink() and checked.is_dir():
                        raise PermissionError("Batch scans must not follow directory symlinks")
                    if entry.is_dir(follow_symlinks=False):
                        yield from walk(checked, rest)
                elif entry.is_file():
                    yield checked

    found = set()
    for path in walk(directory, parts):
        if path.suffix.lower() in extensions:
            found.add(path)
    return sorted(found)[:max_files]
