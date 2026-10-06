"""Bind independently authored production scenes and their selected renderer runtime."""

from __future__ import annotations

import re
from pathlib import Path

from .planning_sources import read_object
from .render_artifacts import file_revision
from .render_authored import PACKAGES, _executable, tree_revision
from .render_validation import codec_executables

PRODUCTION_FILES = (
    "package.json",
    "package-lock.json",
    "production_entry.mjs",
    "production_project.mjs",
    "src/production-index.ts",
    "src/ProductionRoot.tsx",
    "src/Production.tsx",
    "src/production-types.ts",
)


def production_binding(cfg) -> dict:
    """Verify the external source/runtime freeze before project code can be bundled."""
    entry, spec_path = Path(cfg.renderer_entry), Path(cfg.renderer_spec)
    if not entry.is_absolute() or entry.name != "production_entry.mjs" or entry.is_symlink():
        raise ValueError("Production entry must be an absolute regular production_entry.mjs")
    entry = entry.resolve(strict=True)
    if not spec_path.is_absolute() or spec_path.is_symlink():
        raise ValueError("Production renderer requires an absolute regular frozen spec")
    if not re.fullmatch(r"[0-9a-f]{64}", cfg.renderer_spec_sha256):
        raise ValueError("Production renderer requires an external spec SHA256")
    spec, spec_sha = read_object(spec_path, spec_path.parent)
    if spec_sha != cfg.renderer_spec_sha256:
        raise ValueError("Production renderer spec hash changed")
    if spec.get("schema") != "vrm-authored-storyboard/r1":
        raise ValueError("Unsupported production renderer freeze")
    if spec.get("composition_id") != "Production":
        raise ValueError("Production renderer requires composition_id=Production")
    if set(spec["entry_sha256"]) != set(PRODUCTION_FILES):
        raise ValueError("Production freeze must bind every production entry file")
    revisions = {name: file_revision(entry.parent / name, 1024 * 1024) for name in PRODUCTION_FILES}
    if any(revisions[name]["sha256"] != digest for name, digest in spec["entry_sha256"].items()):
        raise ValueError("Production renderer source hash changed")
    if spec.get("package_versions") != PACKAGES:
        raise ValueError("Unsupported production renderer package versions")
    modules = entry.parent / "node_modules"
    for name, version in PACKAGES.items():
        package, _ = read_object(modules / name / "package.json", entry.parent)
        if package.get("name") != name or package.get("version") != version:
            raise ValueError(f"Production renderer package changed: {name}")
    runtime_sha = tree_revision(modules)
    if runtime_sha != spec["node_modules_sha256"]:
        raise ValueError("Production renderer installed bytes changed")
    browser = _executable(spec["browser"])
    browser_dir = Path(spec["browser"]["directory"])
    if not browser_dir.is_absolute() or not Path(browser["path"]).is_relative_to(browser_dir):
        raise ValueError("Browser resources require an absolute containing directory")
    browser_sha = tree_revision(browser_dir)
    if browser_sha != spec["browser"]["tree_sha256"]:
        raise ValueError("Production browser resources changed")
    browser.update(directory=str(browser_dir), tree_sha256=browser_sha)
    ffprobe = _executable(spec["ffprobe"])
    if codec_executables()["ffprobe"] != ffprobe:
        raise ValueError("Production ffprobe differs from the selected qualification executable")
    pins = spec["project_sha256"]
    if (
        not isinstance(pins, dict)
        or not pins
        or any(
            not isinstance(name, str)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for name, digest in pins.items()
        )
    ):
        raise ValueError("Production freeze requires exact project file hashes")
    return {
        "route": "authored_storyboard",
        "entry": str(entry),
        "spec": str(spec_path),
        "spec_sha256": spec_sha,
        "entry_revision": revisions,
        "entry_sha256": spec["entry_sha256"],
        "node_modules_sha256": runtime_sha,
        "node": _executable(spec["node"]),
        "browser": browser,
        "ffprobe": ffprobe,
        "project_sha256": pins,
    }
