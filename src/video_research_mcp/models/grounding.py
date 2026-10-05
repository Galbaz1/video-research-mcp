"""Caller claims checked against retrieved corpus evidence and bounded frame escalation."""

from typing import Literal

from pydantic import Field, model_validator

from .corpus import ID, CorpusModel, Digest, QueryRequest

MAX_VERIFY_BYTES = 256 * 1024 * 1024


class GroundingCitation(CorpusModel):
    """One caller-proposed citation into a retrieved observation interval."""

    observation_id: ID
    source_revision: ID
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    quote: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered_span(self):
        """Require an ordered cited interval."""
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds precedes start_seconds")
        return self


class GroundingClaim(CorpusModel):
    """A caller-asserted statement; the tool never authors or rewrites its text."""

    claim_id: ID
    text: str = Field(min_length=1, max_length=2000)
    citations: list[GroundingCitation] = Field(default_factory=list, max_length=8)


class EscalationBudget(CorpusModel):
    """Finite attempt, byte and wall-time limits for additional frame observations."""

    max_attempts: int = Field(default=3, ge=1, le=8)
    max_bytes: int = Field(default=4 * 1024 * 1024, ge=65536, le=8 * 1024 * 1024)
    deadline_seconds: float = Field(default=30, gt=0, le=120)


class EscalationRequest(CorpusModel):
    """Exact local source revision and display-coordinate crop for nearby decoded frames."""

    file_path: str = Field(min_length=1, max_length=4096)
    expected_source_sha256: Digest
    crop_box: tuple[int, int, int, int] | None = None
    max_pixels: int = Field(default=250_000, ge=1, le=1_000_000)
    budget: EscalationBudget = Field(default_factory=EscalationBudget)


class GroundingRequest(CorpusModel):
    """Retrieve first, then validate caller claims; optional bounded visual escalation."""

    retrieval: QueryRequest
    claims: list[GroundingClaim] = Field(default_factory=list, max_length=16)
    repair_citations: bool = True
    verify_byte_budget: int = Field(default=32 * 1024 * 1024, ge=1, le=MAX_VERIFY_BYTES)
    escalation: EscalationRequest | None = None

    @model_validator(mode="after")
    def unique_claims(self):
        """Keep claim identities unique so traces join unambiguously."""
        ids = [claim.claim_id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("claim_id values must be unique")
        return self


class EscalationAttempt(CorpusModel):
    """One decoded frame attempt with requested and PTS-derived actual times kept apart."""

    attempt: int
    claim_id: ID
    observation_id: ID
    status: Literal["observed", "failed", "discarded_byte_budget"]
    requested_seconds: float
    actual_seconds: float | None = None
    original_pts: int | None = None
    time_base: str | None = None
    within_cited_span: bool | None = None
    crop_box: list[int] | None = None
    source: dict | None = None
    artifact: dict | None = None
    error: dict | None = None
    cleanup_error: dict | None = None
    interpretation: Literal["not_performed"] = "not_performed"


class EscalationReport(CorpusModel):
    """Every attempt and the limit that stopped further observations."""

    status: Literal["not_requested", "not_needed", "refused", "complete", "stopped"]
    stop_reason: str | None = None
    attempts: list[EscalationAttempt] = Field(default_factory=list)
    refusals: list[dict] = Field(default_factory=list)
    bytes_used: int = 0
    limits: dict = Field(default_factory=dict)


class ClaimResult(CorpusModel):
    """Claim support from verbatim retrieved text, citation availability, or none."""

    claim_id: ID
    text: str
    claim_basis: Literal["caller_asserted"] = "caller_asserted"
    support: Literal["verbatim_quote", "citation_available_semantics_unverified", "unsupported"]
    citations: list[dict] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)


class GroundingResult(CorpusModel):
    """Grounding outcome; deliberately no generated answer text."""

    status: Literal["grounded", "partially_grounded", "abstained", "evidence_only"]
    query: str
    retrieval_status: Literal["found", "no_evidence"]
    collection: ID
    index_revision: int
    claims: list[ClaimResult] = Field(default_factory=list)
    missing_evidence: list[dict] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list)
    escalation: EscalationReport
    synthesis: dict = Field(default_factory=lambda: {
        "status": "unsupported", "reason": "no_authorized_synthesis_route_configured"})
    limits: dict = Field(default_factory=dict)
    citation_availability: str = "current_artifact_bytes_verified_not_factual_truth"
