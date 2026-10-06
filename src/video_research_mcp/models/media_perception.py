"""Bounded joint audio/visual requests and untrusted window-relative evidence."""

from typing import Annotated, Literal
import json

from pydantic import Field, model_validator

from .image_edit import Digest, Number, StrictModel
from .vision import VisionLimits
from ..errors import ToolError


class AVPerceptionLimits(VisionLimits):
    """Reserve every count/generation transmission under one operation deadline."""

    max_calls: Annotated[int, Field(strict=True, ge=1, le=24)] = 8
    max_windows: Annotated[int, Field(strict=True, ge=1, le=4)] = 4
    max_frames: Annotated[int, Field(strict=True, ge=1, le=128)] = 128
    max_payload_bytes: Annotated[int, Field(strict=True, ge=1, le=8 * 1024 * 1024)] = 8 * 1024 * 1024
    max_transmitted_bytes: Annotated[int, Field(strict=True, ge=1, le=64 * 1024 * 1024)] = 32 * 1024 * 1024
    timeout_seconds: Annotated[Number, Field(gt=0, le=120)] = 120


class AVPerceptionRequest(StrictModel):
    """One exact local source; the default prepares a plan without submission."""

    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest
    instruction: Annotated[str, Field(min_length=1, max_length=8192)]
    media_type: Literal["auto", "audio", "video"] = "auto"
    start_seconds: Annotated[Number, Field(ge=0)] = 0
    end_seconds: Annotated[Number | None, Field(gt=0)] = None
    window_seconds: Annotated[Number, Field(ge=1, le=30)] = 30
    fps: Annotated[Number, Field(ge=0.1, le=30)] = 1
    max_pixels: Annotated[int, Field(strict=True, ge=1, le=1_000_000)] = 250000
    max_frames_per_window: Annotated[int, Field(strict=True, ge=1, le=48)] = 32
    thinking_level: Literal["low", "medium", "high"] = "medium"
    dry_run: Annotated[bool, Field(strict=True)] = True
    authorize_submission: Annotated[bool, Field(strict=True)] = False
    limits: AVPerceptionLimits = AVPerceptionLimits()

    @model_validator(mode="after")
    def ordered_selection(self):
        """Reject empty ranges before any local work or external transmission."""
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("Perception end must exceed start")
        return self


class AVEvidence(StrictModel):
    """A model claim with an explicit modality and supporting local frame indices."""

    modality: Literal["spoken", "visible"]
    start_seconds: Annotated[Number, Field(ge=0)]
    end_seconds: Annotated[Number, Field(ge=0)]
    description: Annotated[str, Field(min_length=1, max_length=2048)]
    frame_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, le=47)]], Field(max_length=48)] = []

    @model_validator(mode="after")
    def evidence_kind(self):
        """Keep transcript claims separate from support by submitted image points."""
        if self.end_seconds < self.start_seconds:
            raise ValueError("Model evidence interval is reversed")
        if self.modality == "spoken" and self.frame_indices:
            raise ValueError("Spoken evidence cannot cite visual frame indices")
        if self.modality == "visible" and not self.frame_indices:
            raise ValueError("Visible evidence requires a submitted frame index")
        if any(type(i) is not int or i < 0 for i in self.frame_indices) or len(set(self.frame_indices)) != len(self.frame_indices):
            raise ValueError("Frame indices must be unique nonnegative integers")
        return self


class AVWindowAnswer(StrictModel):
    """Window-relative model output; source clocks and correctness come from elsewhere."""

    summary: Annotated[str, Field(max_length=8192)]
    events: Annotated[list[AVEvidence], Field(max_length=128)]
    abstentions: Annotated[list[Annotated[str, Field(max_length=2048)]], Field(max_length=64)] = []

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        """Reject excessive or nonfinite provider JSON before timeline admission."""
        if len(json.dumps(value, allow_nan=False).encode()) > 128 * 1024:
            raise ValueError("Perception model JSON exceeds128KiB")
        return value


class AVSourceEvidence(AVEvidence):
    """Window-local support indices with model times mapped to the original source."""

    window_index: Annotated[int, Field(strict=True, ge=0, le=3)]
    evidence_status: Literal["model_inference"] = "model_inference"
    coordinate_basis: Literal["absolute_source_seconds"] = "absolute_source_seconds"


class AVPerceptionResponse(StrictModel):
    """Exact transmitted lineage and a separately labeled inferred timeline."""

    status: Literal["planned", "complete"]
    operation: Literal["media_perceive"] = "media_perceive"
    source: dict
    backend: dict
    request_sha256: Digest
    windows: list[dict]
    timeline: list[AVSourceEvidence]
    summaries: list[str]
    abstentions: list[dict]
    execution: dict
    provenance: dict


class AVPerceptionFailure(ToolError):
    """Retain completed windows and unsuccessful attempt accounting without raw diagnostics."""

    source: dict | None
    windows: list[dict]
    timeline: list[AVSourceEvidence]
    summaries: list[str]
    abstentions: list[dict]
    execution: dict
    request_sha256: Digest | None
