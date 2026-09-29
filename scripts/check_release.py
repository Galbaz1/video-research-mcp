#!/usr/bin/env python3
"""Check release metadata and shipped installer mappings without provider calls."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path


def main() -> None:
    """Fail when metadata, changelog or bundled installer files disagree."""
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    package = json.loads((root / "package.json").read_text())
    plugin = json.loads((root / ".claude-plugin/plugin.json").read_text())
    version = project["version"]
    if package["version"] != version or plugin["version"] != version:
        raise SystemExit("Release versions differ across Python, npm and plugin manifests")
    if not re.search(rf"^## \[{re.escape(version)}\]", (root / "CHANGELOG.md").read_text(), re.M):
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    result = subprocess.run(
        ["node", "-e", "console.log(JSON.stringify(require('./bin/lib/copy').FILE_MAP))"],
        cwd=root, check=True, capture_output=True, text=True,
    )
    file_map = json.loads(result.stdout)
    missing = [name for name in file_map if not (root / name).is_file()]
    if missing:
        raise SystemExit(f"Installer sources missing: {', '.join(missing)}")
    if len(set(file_map.values())) != len(file_map):
        raise SystemExit("Installer has duplicate destinations")
    print(f"Release {version}: manifests, changelog and {len(file_map)} installer files agree")


if __name__ == "__main__":
    main()
