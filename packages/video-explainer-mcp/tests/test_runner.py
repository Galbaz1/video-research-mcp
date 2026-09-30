"""Tests for the subprocess runner."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest

from video_explainer_mcp.errors import SubprocessError
from video_explainer_mcp.runner import SubprocessResult, run_cli

pytestmark = pytest.mark.unit


class TestSubprocessResult:
    """Tests for the SubprocessResult dataclass."""

    def test_frozen(self):
        """SubprocessResult is immutable."""
        r = SubprocessResult("out", "err", 0, 1.5, ["cmd"])
        with pytest.raises(AttributeError):
            r.stdout = "new"

    def test_fields(self):
        """All fields are accessible."""
        r = SubprocessResult("out", "err", 0, 1.5, ["a", "b"])
        assert r.stdout == "out"
        assert r.stderr == "err"
        assert r.returncode == 0
        assert r.duration_seconds == 1.5
        assert r.command == ["a", "b"]


class TestRunCli:
    """Tests for run_cli function."""

    async def test_success(self, mock_subprocess, mock_explainer_venv, monkeypatch):
        """Successful CLI execution returns SubprocessResult."""
        monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
        proc = mock_subprocess(returncode=0, stdout=b"OK\n", stderr=b"")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await run_cli("create", "test-project")
        assert result.stdout == "OK\n"
        assert result.returncode == 0

    async def test_failure_raises(self, mock_subprocess, mock_explainer_venv, monkeypatch):
        """Non-zero exit raises SubprocessError."""
        monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
        proc = mock_subprocess(returncode=1, stderr=b"Project not found: x")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            with pytest.raises(SubprocessError) as exc_info:
                await run_cli("status", "missing")
        assert exc_info.value.returncode == 1
        assert "Project not found" in exc_info.value.stderr

    async def test_timeout(self, mock_explainer_venv, monkeypatch):
        """Timeout sends SIGTERM then SIGKILL."""
        monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
        proc = AsyncMock()
        proc.returncode = None
        proc.pid = 12345
        proc.communicate = AsyncMock(side_effect=TimeoutError())
        proc.terminate = lambda: None
        proc.kill = lambda: None

        # After kill, communicate should return
        call_count = 0

        async def smart_communicate():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TimeoutError()
            return (b"", b"")

        proc.communicate = smart_communicate

        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
            patch("os.killpg"),
        ):
            with pytest.raises(asyncio.TimeoutError):
                await run_cli("render", "slow-project", timeout=1)

    async def test_custom_cwd(self, mock_subprocess, mock_explainer_venv, monkeypatch):
        """Custom cwd is passed to subprocess."""
        monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
        proc = mock_subprocess(returncode=0, stdout=b"OK")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            await run_cli("status", cwd="/custom/dir")
            call_kwargs = mock_exec.call_args
            assert call_kwargs.kwargs.get("cwd") == "/custom/dir"

    async def test_builds_correct_command(self, mock_subprocess, mock_explainer_venv, monkeypatch):
        """Command uses console script + --projects-dir (not python -m)."""
        monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
        proc = mock_subprocess(returncode=0, stdout=b"OK")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            await run_cli("generate", "my-project", "--mock")
            args = mock_exec.call_args.args
            # First arg is the console script path
            assert args[0].endswith("video-explainer")
            assert ".venv/bin/video-explainer" in args[0]
            # --projects-dir is injected
            assert "--projects-dir" in args
            # No python -m invocation
            assert "-m" not in args
            assert "video_explainer" not in args
            # User args are passed through
            assert "generate" in args
            assert "my-project" in args

    async def test_env_strips_claudecode(self, mock_subprocess, mock_explainer_venv, monkeypatch):
        """CLAUDECODE and CLAUDE_CODE_* env vars are stripped from subprocess."""
        monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION", "abc")
        monkeypatch.setenv("HOME", "/home/user")
        proc = mock_subprocess(returncode=0, stdout=b"OK")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)) as mock_exec:
            await run_cli("status", "test")
            env = mock_exec.call_args.kwargs.get("env", {})
            assert "CLAUDECODE" not in env
            assert "CLAUDE_CODE_SESSION" not in env
            assert "HOME" in env


async def test_cancelled_cli_terminates_process(mock_subprocess, mock_explainer_venv, monkeypatch):
    """Cancelling a background task stops and reaps its CLI process."""
    monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
    proc = mock_subprocess()
    proc.returncode = None
    proc.communicate.side_effect = [asyncio.CancelledError(), (b"", b"")]
    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        pytest.raises(asyncio.CancelledError),
        patch("os.killpg") as signal_group,
    ):
        await run_cli("render", "test")
    signal_group.assert_called_once()
    assert proc.communicate.await_count == 2


async def test_cancel_during_spawn_waits_for_owned_process_then_reaps(
    mock_subprocess,
    mock_explainer_venv,
    monkeypatch,
):
    """Cancellation cannot lose a process handle while the spawn coroutine is pending."""
    monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
    proc = mock_subprocess()
    proc.returncode = None
    spawning, release = asyncio.Event(), asyncio.Event()

    async def spawn(*args, **kwargs):
        assert kwargs["start_new_session"] is True
        spawning.set()
        await release.wait()
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=spawn),
        patch("os.killpg") as signal_group,
    ):
        task = asyncio.create_task(run_cli("render", "test"))
        await spawning.wait()
        task.cancel()
        await asyncio.sleep(0)
        signal_group.assert_not_called()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    signal_group.assert_called_once()
    proc.communicate.assert_awaited_once()


async def test_failed_process_binding_reaps_owned_process(
    mock_subprocess,
    mock_explainer_venv,
    monkeypatch,
):
    """A lost lease during process binding prevents acceptance and cleans up the new child."""
    monkeypatch.setenv("EXPLAINER_PATH", str(mock_explainer_venv))
    proc = mock_subprocess()
    proc.returncode = None

    def rejected_binding(pid):
        raise RuntimeError("ownership lost")

    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        patch("os.killpg") as signal_group,
    ):
        with pytest.raises(RuntimeError, match="ownership lost"):
            await run_cli("render", "test", process_started=rejected_binding)
    signal_group.assert_called_once()
    proc.communicate.assert_awaited_once()


@pytest.mark.skipif(os.name != "posix", reason="Owned POSIX process groups required")
@pytest.mark.parametrize("stop", ["timeout", "cancel"])
@pytest.mark.parametrize("ignore_term", [False, True])
async def test_exited_parent_with_inherited_pipe_child_is_bounded(stop, ignore_term, tmp_path):
    """Cleanup must signal the owned group after its parent exits, then join pipes."""
    from video_explainer_mcp.runner import _invoke_cli

    marker = tmp_path / "child.json"
    child_code = (
        "import json,os,pathlib,signal,time; "
        + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if ignore_term else "")
        + f"pathlib.Path({str(marker)!r}).write_text(json.dumps({{'pid':os.getpid()}})); "
        + "time.sleep(20)"
    )
    code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child_code!r}])"
    spawn = asyncio.create_subprocess_exec
    processes = []

    async def owned_spawn(*args, **kwargs):
        proc = await spawn(*args, **kwargs)
        processes.append(proc)
        return proc

    started = time.monotonic()
    with (
        patch("asyncio.create_subprocess_exec", side_effect=owned_spawn),
        patch("video_explainer_mcp.runner.SIGTERM_GRACE_SECONDS", 0.05),
        patch("os.killpg", wraps=os.killpg) as signal_group,
    ):
        task = asyncio.create_task(
            _invoke_cli([sys.executable, "-c", code], None, 0.4 if stop == "timeout" else 20, None)
        )
        try:
            async with asyncio.timeout(1):
                while not marker.exists() or not processes or processes[0].returncode is None:
                    await asyncio.sleep(0.01)
            child_pid = json.loads(marker.read_text())["pid"]
            if stop == "cancel":
                task.cancel()
            done, _ = await asyncio.wait({task}, timeout=1)
            assert task in done, "Exited-parent cleanup blocked on the inherited child pipes"
            with pytest.raises(TimeoutError if stop == "timeout" else asyncio.CancelledError):
                await task
            assert time.monotonic() - started < 1.5
            assert signal_group.call_args_list[0].args == (processes[0].pid, signal.SIGTERM)
            if ignore_term:
                assert signal_group.call_args_list[1].args == (processes[0].pid, signal.SIGKILL)
            async with asyncio.timeout(1):
                while True:
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    await asyncio.sleep(0.01)
        finally:
            for proc in processes:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


async def test_pipe_join_after_kill_is_bounded_and_unverified(mock_subprocess):
    """Unclosed pipes cannot turn cleanup into an indefinite wait or acknowledged stop."""
    from video_explainer_mcp.runner import _stop_owned_process

    proc = mock_subprocess()
    never = asyncio.Event()
    proc.communicate = AsyncMock(side_effect=never.wait)
    with (
        patch("video_explainer_mcp.runner.SIGTERM_GRACE_SECONDS", 0.02),
        patch("video_explainer_mcp.runner.SIGKILL_REAP_SECONDS", 0.02),
        patch("os.killpg") as signal_group,
    ):
        async with asyncio.timeout(0.2):
            with pytest.raises(RuntimeError, match="cleanup unverified"):
                await _stop_owned_process(proc)
    assert [call.args[1] for call in signal_group.call_args_list] == [
        signal.SIGTERM,
        signal.SIGKILL,
    ]
    assert proc.communicate.await_count == 2
