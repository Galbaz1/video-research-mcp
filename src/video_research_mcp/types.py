"""Shared type aliases and helpers for tool parameters."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import Field


def coerce_json_param(value: str | dict | list | None, expected_type: type) -> dict | list | None:
    """Parse MCP JSON-RPC string params back to dict/list.

    MCP JSON-RPC transport may serialize dict/list params as JSON strings.
    Pydantic v2 rejects these — this helper coerces them back.

    Args:
        value: The parameter value (possibly a JSON string).
        expected_type: Expected Python type (``dict`` or ``list``).

    Returns:
        Parsed value if coercion succeeded, original value otherwise.
    """
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, expected_type):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return value


def coerce_string_list_param(
    value: str | list | None,
    *,
    param_name: str,
    allow_empty: bool = True,
) -> list[str] | None:
    """Coerce and validate a tool parameter as a list of non-empty strings.

    Args:
        value: Raw MCP parameter value, possibly JSON-stringified.
        param_name: Parameter name for human-readable validation errors.
        allow_empty: Whether an empty list is accepted.

    Returns:
        Validated list of stripped strings, or ``None`` when unset.

    Raises:
        ValueError: If the value is not a list of non-empty strings.
    """
    if value is None:
        return None

    coerced = coerce_json_param(value, list)
    if not isinstance(coerced, list):
        raise ValueError(f"'{param_name}' must be a list of strings")

    values: list[str] = []
    for idx, item in enumerate(coerced):
        if not isinstance(item, str):
            raise ValueError(f"'{param_name}[{idx}]' must be a string")
        item = item.strip()
        if not item:
            raise ValueError(f"'{param_name}[{idx}]' must not be empty")
        values.append(item)

    if not allow_empty and not values:
        raise ValueError(f"'{param_name}' must contain at least one item")

    return values

# ── Literal enums ────────────────────────────────────────────────────────────

ThinkingLevel = Literal["minimal", "low", "medium", "high"]
Scope = Literal["quick", "moderate", "deep", "comprehensive"]
CacheAction = Literal["stats", "list", "clear", "context"]
ModelPreset = Literal["best", "stable", "budget"]
KnowledgeCollection = Literal[
    "ResearchFindings", "VideoAnalyses", "ContentAnalyses",
    "VideoMetadata", "SessionTranscripts", "WebSearchResults", "ResearchPlans",
    "CommunityReactions", "ConceptKnowledge", "RelationshipEdges", "CallNotes",
]

# ── Annotated aliases ────────────────────────────────────────────────────────

YouTubeUrl = Annotated[str, Field(min_length=10, description="YouTube video URL (youtube.com or youtu.be)")]
TopicParam = Annotated[str, Field(min_length=3, max_length=2000, description="Research topic or question")]
VideoFilePath = Annotated[str, Field(
    min_length=1,
    description="Path to a local video file (mp4, webm, mov, avi, mkv, mpeg, wmv, 3gpp)",
)]
VideoDirectoryPath = Annotated[str, Field(
    min_length=1,
    description="Path to a directory containing video files",
)]
ContentDirectoryPath = Annotated[str, Field(
    min_length=1,
    description="Path to a directory containing content files (PDF, text, HTML, etc.)",
)]
ContentBatchMode = Literal["compare", "individual"]
PlaylistUrl = Annotated[str, Field(
    min_length=10,
    description="YouTube playlist URL (must contain 'list=' parameter)",
)]
