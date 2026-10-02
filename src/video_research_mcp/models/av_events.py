"""Task-specific AV occurrences and music sections with server-assigned support identities."""

import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..errors import ToolError
from .image_edit import Digest, Number, StrictModel
from .media_perception import AVPerceptionRequest

Text = Annotated[str, Field(min_length=1, max_length=2048)]
Tags = Annotated[list[Annotated[str, Field(min_length=1, max_length=128)]], Field(max_length=32)]


class CaptionEventsRequest(AVPerceptionRequest):
    """Describe bounded supported occurrences without a caller-selected task route."""

    instruction: Annotated[str, Field(min_length=1, max_length=8192)] = "Describe supported audio and visual occurrences."


class CountEventsRequest(AVPerceptionRequest):
    """Count retained supported occurrence records for one explicit target."""

    instruction: Annotated[str, Field(min_length=1, max_length=8192)] = "Find distinct supported occurrences of the target."
    target: Annotated[str, Field(min_length=1, max_length=1024)]

    @model_validator(mode="after")
    def meaningful_target(self):
        """Reject an empty target without rewriting caller data."""
        if not self.target.strip():
            raise ValueError("Event counting requires a nonempty target")
        return self


class GroundEventsRequest(AVPerceptionRequest):
    """Retain all admitted matches and disclose a bounded score-ranked selection."""

    instruction: Annotated[str, Field(min_length=1, max_length=8192)] = "Locate supported occurrences matching the query."
    query: Text
    top_k: Annotated[int, Field(strict=True, ge=1, le=128)] = 10

    @model_validator(mode="after")
    def meaningful_query(self):
        """Reject an empty query at the typed public boundary."""
        if not self.query.strip():
            raise ValueError("Event grounding requires a nonempty query")
        return self


class AnalyzeMusicRequest(AVPerceptionRequest):
    """Submit audio only, including when the exact source is a video container."""

    instruction: Annotated[str, Field(min_length=1, max_length=8192)] = "Describe audible musical sections and their evidence."
    media_type: Literal["audio"] = "audio"


class Occurrence(StrictModel):
    """Window-relative inference with explicit audio, visual or fused AV basis."""

    start_seconds: Annotated[Number, Field(ge=0)]
    end_seconds: Annotated[Number, Field(ge=0)]
    basis: Literal["audio", "visual", "both"]
    description: Text
    frame_indices: Annotated[list[Annotated[int, Field(strict=True, ge=0, le=47)]], Field(max_length=48)] = []

    @model_validator(mode="after")
    def local_support(self):
        """Require modality-consistent unique frame references and ordered endpoints."""
        if self.end_seconds < self.start_seconds or not self.description.strip():
            raise ValueError("Occurrence interval or description is invalid")
        if len(set(self.frame_indices)) != len(self.frame_indices):
            raise ValueError("Occurrence frame references must be unique")
        if self.basis == "audio" and self.frame_indices:
            raise ValueError("Audio occurrences must not cite visual frames")
        if self.basis in {"visual", "both"} and not self.frame_indices:
            raise ValueError("Visual and fused occurrences require actual frame references")
        return self


class GroundMatch(Occurrence):
    """A model match score is bounded but remains uncalibrated inference."""

    score: Annotated[Number, Field(ge=0, le=1)]


class MusicProperties(StrictModel):
    """Audible labels and musical properties, never renamed physical measurements."""

    instruments: Tags
    moods: Tags
    tags: Tags
    tempo_bpm: Annotated[Number | None, Field(gt=0, le=400)] = None
    key: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    meter: Annotated[str | None, Field(min_length=1, max_length=32)] = None


class MusicSection(Occurrence):
    """A timed audio-only section whose boundaries and musical labels are inferred."""

    basis: Literal["audio"] = "audio"
    frame_indices: Annotated[list[int], Field(max_length=0)] = []
    label: Annotated[str, Field(min_length=1, max_length=256)]
    properties: MusicProperties


class WindowAnswer(StrictModel):
    """Explicit events, valid empty or abstained inference with bounded finite JSON."""

    summary: Annotated[str, Field(max_length=8192)]
    outcome: Literal["events", "empty", "abstained"]
    abstentions: Annotated[list[Text], Field(max_length=64)] = []

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        """Reject excessive and nonfinite JSON without repair or dropping records."""
        if len(json.dumps(value, allow_nan=False).encode()) > 128 * 1024:
            raise ValueError("AV event model JSON exceeds128KiB")
        return value

    def require_population(self, records):
        """Keep valid empty, explicit abstention and retained inference distinct."""
        if self.outcome == "events" and not records:
            raise ValueError("Events outcome requires retained records")
        if self.outcome != "events" and records:
            raise ValueError("Empty or abstained outcomes must not contain records")
        if self.outcome == "empty" and self.abstentions:
            raise ValueError("Empty and abstained outcomes are distinct")
        if self.outcome == "abstained" and not self.abstentions:
            raise ValueError("Abstained outcome requires an explicit reason")
        return self


class CaptionWindowAnswer(WindowAnswer):
    """Caption occurrences use the actual AV support schema."""

    events: Annotated[list[Occurrence], Field(max_length=128)]

    @model_validator(mode="after")
    def population(self):
        """Validate the complete caption population."""
        return self.require_population(self.events)


class CountWindowAnswer(WindowAnswer):
    """The provider emits occurrences and cannot submit an unrelated numeric count."""

    occurrences: Annotated[list[Occurrence], Field(max_length=128)]

    @model_validator(mode="after")
    def population(self):
        """Validate every occurrence without a count override or silent truncation."""
        return self.require_population(self.occurrences)


class GroundWindowAnswer(WindowAnswer):
    """All supplied matches precede server-side ranked top-k selection."""

    matches: Annotated[list[GroundMatch], Field(max_length=128)]

    @model_validator(mode="after")
    def population(self):
        """Validate the complete scored match population."""
        return self.require_population(self.matches)


class MusicWindowAnswer(WindowAnswer):
    """Music has a section/evidence contract rather than a global unvalidated caption."""

    sections: Annotated[list[MusicSection], Field(max_length=128)]

    @model_validator(mode="after")
    def population(self):
        """Validate timed audio-only music sections and explicit abstention."""
        return self.require_population(self.sections)


class SupportedRecord(StrictModel):
    """A server identity and exact submitted support around unverified model inferences."""

    record_id: Annotated[str, Field(pattern=r"^av_[a-f0-9]{64}$")]
    source_sha256: Digest
    window_index: Annotated[int, Field(strict=True, ge=0, le=3)]
    start_seconds: Number
    end_seconds: Number
    local_start_seconds: Number
    local_end_seconds: Number
    basis: Literal["audio", "visual", "both"]
    description: Text
    frame_indices: list[int]
    visual_support: list[dict]
    audio_support: dict | None
    score: Annotated[Number | None, Field(ge=0, le=1)] = None
    music: dict | None = None
    evidence_status: Literal["model_inference"] = "model_inference"
    coordinate_basis: Literal["absolute_source_seconds"] = "absolute_source_seconds"


class AVEventsResponse(StrictModel):
    """Task populations and complete measured coverage with separate semantic claims."""

    operation: Literal["media_caption_events", "media_count_events", "media_ground_events", "media_analyze_music"]
    task: Literal["caption", "count", "ground", "music"]
    status: Literal["planned", "complete"]
    outcome: Literal["planned", "events", "empty", "abstained"]
    source: dict
    backend: dict
    request_sha256: Digest
    windows: list[dict]
    records: list[SupportedRecord]
    matches: list[SupportedRecord]
    grounding_population: dict | None
    count: int | None
    count_so_far: int | None
    target: str | None
    query: str | None
    summaries: list[str]
    abstentions: list[dict]
    execution: dict
    provenance: dict


class AVEventsFailure(ToolError):
    """Keep retained populations and failed/planned windows without an accepted total."""

    operation: str
    task: str
    status: Literal["partial", "failed"]
    outcome: Literal["partial", "error"]
    source: dict | None
    backend: dict
    request_sha256: Digest | None
    windows: list[dict]
    records: list[SupportedRecord]
    matches: list[SupportedRecord]
    grounding_population: dict | None
    count: None = None
    count_so_far: int | None
    target: str | None
    query: str | None
    summaries: list[str]
    abstentions: list[dict]
    execution: dict
    provenance: dict
