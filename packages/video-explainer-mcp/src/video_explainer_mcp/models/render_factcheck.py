"""Render fact-check request and result wire models.

Verified support (deterministic exact-quote and literal-token checks) and asserted
judgments (fixture, author or model verdicts) are separate fields and never merge.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evidence import Digest, EvidenceReference, Identifier

Status = Literal["pass", "fail", "UNKNOWN"]
Channel = Literal["caption", "overlay_text", "voiceover_asr", "frame_ocr"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimJudgment(_Strict):
    """Caller-recorded verdict; it is reported, not certified, by this check."""

    claim_id: Identifier
    verdict: Literal["supported", "false", "unsupported"]
    method: Literal["fixture_literal", "author_review", "model_judgment"]
    judge: Annotated[str, Field(min_length=1, max_length=128)]
    correction_refs: list[EvidenceReference] = Field(default_factory=list, max_length=16)


class RenderedObservation(_Strict):
    """Text actually recovered from a rendered output channel by a named method."""

    id: Identifier
    channel: Channel
    text: Annotated[str, Field(min_length=1, max_length=4096)]
    method: Annotated[str, Field(min_length=1, max_length=128, description="e.g. caption_track, asr:<engine>, ocr:<engine>")]
    claim_ids: list[Identifier] = Field(default_factory=list, description="Renderer-declared IDs; checked, not trusted")
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def ordered(self):
        """Require both interval endpoints together and in order."""
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("Observation interval requires both endpoints")
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("Observation interval end must follow start")
        return self


class RenderReceipt(_Strict):
    """Renderer completion claim to compare against current output bytes."""

    output_path: Annotated[str, Field(min_length=1, description="Path relative to the project directory")]
    expected_sha256: Digest
    status: Literal["completed", "failed", "cancelled", "unknown"]


class RenderFactcheckRequest(_Strict):
    """Judgments, rendered observations and render receipt to reconcile with the project packet."""

    judgments: list[ClaimJudgment] = Field(default_factory=list, max_length=500)
    observations: list[RenderedObservation] = Field(default_factory=list, max_length=2000)
    render: RenderReceipt | None = None
    sync_tolerance_ms: int = Field(default=500, ge=0, le=10_000)


class SourceReference(BaseModel):
    """Integrity-checked original passage (source_unavailable references carry no quote)."""

    source_id: str
    passage_id: str
    quote: str | None
    source_sha256: str | None
    start_ms: int | None = None
    end_ms: int | None = None


class JudgmentRecord(BaseModel):
    """Asserted verdict with its method; corrections are verified exact quotes only."""

    verdict: str
    method: str
    judge: str
    verified: Literal[False] = False
    corrections: list[SourceReference] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class ClaimCheck(BaseModel):
    """One claim: verified support, asserted judgment and the resulting factual status."""

    claim_id: str
    text: str
    editorial_approved: bool
    verified_support: Literal["exact_source_text", "no_exact_source_text", "source_unavailable", "abstained"]
    support_references: list[SourceReference]
    judgment: JudgmentRecord | None
    factual_status: Literal["supported", "false", "unsupported", "unknown"]
    status_method: str


class ObservationCheck(BaseModel):
    """Independent reconciliation of one rendered observation with packet claims."""

    id: str
    channel: str
    method: str
    matched_claim_ids: list[str]
    declared_claim_ids: list[str]
    declared_matches: bool
    additions: list[str]
    unapproved_claim_ids: list[str]
    false_claim_ids: list[str]
    reconciled: bool
    comparison: Literal["normalized_literal_tokens"] = "normalized_literal_tokens"


class Dimension(BaseModel):
    """One separately reported quality dimension."""

    status: Status
    basis: str
    reasons: list[str] = Field(default_factory=list)
    details: list[dict] = Field(default_factory=list)


class QualityReport(BaseModel):
    """Factual support, clarity, legibility, sync and completion never collapse into one score."""

    factual_support: Dimension
    narration_clarity: Dimension
    legibility: Dimension
    synchronization: Dimension
    render_completion: Dimension


class RenderFactcheckResult(BaseModel):
    """Structured render fact-check; deterministic literal evidence, not general factual truth."""

    project_id: str
    packet_sha256: str
    evidence_scope: Literal["deterministic_literal_fixture_evidence"] = "deterministic_literal_fixture_evidence"
    source_errors: list[str]
    lineage_errors: list[str]
    claims: list[ClaimCheck]
    observations: list[ObservationCheck]
    unobserved_approved_claim_ids: list[str]
    quality: QualityReport
    factual_pass: bool
    semantic_support: Literal["not_verified"] = "not_verified"
