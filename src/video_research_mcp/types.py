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

# ── Literal enums ────────────────────────────────────────────────────────────

ThinkingLevel = Literal["minimal", "low", "medium", "high"]
Scope = Literal["quick", "moderate", "deep", "comprehensive"]
CacheAction = Literal["stats", "list", "clear", "context"]
ModelPreset = Literal["best", "stable", "budget"]
KnowledgeCollection = Literal[
    "ResearchFindings", "VideoAnalyses", "ContentAnalyses",
    "VideoMetadata", "SessionTranscripts", "WebSearchResults", "ResearchPlans",
    "CommunityReactions", "ConceptKnowledge", "RelationshipEdges", "CallNotes",
    "DeepResearchReports",
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
