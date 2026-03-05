"""Pydantic models for Gemini Deep Research (Interactions API) tools.

Used by research_web, research_web_status, and research_web_followup tools.
These are output models for tool responses, not Gemini structured output schemas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeepResearchSource(BaseModel):
    """A single source cited by the Deep Research Agent."""

    url: str = ""
    title: str = ""
    status: str = ""


class DeepResearchLaunch(BaseModel):
    """Response from research_web — confirms launch of a background task."""

    interaction_id: str
    status: str = "in_progress"
    estimated_minutes: str = "10-20"


class DeepResearchResult(BaseModel):
    """Completed Deep Research report extracted from an Interaction."""

    interaction_id: str
    status: str = "completed"
    topic: str = ""
    report_text: str = ""
    sources: list[DeepResearchSource] = Field(default_factory=list)
    source_count: int = 0
    duration_seconds: int | None = None
    usage: dict = Field(default_factory=dict)


class DeepResearchFollowup(BaseModel):
    """Response from research_web_followup — a follow-up answer."""

    interaction_id: str
    previous_interaction_id: str = ""
    response: str = ""
