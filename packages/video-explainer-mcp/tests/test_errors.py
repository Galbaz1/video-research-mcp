"""Tests for error handling module."""

from __future__ import annotations

import pytest

from video_explainer_mcp.errors import (
    ErrorCategory,
    SubprocessError,
    categorize_error,
    make_tool_error,
)

pytestmark = pytest.mark.unit


class TestSubprocessError:
    """Tests for SubprocessError exception."""

    def test_attributes(self):
        """Stores command, returncode, stdout, stderr."""
        err = SubprocessError(["cli", "render"], 1, stdout="out", stderr="fail")
        assert err.command == ["cli", "render"]
        assert err.returncode == 1
        assert err.stdout == "out"
        assert err.stderr == "fail"
        assert "exited with code 1" in str(err)


class TestCategorizeError:
    """Tests for error categorization from stderr patterns."""

    def test_project_exists(self):
        """Detects 'already exists' in subprocess output."""
        err = SubprocessError(["cli", "create"], 1, stderr="Project already exists")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.PROJECT_EXISTS

    def test_project_not_found(self):
        """Detects 'project not found' in subprocess output."""
        err = SubprocessError(["cli", "status"], 1, stderr="Project not found: foo")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.PROJECT_NOT_FOUND

    def test_remotion_not_installed(self):
        """Detects Remotion missing."""
        err = SubprocessError(["cli", "render"], 1, stderr="remotion not installed")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.REMOTION_NOT_INSTALLED

    def test_ffmpeg_not_found(self):
        """Detects FFmpeg missing."""
        err = SubprocessError(["cli", "render"], 1, stderr="ffmpeg not found")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.FFMPEG_NOT_FOUND

    def test_node_not_found(self):
        """Detects Node.js missing."""
        err = SubprocessError(["cli", "render"], 1, stderr="node not found")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.NODE_NOT_FOUND

    def test_tts_failed(self):
        """Detects TTS errors."""
        err = SubprocessError(["cli", "voiceover"], 1, stderr="elevenlabs API error")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.TTS_FAILED

    def test_render_failed(self):
        """Detects render errors."""
        err = SubprocessError(["cli", "render"], 1, stderr="Render failed: out of memory")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.RENDER_FAILED

    def test_killed_process(self):
        """Detects SIGKILL (exit -9)."""
        err = SubprocessError(["cli", "render"], -9)
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.SUBPROCESS_CRASHED

    def test_generic_subprocess_failure(self):
        """Falls through to generic subprocess failure."""
        err = SubprocessError(["cli", "foo"], 42, stderr="something weird")
        cat, _ = categorize_error(err)
        assert cat == ErrorCategory.SUBPROCESS_FAILED

    def test_timeout(self):
        """Detects timeout from non-subprocess exception."""
        cat, _ = categorize_error(TimeoutError("timed out"))
        assert cat == ErrorCategory.SUBPROCESS_TIMEOUT

    def test_file_not_found(self):
        """Detects FileNotFoundError."""
        cat, _ = categorize_error(FileNotFoundError("no such file"))
        assert cat == ErrorCategory.EXPLAINER_NOT_FOUND


class TestMakeToolError:
    """Tests for make_tool_error serialization."""

    def test_returns_dict(self):
        """Returns a serializable dict with expected keys."""
        err = SubprocessError(["cli"], 1, stderr="Project not found: x")
        result = make_tool_error(err)
        assert isinstance(result, dict)
        assert result["category"] == "PROJECT_NOT_FOUND"
        assert "error" in result
        assert "hint" in result
        assert result["retryable"] is False

    def test_timeout_is_retryable(self):
        """Timeout errors are marked retryable."""
        result = make_tool_error(TimeoutError("timed out"))
        assert result["retryable"] is True


def test_render_missing_artifact_has_render_hint():
    """An absent new render is classified as a render failure, not missing CLI setup."""
    result = make_tool_error(FileNotFoundError(
        "Render exited successfully but produced no new nonempty video"
    ))
    assert result["category"] == "RENDER_FAILED"
    assert "fresh video" in result["hint"]


def test_empty_timeout_exception_is_classified():
    """Timeout exceptions need no message to receive the actionable timeout category."""
    assert make_tool_error(TimeoutError())["category"] == "SUBPROCESS_TIMEOUT"
