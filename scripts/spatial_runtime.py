"""Readmit the concrete isolated spatial runtime using only trusted stdlib code."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from spatial_inputs import admit_file

CLEARANCE = "verified-selected-runtime-grants"
DIRECT_PACKAGES = {"mcp": "1.30.0", "pillow": "11.3.0", "openai": "1.109.1", "anyio": "4.15.1",
                   "pydantic": "2.13.5", "docstring-parser": "0.18.0",
                   "numpy": "2.4.4", "matplotlib": "3.10.9"}


def read_descriptor(path: Path, sha256: str) -> dict:
    """Parse the same regular descriptor bytes whose independent digest was checked."""
    if not path.is_absolute() or path != path.resolve() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Descriptor must be an absolute regular file without links")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("Descriptor differs from the independently trusted SHA256")
    return json.loads(raw)


def installed_inventory(site: Path, rows: list[dict]) -> dict[str, dict]:
    """Match every installed regular file, rejecting links, specials and unlisted bytes."""
    if not site.is_absolute() or site != site.resolve() or not site.is_dir():
        raise ValueError("Selected site-packages must be a real absolute directory")
    selected = {}
    for row in rows:
        path = Path(row["path"])
        if not path.is_relative_to(site) or path == site or str(path) in selected:
            raise ValueError("Installed inventory contains escaping or duplicate paths")
        selected[str(path)] = row
    if not selected:
        raise ValueError("Complete installed inventory is required")
    actual, pending = set(), [site]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(mode):
                    actual.add(entry.path)
                else:
                    raise ValueError(f"Nonregular installed path: {entry.path}")
    if actual != set(selected):
        raise ValueError(f"Installed file inventory differs: missing={sorted(set(selected) - actual)} "
                         f"extra={sorted(actual - set(selected))}")
    for row in selected.values():
        admit_file(row)
    return selected


def interpreter_selection(fields: dict) -> tuple[Path, Path, Path]:
    """Bind the prefix executable link directly to the selected CPython binary and library."""
    executable = Path(fields["python_executable"])
    real = Path(fields["python_realpath"])
    if (not executable.is_absolute() or executable.parent != executable.parent.resolve()
            or executable.name not in {"python", "python3", "python3.12"}
            or executable.parent.name != "bin" or not executable.is_symlink()
            or os.readlink(executable) != str(real) or executable.resolve() != real):
        raise ValueError("Selected venv-prefix interpreter link was retargeted or is indirect")
    admit_file({"path": str(real), "sha256": fields["python_sha256"], "bytes": fields["python_bytes"]})
    library = fields["libpython"]
    if Path(library["path"]) != real.parent.parent / "lib/libpython3.12.dylib":
        raise ValueError("libpython is outside the selected interpreter installation")
    admit_file(library)
    prefix = executable.parent.parent
    site = Path(fields["site_packages"])
    if site != prefix / "lib/python3.12/site-packages":
        raise ValueError("site-packages differs from the selected venv-prefix")
    return executable, real, site


def bootstrap_selection(fields: dict, real: Path, site: Path, installed: dict) -> None:
    """Admit the concrete stdlib venv configuration and require zero startup hooks."""
    prefix = site.parents[2]
    cfg = prefix / "pyvenv.cfg"
    required = {str(cfg)}
    rows = fields["bootstrap_sources"]
    paths = [row["path"] for row in rows]
    if len(set(paths)) != len(paths) or not required.issubset(paths):
        raise ValueError("Selected runtime bootstrap is incomplete or duplicated")
    for row in rows:
        path = Path(row["path"])
        if not path.is_relative_to(prefix) and not path.is_relative_to(real.parent.parent):
            raise ValueError("Bootstrap path escapes the selected runtime")
        admit_file(row)
    settings = {}
    for line in cfg.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator:
            if key.strip() in settings:
                raise ValueError("Duplicate pyvenv setting")
            settings[key.strip()] = value.strip()
    if (settings.get("home") != str(real.parent)
            or settings.get("version") != "3.12.13"
            or settings.get("executable") != str(real)
            or settings.get("include-system-site-packages") != "false"):
        raise ValueError("pyvenv.cfg differs from the selected CPython prefix")
    for path in installed:
        relative = Path(path).relative_to(site)
        if (relative.name.lower().endswith(".pth")
                or any(part.split(".")[0] in {"sitecustomize", "usercustomize"} for part in relative.parts)):
            raise ValueError("Unexpected installed startup hook")


def admit_runtime(data: dict) -> dict:
    """Readmit executable, bootstrap and the entire installed byte inventory before use."""
    if data.get("runtime_clearance") != CLEARANCE:
        raise ValueError("Runtime grants are blocked")
    if data["selected_python"] != "3.12.13" or data["selected_direct_packages"] != DIRECT_PACKAGES:
        raise ValueError("Runtime differs from the explicitly selected external profile")
    fields = data["runtime_fields"]
    executable, real, site = interpreter_selection(fields)
    installed = installed_inventory(site, fields["installed_sources"])
    bootstrap_selection(fields, real, site, installed)
    return {"executable": str(executable), "realpath": str(real),
            "prefix": str(executable.parent.parent), "site_packages": str(site),
            "installed_files": len(installed)}
