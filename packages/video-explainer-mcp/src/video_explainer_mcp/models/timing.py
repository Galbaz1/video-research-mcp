"""Bounded sample-clock timing inspection and explicit repair requests."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimingRequest(BaseModel):
    """Inspect current source bindings or repair with the last observed timing revision."""

    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["inspect", "repair"]
    expected_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def repair_revision(self):
        """Require a concrete revision for every write."""
        if (self.action == "repair") != (self.expected_revision is not None):
            raise ValueError("Only repair requires expected_revision (0 before first repair)")
        return self


class TimingManifest(BaseModel):
    """Retain source identity, sample timestamps and the quantized production clock."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    revision: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    plan_sha256: str
    source_commitment_sha256: str
    script_sha256: str
    narration_sha256: str
    audio: dict
    sample_rate: int = Field(ge=1, le=192000)
    total_samples: int = Field(ge=1)
    video_frames: int = Field(ge=1, le=54000)
    duration_tolerance_seconds: Literal[0.03333333333333333] = 1 / 30
    timestamp_method: str
    scenes: list[dict] = Field(min_length=1, max_length=64)
    storyboard: dict
    render_verification: Literal["UNRUN"] = "UNRUN"


class TimingResult(BaseModel):
    """Separate stale/missing timing from a published current storyboard."""

    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str
    status: Literal["current", "stale", "missing_alignment", "missing_scene_timing", "repaired"]
    revision: int = Field(ge=0)
    current: bool
    affected_scenes: list[str]
    reused_scenes: list[str] = Field(default_factory=list)
    shifted_scenes: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    manifest: TimingManifest | None = None
