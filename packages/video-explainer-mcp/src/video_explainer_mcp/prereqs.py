"""Explicit renderer, generation and provider prerequisites without provider requests."""

from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from .config import get_config
from .media_process import run_media_process
from .render_contract import project_contract, source_contract
from .planning_sources import read_object
from .render_validation import codec_executables


class PrereqStatus(BaseModel):
    """Observed availability of one local prerequisite."""

    name: str
    available: bool
    path: str = ""
    message: str = ""
    version: str = "not checked"


class PrereqReport(BaseModel):
    """Technical readiness, separate from provider access, grants and output acceptance."""

    all_ok: bool = False
    checks: list[PrereqStatus] = Field(default_factory=list)
    source: dict = Field(default_factory=dict)
    project: dict = Field(default_factory=dict)
    capabilities: dict = Field(default_factory=dict)
    provider_calls: int = 0


def _browser(directory: Path) -> Path | None:
    """Resolve the selected Remotion4.0.242 public CLI's ordinary cache location."""
    system, machine = platform.system(), platform.machine().lower()
    platforms = {
        ("Darwin", "arm64"): "mac-arm64",
        ("Darwin", "x86_64"): "mac-x64",
        ("Linux", "x86_64"): "linux64",
        ("Windows", "amd64"): "win64",
    }
    name = platforms.get((system, machine))
    if not name:
        return None
    binary = "chrome-headless-shell.exe" if name == "win64" else "chrome-headless-shell"
    return (
        directory
        / "remotion/node_modules/.remotion/chrome-headless-shell"
        / name
        / f"chrome-headless-shell-{name}"
        / binary
    )


def _renderer_checks(directory: Path | None) -> list[PrereqStatus]:
    """Inspect the selected ordinary Node installation without loading its modules."""
    console = directory / ".venv/bin/video-explainer" if directory else None
    checks = [
        PrereqStatus(
            name="console_script",
            available=bool(console) and console.is_file() and os.access(console, os.X_OK),
            path=str(console or ""),
        )
    ]
    for name in ("renderer", "bundler", "remotion"):
        package = "remotion" if name == "remotion" else "@remotion/" + name
        path = directory / "remotion/node_modules" / package / "package.json" if directory else None
        try:
            if path is None:
                raise ValueError("EXPLAINER_PATH is not configured")
            value, _ = read_object(path, directory)
            version = value["version"]
            if not isinstance(version, str):
                raise ValueError("Renderer package version must be a string")
            available = version == "4.0.242"
        except (OSError, ValueError, KeyError):
            version, available = "missing or unreadable", False
        checks.append(
            PrereqStatus(name=name, available=available, path=str(path or ""), version=version)
        )
    browser = _browser(directory) if directory else None
    checks.append(
        PrereqStatus(
            name="browser",
            available=bool(browser) and browser.is_file() and os.access(browser, os.X_OK),
            path=str(browser or ""),
            message="Cached headless-shell required; doctor does not download or launch a browser",
        )
    )
    return checks


def check_prereqs(project_id: str | None = None) -> PrereqReport:
    """Inspect local prerequisites and exact mapped source before any render work."""
    cfg = get_config()
    directory = Path(cfg.explainer_path).expanduser().resolve() if cfg.explainer_path else None
    checks = []
    for name in ("node", "ffmpeg", "ffprobe", "claude"):
        found = shutil.which(name)
        checks.append(
            PrereqStatus(
                name=name,
                available=bool(found),
                path=found or "",
                message="" if found else f"{name} is not available in PATH",
            )
        )
    checks.extend(_renderer_checks(directory))
    source = (
        source_contract(directory)
        if directory
        else {"mapped_source_verified": False, "errors": ["EXPLAINER_PATH is not configured"]}
    )
    project = {}
    if project_id is not None:
        target = (cfg.resolved_projects_path / project_id).resolve()
        try:
            if not target.is_relative_to(cfg.resolved_projects_path):
                raise ValueError("Project resolves outside configured root")
            project = {"supported": True, **project_contract(target, "720p")}
        except (OSError, ValueError) as exc:
            project = {"supported": False, "error": str(exc)}
    required = [c for c in checks if c.name != "claude"]
    ready = (
        all(c.available for c in required)
        and source["mapped_source_verified"]
        and project.get("supported", True)
    )
    return PrereqReport(
        all_ok=ready,
        checks=checks,
        source=source,
        project=project,
        capabilities={
            "real_render": {"prerequisites_present": ready, "execution_verified": False},
            "generation": {"claude_present": checks[3].available, "provider_access": "not checked"},
            "tts": {
                "configured_provider": cfg.tts_provider,
                "credential_present": bool(cfg.elevenlabs_api_key)
                if cfg.tts_provider == "elevenlabs"
                else None,
                "provider_access": "not checked",
                "actual_audio_provenance": "unknown",
            },
            "mock_pipeline_fallback": "possible in foreign full generate; cannot prove real completion",
        },
    )


async def doctor(project_id: str | None = None) -> PrereqReport:
    """Read native versions with bounded owned subprocesses; make no provider call."""
    report = check_prereqs(project_id)
    for check in report.checks:
        if not check.available or check.name not in ("node", "ffmpeg", "ffprobe"):
            continue
        argument = "--version" if check.name == "node" else "-version"
        try:
            stdout, _ = await run_media_process([check.path, argument], 10.0)
            lines = stdout.decode(errors="replace").splitlines()
            if not lines:
                raise ValueError("Native version response is empty")
            check.version = lines[0][:256]
            if check.name == "node":
                match = re.fullmatch(r"v(\d+)\.\d+\.\d+", check.version)
                if not match or int(match[1]) < 20:
                    raise ValueError("Selected renderer requires Node 20 or newer")
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            check.available = False
            check.message = str(exc)
    cfg = get_config()
    if cfg.explainer_path:
        report.source = source_contract(Path(cfg.explainer_path).expanduser().resolve())
    report.all_ok = (
        report.all_ok
        and report.source["mapped_source_verified"]
        and all(c.available for c in report.checks if c.name != "claude")
    )
    report.capabilities["real_render"]["prerequisites_present"] = report.all_ok
    if report.all_ok:
        report.capabilities["qualification_executables"] = codec_executables()
    return report


async def require_render_ready(project_id: str | None) -> None:
    """Stop unavailable or unsupported rendering before allocating a production job."""
    report = await doctor(project_id)
    if not report.all_ok:
        missing = [c.name for c in report.checks if not c.available and c.name != "claude"]
        errors = report.source["errors"] + (
            [report.project["error"]] if report.project.get("error") else []
        )
        raise RuntimeError("Renderer prerequisites unavailable: " + "; ".join(missing + errors))
