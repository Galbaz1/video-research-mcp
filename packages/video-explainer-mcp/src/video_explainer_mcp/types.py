"""Shared type aliases for tool parameters."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

# ── Literal enums ────────────────────────────────────────────────────────────

PipelineStep = Literal["script", "narration", "scenes", "voiceover", "storyboard"]
RefinePhase = Literal["script"]
SoundAction = Literal["analyze", "generate"]
RenderResolution = Literal["720p", "1080p", "4k"]
TtsProvider = Literal["mock", "elevenlabs", "edge"]

# ── Annotated aliases ────────────────────────────────────────────────────────

ProjectId = Annotated[str, Field(
    min_length=1,
    max_length=100,
    pattern=r"^[a-zA-Z0-9_-]+$",
    description="Project identifier (alphanumeric, hyphens, underscores)",
)]
