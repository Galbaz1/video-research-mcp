"""Finite offline exports over canonical evidence or explicitly authored fixtures."""

from typing import Annotated, Literal

from pydantic import Field, computed_field, model_validator

from .collections import Read as CollectionRead
from .corpus import ID, CorpusModel, Digest, EvidenceRef, QueryRequest
from .wiki import Ask


class Record(CorpusModel):
    """An attributed evidence interval; unknown provenance is never invented."""

    video_id: ID
    source_revision: ID
    media_digest: Digest
    observation_id: ID | None = None
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    kind: str = Field(max_length=64)
    title: str = Field(default="", max_length=256)
    text: str = Field(default="", max_length=20000)
    citation_id: str = Field(min_length=1, max_length=128)
    basis: Literal["observed", "inferred", "unknown"] = "unknown"
    model: str | None = Field(default=None, max_length=128)
    method: str = Field(default="not_recorded", max_length=128)
    origin: Literal["canonical_corpus", "canonical_wiki", "canonical_collections", "caller_fixture"] = "caller_fixture"
    artifact_refs: list[EvidenceRef] = Field(default_factory=list, max_length=16)
    attribution: str | None = Field(default=None, max_length=256)
    claim: str | None = Field(default=None, max_length=2000)
    stance: Literal["reported", "unknown", "conflicting"] | None = None
    page_revision: int | None = Field(default=None, ge=1)
    page_sha256: Digest | None = None
    source_state: str = Field(default="supplied_not_independently_verified", max_length=128)

    @computed_field
    @property
    def source_id(self) -> str:
        """Retain the canonical video/revision identity without adding a second index."""
        return self.video_id + "@" + self.source_revision

    @model_validator(mode="after")
    def interval(self):
        """Keep absent timing explicit and reject incomplete or reversed intervals."""
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("Both interval endpoints must be supplied or absent")
        if self.start_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds precedes start_seconds")
        return self


class LocalQuery(QueryRequest):
    """Use existing local FTS/supplied-vector retrieval with graph contact disabled."""

    graph: None = None


class ContextOnly(Ask):
    """Retrieve canonical wiki context without any synthesis or model invocation."""

    mode: Literal["context"] = "context"
    model: None = None
    caller_text: None = None


class RecallOnly(CollectionRead):
    """Reuse canonical collection recall and its persisted LRU bookkeeping."""

    action: Literal["recall"] = "recall"


class CorpusSource(CorpusModel):
    """Select existing observations through the concrete corpus retrieval route."""

    kind: Literal["corpus"]
    request: LocalQuery


class WikiSource(CorpusModel):
    """Select canonical wiki pages and their digest-bound observation context."""

    kind: Literal["wiki"]
    request: ContextOnly


class CollectionSource(CorpusModel):
    """Select existing assets/observations through bounded canonical recall."""

    kind: Literal["collections"]
    request: RecallOnly


class FixtureSource(CorpusModel):
    """Explicitly supplied fixture records, not canonical retrieval or validation."""

    kind: Literal["fixture"]
    records: list[Record] = Field(min_length=1, max_length=50)


Source = Annotated[CorpusSource | WikiSource | CollectionSource | FixtureSource, Field(discriminator="kind")]


class Request(CorpusModel):
    """Create one exclusive bounded export bundle; never overwrite an existing path."""

    source: Source
    output_directory: str = Field(min_length=1, max_length=2048)
    title: str = Field(default="Offline evidence", min_length=1, max_length=256)
    formats: list[Literal["html", "markdown", "json"]] = Field(default_factory=lambda: ["html", "markdown", "json"], min_length=1, max_length=3)
    missing_frames: Literal["report", "refuse"] = "report"
    max_inline_bytes: int = Field(default=524288, ge=1, le=4194304)
    max_export_bytes: int = Field(default=2097152, ge=1024, le=8388608)

    @model_validator(mode="after")
    def unique_formats(self):
        """Refuse duplicate output names before any filesystem work."""
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("formats must be unique")
        return self


class Response(CorpusModel):
    """Export receipts distinguish byte integrity from semantic evidence truth."""

    status: Literal["exported", "partial", "no_evidence"]
    complete: bool
    output_directory: str
    records: int
    artifacts: list[dict]
    frame_issues: list[dict]
    selection: dict
    provider_calls: Literal[0] = 0
    evidence_verification: str = "inline_frame_bytes_verified_only; semantic_and_caller_claims_unqualified"
