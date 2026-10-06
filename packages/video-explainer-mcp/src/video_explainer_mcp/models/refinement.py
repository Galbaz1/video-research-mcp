"""Revision-bound feedback and refinement request models.

Caller and model visual judgments are recorded as asserted findings; nothing here claims
that the tool watched a render or that a generative refinement succeeded.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import Digest

VISUAL_CATEGORIES = {"legibility", "composition", "incorrect_visual"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrameRef(_Strict):
    """Exact rendered output bytes and the frame time the finding refers to."""

    render_path: Annotated[str, Field(min_length=1, description="Rendered output path relative to the project")]
    render_sha256: Digest
    time_ms: int = Field(ge=0)
    frame_index: int | None = Field(default=None, ge=0)


class Finding(_Strict):
    """One asserted observation; `observed_by` names who looked, never this tool."""

    category: Literal["legibility", "composition", "incorrect_visual", "script", "narration", "timing", "other"]
    note: Annotated[str, Field(min_length=1, max_length=2000)]
    observed_by: Literal["caller", "model", "fixture"]


class ScenePatch(_Strict):
    """Local typed edit of one plan scene field, guarded by its expected current value."""

    field: Literal["title", "purpose", "duration_seconds"]
    expected: str | float
    value: str | float


class FeedbackRequest(_Strict):
    """Capabilities probe or one add/show/apply/retry feedback lifecycle step."""

    action: Literal["capabilities", "add", "show", "apply", "retry"]
    expected_revision: int = Field(default=0, ge=0, description="Current plan revision for add/retry")
    feedback_id: str | None = Field(default=None, max_length=32)
    kind: Literal["script", "visual"] | None = None
    text: str | None = Field(default=None, max_length=4000)
    scene_index: int | None = Field(default=None, ge=0, le=63)
    findings: list[Finding] = Field(default_factory=list, max_length=32)
    frame: FrameRef | None = None
    patch: ScenePatch | None = None
    processor: Literal["local_patch", "cli_phase"] = "local_patch"
    phase: str | None = Field(default=None, max_length=64, description="CLI refine phase; must be in the probe result")
    max_rounds: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def action_payload(self):
        """Require the fields each lifecycle step consumes."""
        if self.action == "add":
            if self.kind is None or not self.text or self.scene_index is None:
                raise ValueError("add requires kind, text and scene_index")
            if self.kind == "visual" and (self.frame is None or not any(f.category in VISUAL_CATEGORIES for f in self.findings)):
                raise ValueError("visual feedback requires an exact frame and a legibility/composition/incorrect_visual finding")
            if self.processor == "local_patch" and self.patch is None:
                raise ValueError("local_patch feedback requires a typed scene patch")
            if self.processor == "cli_phase" and not self.phase:
                raise ValueError("cli_phase feedback requires a phase")
        if self.action in {"apply", "retry"} and not self.feedback_id:
            raise ValueError("apply/retry require feedback_id")
        return self


class FeedbackResult(BaseModel):
    """Structured lifecycle result; extra keys carry the durable record or probe."""

    model_config = ConfigDict(extra="allow")

    project_id: str
    action: str
    plan_revision: int | None = None
    feedback: dict | None = None
    feedback_items: list[dict] | None = None
    capabilities: dict | None = None
    watched_by_tool: Literal[False] = False
    generative_success_claimed: Literal[False] = False
