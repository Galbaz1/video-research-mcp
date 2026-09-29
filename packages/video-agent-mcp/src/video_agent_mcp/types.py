"""Shared types for video-agent-mcp."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated

from pydantic import Field

# Annotated type for project IDs used across tool parameters.
ProjectId = Annotated[str, Field(
    min_length=1,
    max_length=100,
    pattern=r"^[a-zA-Z0-9_-]+$",
    description="Project identifier under the explainer projects directory",
)]


@dataclass(frozen=True)
class AgentResult:
    """Result from a single Agent SDK query."""

    text: str
    success: bool
    duration_seconds: float
    error: str | None = None


@dataclass
class SceneResult:
    """Result for a single scene generation attempt."""

    scene_number: int
    title: str
    component_name: str
    filename: str
    scene_key: str
    success: bool
    error: str | None = None


@dataclass
class GenerationSummary:
    """Aggregate result of a parallel scene generation run."""

    scenes: list[SceneResult] = field(default_factory=list)
    errors: list[SceneResult] = field(default_factory=list)
    wall_clock_seconds: float = 0.0
    scenes_dir: str = ""
