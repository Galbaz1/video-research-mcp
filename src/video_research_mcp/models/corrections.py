"""Reported corrections and fixed-rule replay, separate from accepted truth."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .collections import Scope
from .corpus import ID, CorpusModel, Digest, Observation


class EvidencePointer(CorpusModel):
    """Exact retained canonical observation identity; no inferred source merge."""

    video_id: ID
    observation_id: ID
    source_revision: ID
    media_digest: Digest


class Outcome(CorpusModel):
    """Caller-supplied outcome, including unsuccessful provider attempts."""

    status: Literal["answer", "abstained", "provider_error", "error"]
    basis: Literal["model_generated", "caller_reported"]
    source_revisions: dict[ID, ID] = Field(min_length=1, max_length=32)
    answer: str | None = Field(default=None, min_length=1, max_length=8000)
    error: str | None = Field(default=None, min_length=1, max_length=2000)
    evidence_refs: list[EvidencePointer] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def coherent(self):
        """Preserve distinct answer/error states and pinned evidence revisions."""
        if (self.status == "answer") != (self.answer is not None):
            raise ValueError("Only answer outcomes require answer text")
        if self.status in {"provider_error", "error"} and self.error is None:
            raise ValueError("Error outcomes require the reported error")
        identities = [tuple(ref.model_dump().values()) for ref in self.evidence_refs]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate evidence reference")
        if any(self.source_revisions.get(ref.video_id) != ref.source_revision for ref in self.evidence_refs):
            raise ValueError("Evidence revision differs from the supplied source revision")
        return self


class Reporter(CorpusModel):
    """Reported correction authority; caller labels do not authenticate a principal."""

    actor: ID
    authority: Literal["user_reported", "reviewer_reported", "model_reported"]


class Lesson(CorpusModel):
    """Immutable question/outcome, reported correction and declared regression rule."""

    case_id: ID
    question: str = Field(min_length=1, max_length=2000)
    original: Outcome
    corrected_answer: str = Field(min_length=1, max_length=8000)
    correction_note: str = Field(min_length=1, max_length=2000)
    corrected_evidence_refs: list[EvidencePointer] = Field(min_length=1, max_length=16)
    reporter: Reporter
    reported_at: AwareDatetime
    evaluator: Literal["exact_answer_and_corrected_refs_v1"] = "exact_answer_and_corrected_refs_v1"

    @model_validator(mode="after")
    def unique_refs(self):
        """Keep corrected evidence identities unambiguous."""
        refs = [tuple(ref.model_dump().values()) for ref in self.corrected_evidence_refs]
        if len(set(refs)) != len(refs):
            raise ValueError("Duplicate corrected evidence reference")
        return self


class ResolvedEvidence(CorpusModel):
    """Exact observation snapshot retained even after later corpus removal."""

    reference: EvidencePointer
    observation: Observation
    source_id: str = Field(min_length=1, max_length=257)


class CacheReceipt(CorpusModel):
    """Immutable intent or observed existing result-cache invalidation; never verified truth."""

    state: Literal["absent", "pending", "complete", "partial", "failed", "not_checked"] = "absent"
    invalidated_entries: int = Field(default=0, ge=0)
    scope: Literal["persisted_semantic_answer_cache"] = "persisted_semantic_answer_cache"
    grounding_cache: Literal["per_request_artifact_status_only"] = "per_request_artifact_status_only"


class CaseRecord(CorpusModel):
    """Immutable lesson with exact original and corrected provenance snapshots."""

    lesson: Lesson
    recorded_at: AwareDatetime
    original_evidence: list[ResolvedEvidence]
    corrected_evidence: list[ResolvedEvidence]
    cache_invalidation: CacheReceipt = Field(default_factory=CacheReceipt)
    verified: Literal[False] = False
    authority_authenticated: Literal[False] = False


class ReplayRecord(CorpusModel):
    """One immutable attempt; passing the specified rule is not factual verification."""

    case_id: ID
    replay_id: ID
    ordinal: int = Field(ge=1)
    change_revision: ID
    evaluated_at: AwareDatetime
    outcome: Outcome
    lesson_sha256: Digest
    status: Literal["pass", "fail", "error", "provider_error", "abstained"]
    reason: str
    evidence: list[ResolvedEvidence] = Field(default_factory=list)
    evaluator_error: str | None = None
    verified: Literal[False] = False
    interpretation: Literal["specified_rule_only_not_factual_verification"] = "specified_rule_only_not_factual_verification"


class Context(Scope):
    """Explicit collection context and finite response size."""

    collection: ID
    output_bytes: int = Field(default=65536, ge=1024, le=1024**2)


class Record(Context):
    """Record a reported correction without rewriting an existing case."""

    action: Literal["record"]
    expected_revision: int = Field(ge=0)
    lesson: Lesson


class Replay(Context):
    """Evaluate a caller-supplied post-change outcome; never invoke a provider."""

    action: Literal["replay"]
    expected_revision: int = Field(ge=0)
    case_id: ID
    replay_id: ID
    change_revision: ID
    outcome: Outcome


class Read(Context):
    """List lessons or export one case and a finite history page."""

    action: Literal["list", "export"]
    case_id: ID | None = None
    offset: int = Field(default=0, ge=0, le=1000)
    limit: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def selection(self):
        """Require the explicit case for export and collection scope for list."""
        if (self.action == "export") != (self.case_id is not None):
            raise ValueError("Only export requires case_id")
        return self


Request = Annotated[Record | Replay | Read, Field(discriminator="action")]


class Response(CorpusModel):
    """Durable local receipts with all admitted replay outcomes in the denominator."""

    status: Literal["recorded", "replayed", "unchanged", "listed", "exported"]
    workspace: ID
    collection: ID
    index_revision: int
    cases: list[CaseRecord] = Field(default_factory=list)
    replays: list[ReplayRecord] = Field(default_factory=list)
    next_offset: int | None = None
    denominator: dict[str, int]
    cache_invalidation: CacheReceipt = Field(default_factory=lambda: CacheReceipt(state="not_checked"))
    context_invalidated_entries: int = Field(default=0, ge=0)
    cache_sources: list[Digest] = Field(default_factory=list, max_length=32)
    cache_errors: list[str] = Field(default_factory=list, max_length=32)
    evidence_basis: Literal["retained_provenance_not_artifact_availability_or_truth"] = "retained_provenance_not_artifact_availability_or_truth"
    provider_calls: Literal[0] = 0
