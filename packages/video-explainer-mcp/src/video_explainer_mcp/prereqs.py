"""Prerequisite checks for the video explainer CLI environment."""

from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from .config import get_config


class PrereqStatus(BaseModel):
    """Result of checking a single prerequisite."""

    name: str
    available: bool
    path: str = ""
    message: str = ""


class PrereqReport(BaseModel):
    """Aggregated prerequisite check results."""

    all_ok: bool = False
    checks: list[PrereqStatus] = Field(default_factory=list)


def check_prereqs() -> PrereqReport:
    """Check that required tools are available on the system.

    Checks: python3 (or configured python), node, ffmpeg, and
    EXPLAINER_PATH directory existence.

    Returns:
        PrereqReport with per-tool availability.
    """
    cfg = get_config()
    checks: list[PrereqStatus] = []

    # Python
    python_path = shutil.which(cfg.explainer_python)
    checks.append(PrereqStatus(
        name="python",
        available=python_path is not None,
        path=python_path or "",
        message="" if python_path else f"'{cfg.explainer_python}' not found in PATH",
    ))

    # Node.js
    node_path = shutil.which("node")
    checks.append(PrereqStatus(
        name="node",
        available=node_path is not None,
        path=node_path or "",
        message="" if node_path else "Node.js not found — install the version required by the upstream checkout",
    ))

    # FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    checks.append(PrereqStatus(
        name="ffmpeg",
        available=ffmpeg_path is not None,
        path=ffmpeg_path or "",
        message="" if ffmpeg_path else "FFmpeg not found — install via 'brew install ffmpeg'",
    ))

    # Explainer path
    explainer_ok = bool(cfg.explainer_path) and Path(cfg.explainer_path).is_dir()
    checks.append(PrereqStatus(
        name="explainer_path",
        available=explainer_ok,
        path=cfg.explainer_path,
        message="" if explainer_ok else "Set EXPLAINER_PATH in ~/.config/video-research-mcp/.env",
    ))

    # Console script (video-explainer CLI installed in upstream venv)
    script = Path(cfg.explainer_path) / ".venv" / "bin" / "video-explainer" if cfg.explainer_path else Path("")
    script_ok = explainer_ok and script.is_file()
    checks.append(PrereqStatus(
        name="console_script",
        available=script_ok,
        path=str(script) if script_ok else "",
        message="" if script_ok else f"Run: cd {cfg.explainer_path} && uv pip install -e .",
    ))

    # Remotion npm dependencies
    remotion_dir = Path(cfg.explainer_path) / "remotion" / "node_modules" / "@remotion" if cfg.explainer_path else Path("")
    remotion_ok = explainer_ok and remotion_dir.is_dir()
    checks.append(PrereqStatus(
        name="remotion",
        available=remotion_ok,
        path=str(remotion_dir) if remotion_ok else "",
        message="" if remotion_ok else f"Run: cd {cfg.explainer_path}/remotion && npm install",
    ))

    return PrereqReport(
        all_ok=all(c.available for c in checks),
        checks=checks,
    )
