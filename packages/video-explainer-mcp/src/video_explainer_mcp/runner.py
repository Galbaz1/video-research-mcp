"""Central subprocess executor for the video_explainer CLI."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ServerConfig, get_config
from .errors import SubprocessError

logger = logging.getLogger(__name__)

SIGTERM_GRACE_SECONDS = 5


def _resolve_cli(cfg: ServerConfig) -> str:
    """Resolve the upstream video-explainer console script path."""
    if not cfg.explainer_path:
        raise FileNotFoundError(
            "EXPLAINER_PATH not set — configure in ~/.config/video-research-mcp/.env"
        )
    script = Path(cfg.explainer_path).expanduser().resolve() / ".venv" / "bin" / "video-explainer"
    if not script.is_file():
        raise FileNotFoundError(
            f"Console script not found: {script}\n"
            f"Run: cd {cfg.explainer_path} && uv pip install -e ."
        )
    return str(script)


@dataclass(frozen=True)
class SubprocessResult:
    """Immutable result of a subprocess execution."""

    stdout: str
    stderr: str
    returncode: int
    duration_seconds: float
    command: list[str]


async def run_cli(
    *args: str,
    timeout: int | None = None,
    cwd: str | None = None,
) -> SubprocessResult:
    """Run the explainer CLI with the given arguments.

    Uses ``asyncio.create_subprocess_exec`` with an argument list (never
    shell=True) to prevent command injection. On timeout, sends SIGTERM,
    waits 5s, then SIGKILL.

    Args:
        *args: CLI arguments (e.g. ``"create"``, ``"my-project"``).
        timeout: Max seconds to wait. Defaults to ``config.timeout``.
        cwd: Working directory. Defaults to ``config.explainer_path``.

    Returns:
        SubprocessResult with stdout, stderr, returncode, duration.

    Raises:
        SubprocessError: On non-zero exit code.
        FileNotFoundError: When explainer CLI is not found.
        asyncio.TimeoutError: When process exceeds timeout.
    """
    cfg = get_config()
    if timeout is None:
        timeout = cfg.timeout
    if cwd is None:
        cwd = str(Path(cfg.explainer_path).expanduser().resolve()) if cfg.explainer_path else None

    script = _resolve_cli(cfg)
    cmd = [script, "--projects-dir", str(cfg.resolved_projects_path), *args]
    logger.info("Running: %s (timeout=%ds)", " ".join(cmd), timeout)
    start = time.monotonic()

    env = {
        k: v
        for k, v in os.environ.items()
        if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")
    }
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except (TimeoutError, asyncio.CancelledError):
        logger.warning("Process interrupted, sending SIGTERM")
        proc.terminate()
        try:
            await asyncio.wait_for(proc.communicate(), timeout=SIGTERM_GRACE_SECONDS)
        except TimeoutError:
            logger.warning("Process did not exit after SIGTERM, sending SIGKILL")
            proc.kill()
            await proc.communicate()
        raise

    elapsed = time.monotonic() - start
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    result = SubprocessResult(
        stdout=stdout,
        stderr=stderr,
        returncode=proc.returncode or 0,
        duration_seconds=round(elapsed, 2),
        command=cmd,
    )

    if result.returncode != 0:
        logger.error(
            "CLI failed (exit %d): %s\nstderr: %s",
            result.returncode,
            " ".join(cmd),
            stderr[:500],
        )
        raise SubprocessError(cmd, result.returncode, stdout, stderr)

    logger.info("CLI completed in %.1fs", elapsed)
    return result
