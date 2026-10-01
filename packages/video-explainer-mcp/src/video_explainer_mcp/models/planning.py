"""Typed editorial plans with explicit source disposition and revision requests."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanModel(BaseModel):
    """Reject unknown fields in the independently owned plan contract."""

    model_config = ConfigDict(extra="forbid", strict=True)


class PlanSource(PlanModel):
    """Include or explicitly reject one original evidence source."""

    source_id: str = Field(min_length=1, max_length=256)
    disposition: Literal["included", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)


class PlanScene(PlanModel):
    """Ordered scene purpose, duration and exact factual claim references."""

    title: str = Field(min_length=1, max_length=256)
    concept: str = Field(min_length=1, max_length=256)
    purpose: str = Field(min_length=1, max_length=2000)
    claim_ids: list[str] = Field(min_length=1, max_length=100)
    duration_seconds: float = Field(gt=0, le=1800)


class VideoPlan(PlanModel):
    """A complete multi-source plan, independent of an external CLI model."""

    title: str = Field(min_length=1, max_length=256)
    audience: str = Field(min_length=1, max_length=2000)
    thesis: str = Field(min_length=1, max_length=2000)
    concept_order: list[str] = Field(min_length=1, max_length=64)
    scenes: list[PlanScene] = Field(min_length=1, max_length=64)
    sources: list[PlanSource] = Field(min_length=1, max_length=128)
    duration_budget_seconds: float = Field(gt=0, le=14400)

    @model_validator(mode="after")
    def ordered_and_bounded(self):
        """Require explicit order, unique sources and a finite scene budget."""
        if len(self.concept_order) != len(set(self.concept_order)):
            raise ValueError("Concept order contains duplicates")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Source dispositions contain duplicates")
        indices = []
        for scene in self.scenes:
            if scene.concept not in self.concept_order:
                raise ValueError("Scene concept is absent from concept order")
            if len(scene.claim_ids) != len(set(scene.claim_ids)):
                raise ValueError("Scene claim references contain duplicates")
            indices.append(self.concept_order.index(scene.concept))
        if indices != sorted(indices) or set(indices) != set(range(len(self.concept_order))):
            raise ValueError("Scenes must cover every concept in the declared order")
        if sum(scene.duration_seconds for scene in self.scenes) > self.duration_budget_seconds:
            raise ValueError("Scene duration exceeds the plan budget")
        return self


class PlanRequest(PlanModel):
    """Noninteractive plan creation, inspection, replacement and approval."""

    action: Literal["create", "show", "revise", "approve"]
    expected_revision: int = Field(default=0, ge=0)
    plan: VideoPlan | None = None

    @model_validator(mode="after")
    def action_payload(self):
        """Require full replacement content only for create and revise."""
        if (self.action in {"create", "revise"}) != (self.plan is not None):
            raise ValueError("Create/revise require a plan; show/approve do not accept one")
        if self.action == "create" and self.expected_revision != 0:
            raise ValueError("Create requires expected_revision=0")
        return self
