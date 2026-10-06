"""Bounded deterministic synthesis over existing attributed evidence records."""

from typing import Annotated, Literal

from pydantic import Field

from .corpus import ID, CorpusModel
from .evidence_export import CorpusSource, FixtureSource, Record, WikiSource

Source = Annotated[CorpusSource | WikiSource | FixtureSource, Field(discriminator="kind")]


class Scope(CorpusModel):
    """Select canonical local evidence or explicitly labeled caller fixtures."""

    source: Source
    instruction: str = Field(min_length=1, max_length=2000)
    max_output_bytes: int = Field(default=65536, ge=1024, le=262144)


class CrossVideo(Scope):
    """Return retrieved quotations instead of unsupported generated assertions."""

    action: Literal["cross_video"]


class Chapters(Scope):
    """Bound heuristic chapter bins by one declared video revision and duration."""

    action: Literal["chapters"]
    video_id: ID
    source_revision: ID
    duration_seconds: float = Field(gt=0, le=14400)
    max_chapters: int = Field(default=10, ge=1, le=20)


class BugReport(Scope):
    """Keep reported source observations separate from caller-inferred causes."""

    action: Literal["bug_report"]
    video_id: ID
    source_revision: ID
    at_seconds: float = Field(ge=0, le=14400)
    lookback_seconds: float = Field(default=30, ge=0, le=120)
    action_observation_ids: list[ID] = Field(default_factory=list, max_length=20)
    inferred_causes: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=10)


Request = Annotated[CrossVideo | Chapters | BugReport, Field(discriminator="action")]


class Statement(CorpusModel):
    """An exact quotation with its complete retrieved video/moment citation."""

    text: str
    evidence: Record
    method: Literal["retrieved_exact_quotation"] = "retrieved_exact_quotation"


class Chapter(CorpusModel):
    """Heuristic boundaries and title retain their actual observation anchors."""

    start_seconds: float
    end_seconds: float
    title: str
    evidence: list[Record]
    method: Literal["equal_duration_bins_source_excerpt_v1"] = "equal_duration_bins_source_excerpt_v1"


class Cause(CorpusModel):
    """Caller-authored inference, never a watched or verified causal conclusion."""

    text: str
    basis: Literal["inferred"] = "inferred"
    method: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"


class BugEvidence(CorpusModel):
    """Channel separation does not upgrade supplied observations into truth."""

    ocr: list[Record] = Field(default_factory=list)
    frames: list[Record] = Field(default_factory=list)
    preceding_speech: list[Record] = Field(default_factory=list)
    actions: list[Record] = Field(default_factory=list)
    inferred_context: list[Record] = Field(default_factory=list)
    inferred_causes: list[Cause] = Field(default_factory=list)
    frame_verification: str = "artifact_references_only_not_opened"


class Response(CorpusModel):
    """Finite source-only results disclose gaps, provenance and zero providers."""

    action: Literal["cross_video", "chapters", "bug_report"]
    status: Literal["complete", "partial", "abstained"]
    instruction: str
    statements: list[Statement] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    bug_report: BugEvidence | None = None
    abstentions: list[dict] = Field(default_factory=list)
    selection: dict
    conflict_policy: str = "retain_all_retrieved_sources_without_arbitration"
    evidence_verification: str = "retrieved_or_caller_records_not_independently_verified"
    provider_calls: Literal[0] = 0
