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
    codex = json.loads((root / "plugin.json").read_text())
    servers = json.loads((root / "mcp.json").read_text())["mcpServers"]
    version = project["version"]
    if {package["version"], plugin["version"], codex["version"]} != {version}:
        raise SystemExit("Release versions differ across Python, npm and plugin manifests")
    runtime = {"type": "stdio", "command": "uvx", "args": [f"video-research-mcp=={version}"]}
    if servers != {"video-research": runtime}:
        raise SystemExit(f"mcp.json must launch only video-research-mcp=={version} through uvx")
    if not {"plugin.json", "mcp.json"} <= set(package["files"]):
        raise SystemExit("npm payload omits the Codex plugin manifests")
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
    print(
        f"Release {version}: manifests, Codex runtime pin, changelog and "
        f"{len(file_map)} installer files agree"
    )


if __name__ == "__main__":
    main()
