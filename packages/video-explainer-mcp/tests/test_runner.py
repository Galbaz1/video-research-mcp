"""Tests for the subprocess runner."""

from __future__ import annotations

import asyncio
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
        proc.returncode = -15
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

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
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
    proc.communicate.side_effect = [asyncio.CancelledError(), (b"", b"")]
    with (
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
        pytest.raises(asyncio.CancelledError),
    ):
        await run_cli("render", "test")
    proc.terminate.assert_called_once()
    assert proc.communicate.await_count == 2
