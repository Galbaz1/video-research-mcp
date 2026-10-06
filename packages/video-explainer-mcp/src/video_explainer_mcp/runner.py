"""Central subprocess executor for the video_explainer CLI."""

from __future__ import annotations

import asyncio
import logging
import json
import tempfile
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import ServerConfig, get_config
from .errors import SubprocessError
from .redaction import redact_text
from .media_process import _read_bounded, _reap_uninterruptibly

logger = logging.getLogger(__name__)

SIGTERM_GRACE_SECONDS = 5
SIGKILL_REAP_SECONDS = 5


async def _stop_owned_process(proc: asyncio.subprocess.Process) -> None:
    """Stop the owned group even after its leader exits, with bounded pipe joins."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        elif proc.returncode is None:
            proc.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(proc.communicate(), timeout=SIGTERM_GRACE_SECONDS)
    except TimeoutError:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            elif proc.returncode is None:
                proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.communicate(), timeout=SIGKILL_REAP_SECONDS)
        except TimeoutError as exc:
            raise RuntimeError("Owned CLI cleanup unverified: process pipes did not close") from exc


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
    cleanup: dict | None = None


def _custody_read(custody: tuple) -> None:
    """Join only this invocation's bounded, token-bound browser launch record."""
    path, receipt, _ = custody
    with path.open("rb") as stream:
        body = stream.read(4097)
    if len(body) > 4096:
        raise RuntimeError("Browser custody exceeds 4096 bytes")
    for line in body.splitlines():
        record = json.loads(line)
        if record.get("schema") != "vrm-browser-custody/r1" or record.get("execution_token") != receipt["execution_token"]:
            raise RuntimeError("Browser custody binding differs")
        if record["state"] == "launching":
            if not receipt["browser"].get("known"):
                receipt["browser"] = {"state": "launching", "known": False}
        elif record["state"] == "registered":
            pid = record["browser_pid"]
            if type(pid) is not int or pid <= 1 or pid == receipt["node"]["pid"] or record["browser_pgid"] != pid:
                raise RuntimeError("Browser custody PID/group invalid")
            receipt["browser"] = {"state": "registered", "known": True, "pid": pid, "pgid": pid}
            try:
                if os.getpgid(pid) != pid:
                    raise RuntimeError("Browser detached group differs")
            except ProcessLookupError:
                pass
        else:
            raise RuntimeError("Unsupported browser custody state")


async def _watch_custody(custody: tuple) -> None:
    """Checkpoint registration independently of stdout collection and completion."""
    last = None
    while True:
        try:
            _custody_read(custody)
        except json.JSONDecodeError:
            await asyncio.sleep(0.01)
            continue
        receipt, publish = custody[1:]
        current = json.dumps(receipt)
        if current != last and publish:
            publish(receipt)
        last = current
        await asyncio.sleep(0.01)


async def _sweep_group(pid: int) -> dict:
    """Bound short EPERM drain, signal the known group once, and require ESRCH."""
    outcome = {"pid": pid, "pgid": pid, "signals": [], "permission_denials": 0,
               "group_absent": False, "pid_absent": False}
    for attempt in range(101):
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            outcome["group_absent"] = True
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                outcome["pid_absent"] = True
                return outcome
            except PermissionError:
                outcome["permission_denials"] += 1
        except PermissionError:
            outcome["permission_denials"] += 1
        if attempt == 0 and not outcome["group_absent"]:
            outcome["signals"].append("SIGKILL")
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            except PermissionError:
                outcome["permission_denials"] += 1
        await asyncio.sleep(0.01)
    error = RuntimeError("Authored renderer owned group remains after cleanup")
    error.cleanup = outcome
    raise error


async def _sweep_bounded(proc: asyncio.subprocess.Process, custody: tuple | None) -> dict:
    """Sweep both owned groups even when one cleanup phase fails."""
    receipt = custody[1] if custody else {"node": {}, "browser": {"state": "not_started"}}
    receipt["verified"], errors = False, []
    try:
        await _reap_uninterruptibly(proc)
        receipt["node"] = await _sweep_group(proc.pid)
    except Exception as exc:
        errors.append(str(exc))
        receipt["node"].update(getattr(exc, "cleanup", {"group_absent": False}))
    try:
        if custody:
            _custody_read(custody)
    except Exception as exc:
        errors.append(str(exc))
    try:
        if receipt["browser"].get("known"):
            receipt["browser"].update(await _sweep_group(receipt["browser"]["pid"]))
        elif receipt["browser"]["state"] == "launching":
            errors.append("Browser launch custody unknown; no orphan absence proof")
    except Exception as exc:
        errors.append(str(exc))
        receipt["browser"].update(getattr(exc, "cleanup", {"group_absent": False}))
    receipt["verified"] = not errors
    if errors:
        receipt["error"] = "; ".join(errors)
    if custody and custody[2]:
        custody[2](receipt)
    if errors:
        raise RuntimeError(receipt["error"])
    return receipt


async def _finish_bounded(proc: asyncio.subprocess.Process, custody: tuple | None = None) -> dict:
    """Finish custody cleanup before acknowledging repeated cancellation."""
    cleanup = asyncio.create_task(_sweep_bounded(proc, custody))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    receipt = cleanup.result()
    if cancelled:
        raise asyncio.CancelledError
    return receipt


async def _spawn_cli(cmd: list[str], cwd: str | None, bounded: bool, custody: tuple | None):
    """Acquire the spawn handle despite repeated cancellation before cleanup."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")}
    if bounded:
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}}
    if custody:
        env["VRM_RENDER_CUSTODY_FILE"] = str(custody[0])
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env,
        start_new_session=os.name == "posix", stdin=asyncio.subprocess.DEVNULL if bounded else None))
    cancelled = False
    while not spawn.done():
        try:
            await asyncio.shield(spawn)
        except asyncio.CancelledError:
            cancelled = True
    return spawn.result(), cancelled


async def _join_readers(tasks: list) -> bool:
    """Join cancelled pipe readers before the process reaper can acquire streams."""
    for task in tasks:
        if not task.done():
            task.cancel()
    joined = asyncio.gather(*tasks, return_exceptions=True)
    cancelled = False
    while not joined.done():
        try:
            await asyncio.shield(joined)
        except asyncio.CancelledError:
            cancelled = True
    return cancelled


async def _invoke_cli(
    cmd: list[str], cwd: str | None, timeout: int, process_started: Callable[[int], None] | None,
    *, bounded: bool = False, custody: tuple | None = None,
) -> tuple[bytes, bytes, int]:
    """Hold Node and browser custody across output, timeout and cancellation."""
    proc, cancelled = await _spawn_cli(cmd, cwd, bounded, custody)
    watcher, collection = None, None
    if custody:
        custody[1]["node"] = {"pid": proc.pid, "pgid": proc.pid}
        watcher = asyncio.create_task(_watch_custody(custody))
    try:
        if cancelled:
            raise asyncio.CancelledError
        if process_started:
            process_started(proc.pid)
        collect = _collect_bounded(proc) if bounded else proc.communicate()
        collection = asyncio.create_task(collect)
        if watcher:
            done, _ = await asyncio.wait({collection, watcher}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                watcher.result()
            if collection not in done:
                raise TimeoutError()
        stdout, stderr = await asyncio.wait_for(collection, timeout=timeout)
        return stdout, stderr, proc.returncode or 0
    except (Exception, asyncio.CancelledError):
        if not bounded:
            await _stop_owned_process(proc)
        raise
    finally:
        tasks = [task for task in (collection, watcher) if task]
        cancelled = await _join_readers(tasks) or cancelled
        if bounded:
            await _finish_bounded(proc, custody)
        if cancelled:
            raise asyncio.CancelledError


async def _collect_bounded(proc: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
    """Join capped pipe readers before cleanup can acquire their streams."""
    tasks = [asyncio.create_task(_read_bounded(stream)) for stream in (proc.stdout, proc.stderr)]
    tasks.append(asyncio.create_task(proc.wait()))
    try:
        stdout, stderr, _ = await asyncio.gather(*tasks)
        return stdout, stderr
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_cli(
    *args: str,
    timeout: int | None = None,
    cwd: str | None = None,
    process_started: Callable[[int], None] | None = None,
) -> SubprocessResult:
    """Run the explainer CLI with the given arguments.

    Uses ``asyncio.create_subprocess_exec`` with an argument list (never
    shell=True) to prevent command injection. On timeout, sends SIGTERM,
    waits 5s, then SIGKILL.

    Args:
        *args: CLI arguments (e.g. ``"create"``, ``"my-project"``).
        timeout: Max seconds to wait. Defaults to ``config.timeout``.
        cwd: Working directory. Defaults to ``config.explainer_path``.
        process_started: Persist the operation identity after obtaining the owned Process.

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

    stdout_bytes, stderr_bytes, returncode = await _invoke_cli(cmd, cwd, timeout, process_started)

    elapsed = time.monotonic() - start
    stdout = redact_text(stdout_bytes.decode("utf-8", errors="replace"))
    stderr = redact_text(stderr_bytes.decode("utf-8", errors="replace"))

    result = SubprocessResult(
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
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


async def run_entry(
    cmd: list[str], *, cwd: str, timeout: int, process_started: Callable[[int], None],
    dispatch_updated: Callable[[dict], None] | None = None,
) -> SubprocessResult:
    """Run the frozen argv with durable bounded browser custody independent of pipes."""
    start = time.monotonic()
    receipt = {"execution_token": cmd[-1], "node": {}, "browser": {"state": "not_started"}, "verified": False}
    with tempfile.TemporaryDirectory(prefix="vrm-render-custody-") as directory:
        path = Path(directory) / "browser.jsonl"
        path.touch(mode=0o600)
        stdout, stderr, code = await _invoke_cli(cmd, cwd, timeout, process_started, bounded=True,
                                              custody=(path, receipt, dispatch_updated))
    result = SubprocessResult(redact_text(stdout.decode("utf-8", errors="replace")),
                              redact_text(stderr.decode("utf-8", errors="replace")), code,
                              round(time.monotonic() - start, 2), cmd, receipt)
    if code:
        raise SubprocessError(cmd, code, result.stdout, result.stderr)
    return result
