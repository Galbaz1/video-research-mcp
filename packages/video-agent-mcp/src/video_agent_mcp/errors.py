"""Structured error handling for video-agent-mcp tools."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .redaction import redact_text


class ErrorCategory(str, Enum):
    """Categories of errors for diagnostics."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    SCRIPT_NOT_FOUND = "SCRIPT_NOT_FOUND"
    SCENES_EXIST = "SCENES_EXIST"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_ERROR = "AGENT_ERROR"
    CODE_EXTRACTION_FAILED = "CODE_EXTRACTION_FAILED"
    FILE_WRITE_ERROR = "FILE_WRITE_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    UNKNOWN = "UNKNOWN"


class ToolError(BaseModel):
    """Structured error returned from any tool."""

    error: str
    category: str
    hint: str
    retryable: bool = False


def categorize_error(error: Exception) -> tuple[ErrorCategory, str]:
    """Map an exception to an ErrorCategory + human-readable hint."""
    s = str(error).lower()

    if isinstance(error, FileNotFoundError):
        if "script" in s:
            return (
                ErrorCategory.SCRIPT_NOT_FOUND,
                "script.json not found — run explainer_create + explainer_inject first",
            )
        return (
            ErrorCategory.PROJECT_NOT_FOUND,
            "Project directory not found — check EXPLAINER_PATH and project_id",
        )
    if isinstance(error, FileExistsError):
        return (
            ErrorCategory.SCENES_EXIST,
            "Scenes already exist — use force=True to overwrite",
        )
    if "timeout" in s or "timed out" in s:
        return (
            ErrorCategory.AGENT_TIMEOUT,
            "Agent query timed out — try increasing AGENT_TIMEOUT or reducing concurrency",
        )
    if "claude" in s or "agent" in s or "sdk" in s:
        return (
            ErrorCategory.AGENT_ERROR,
            "Agent SDK error — check that Claude Code CLI is installed and ANTHROPIC_API_KEY is set",
        )
    return (ErrorCategory.UNKNOWN, str(error))


def make_tool_error(error: Exception) -> dict:
    """Create a serialisable ToolError dict from an exception."""
    cat, hint = categorize_error(error)
    retryable = cat in {
        ErrorCategory.AGENT_TIMEOUT,
        ErrorCategory.AGENT_ERROR,
    }
    return ToolError(
        error=redact_text(str(error)),
        category=cat.value,
        hint=redact_text(hint),
        retryable=retryable,
    ).model_dump()
