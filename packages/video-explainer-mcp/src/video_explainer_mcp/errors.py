"""Structured error handling for video explainer subprocess operations."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ErrorCategory(str, Enum):
    """Categories of errors for diagnostics."""

    EXPLAINER_NOT_FOUND = "EXPLAINER_NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_EXISTS = "PROJECT_EXISTS"
    SUBPROCESS_TIMEOUT = "SUBPROCESS_TIMEOUT"
    SUBPROCESS_FAILED = "SUBPROCESS_FAILED"
    SUBPROCESS_CRASHED = "SUBPROCESS_CRASHED"
    STEP_FAILED = "STEP_FAILED"
    RENDER_FAILED = "RENDER_FAILED"
    TTS_FAILED = "TTS_FAILED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    FFMPEG_NOT_FOUND = "FFMPEG_NOT_FOUND"
    REMOTION_NOT_INSTALLED = "REMOTION_NOT_INSTALLED"
    UNKNOWN = "UNKNOWN"


class SubprocessError(Exception):
    """Raised when the explainer CLI exits with a non-zero code."""

    def __init__(
        self,
        command: list[str],
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"Command {' '.join(command)!r} exited with code {returncode}"
        )


class ToolError(BaseModel):
    """Structured error returned from any tool."""

    error: str
    category: str
    hint: str
    retryable: bool = False


def categorize_error(error: Exception) -> tuple[ErrorCategory, str]:
    """Map an exception to an ErrorCategory + human-readable hint."""
    s = str(error).lower()

    if isinstance(error, SubprocessError):
        combined = f"{error.stdout} {error.stderr}".lower()

        if "already exists" in combined:
            return (
                ErrorCategory.PROJECT_EXISTS,
                "Project already exists — use a different ID or delete the existing one",
            )
        if "not found" in combined and "project" in combined:
            return (
                ErrorCategory.PROJECT_NOT_FOUND,
                "Project not found — check the project ID with explainer_list",
            )
        if "remotion" in combined and ("not found" in combined or "not installed" in combined):
            return (
                ErrorCategory.REMOTION_NOT_INSTALLED,
                "Remotion not installed — run 'npm install' in the explainer directory",
            )
        if "ffmpeg" in combined and "not found" in combined:
            return (
                ErrorCategory.FFMPEG_NOT_FOUND,
                "FFmpeg not found — install via 'brew install ffmpeg' or equivalent",
            )
        if "node" in combined and "not found" in combined:
            return (
                ErrorCategory.NODE_NOT_FOUND,
                "Node.js not found — install the Node.js version required by the upstream checkout",
            )
        if "tts" in combined or "voice" in combined or "elevenlabs" in combined:
            return (
                ErrorCategory.TTS_FAILED,
                "TTS generation failed — check TTS provider config and API key",
            )
        if "render" in combined:
            return (
                ErrorCategory.RENDER_FAILED,
                "Video render failed — check Remotion setup and project assets",
            )
        if error.returncode == -9 or error.returncode == -15:
            return (
                ErrorCategory.SUBPROCESS_CRASHED,
                "Process was killed (likely OOM or signal) — try reducing resolution",
            )
        return (
            ErrorCategory.SUBPROCESS_FAILED,
            f"CLI command failed (exit {error.returncode}) — check stderr for details",
        )

    if isinstance(error, TimeoutError) or "timeout" in s or "timed out" in s:
        return (
            ErrorCategory.SUBPROCESS_TIMEOUT,
            "Operation timed out — increase timeout or use background render",
        )
    if "render exited successfully" in s:
        return (
            ErrorCategory.RENDER_FAILED,
            "CLI reported success but no fresh video was produced — inspect the render output",
        )
    if "no such file" in s or "not found" in s or isinstance(error, FileNotFoundError):
        return (
            ErrorCategory.EXPLAINER_NOT_FOUND,
            "Explainer CLI not found — set EXPLAINER_PATH in ~/.config/video-research-mcp/.env",
        )

    return (ErrorCategory.UNKNOWN, str(error))


def make_tool_error(error: Exception) -> dict:
    """Create a serialisable ToolError dict from an exception."""
    cat, hint = categorize_error(error)
    retryable = cat in {
        ErrorCategory.SUBPROCESS_TIMEOUT,
        ErrorCategory.TTS_FAILED,
    }
    return ToolError(
        error=str(error),
        category=cat.value,
        hint=hint,
        retryable=retryable,
    ).model_dump()
