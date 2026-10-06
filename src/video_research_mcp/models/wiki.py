"""Explicit canonical identities and bounded, attributed wiki page operations."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .corpus import ID, CorpusModel, Digest, EvidenceRef

PageKind = Literal["concept", "topic", "entity", "video"]


class Scope(CorpusModel):
    """One existing canonical corpus SQLite database, never a separate wiki store."""

    index_path: str = Field(min_length=1, max_length=2048)


class EvidenceLink(CorpusModel):
    """Caller-selected concept claim bound to an exact existing observation version."""

    evidence_id: ID
    collection: ID
    video_id: ID
    observation_id: ID
    source_revision: ID
    media_digest: Digest
    attribution: str = Field(min_length=1, max_length=256)
    claim: str = Field(min_length=1, max_length=2000)
    stance: Literal["reported", "unknown", "conflicting"]


class LinkedEvidence(EvidenceLink):
    """Immutable provenance snapshot, without duplicating source observation content."""

    source_id: str
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    linked_at: str
    corpus_revision: int = Field(ge=1)
    observation_sha256: Digest
    artifact_refs: list[EvidenceRef] = Field(min_length=1, max_length=16)


class Page(CorpusModel):
    """An immutable human-readable revision with independently attributed contributions."""

    concept_id: ID
    kind: PageKind
    title: str = Field(min_length=1, max_length=256)
    revision: int = Field(ge=1)
    body: str = Field(max_length=20000)
    tags: list[ID] = Field(max_length=20)
    evidence: list[LinkedEvidence] = Field(max_length=100)
    updated_at: str
    retired: bool = False
    text_origin: Literal["caller_text"] = "caller_text"
    claims_are_attributed: Literal[True] = True


class Write(Scope):
    """Create/update one explicit concept identity and append immutable evidence links."""

    action: Literal["write"]
    concept_id: ID
    expected_revision: int = Field(ge=0, le=100)
    kind: PageKind
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=20000)
    tags: list[ID] = Field(default_factory=list, max_length=20)
    evidence: list[EvidenceLink] = Field(min_length=1, max_length=100)


class Read(Scope):
    """Page access/history, typed listing/TOC and literal-term FTS retrieval."""

    action: Literal["get", "history", "list", "toc", "search"]
    concept_id: ID | None = None
    revision: int | None = Field(default=None, ge=1, le=100)
    kind: PageKind | None = None
    tag: ID | None = None
    query: str = Field(default="", max_length=2000)
    offset: int = Field(default=0, ge=0, le=1000)
    limit: int = Field(default=10, ge=1, le=50)
    output_bytes: int = Field(default=65536, ge=1024, le=262144)

    @model_validator(mode="after")
    def required_identity(self):
        """Reject incomplete operations instead of silently broadening their scope."""
        if self.action in ("get", "history") and self.concept_id is None:
            raise ValueError("get/history require concept_id")
        if self.action == "search" and not self.query.strip():
            raise ValueError("search requires query")
        return self


class RemoveSource(Scope):
    """Remove a video's current contributions using caller-pinned affected page revisions."""

    action: Literal["remove_source"]
    video_id: ID
    expected_revisions: dict[ID, Annotated[int, Field(ge=1, le=100)]] = Field(min_length=1, max_length=100)


class Ask(Scope):
    """Retrieve context first; prose is optional and its origin is always disclosed."""

    action: Literal["ask"]
    question: str = Field(min_length=1, max_length=2000)
    concept_ids: list[ID] = Field(default_factory=list, max_length=10)
    mode: Literal["context", "caller", "gemini"] = "context"
    caller_text: str | None = Field(default=None, min_length=1, max_length=8000)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    context_bytes: int = Field(default=32768, ge=1024, le=65536)
    top_k: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def synthesis_mode(self):
        """Require explicit prose inputs; prevent silently ignored authority or text."""
        if (self.mode == "caller") != (self.caller_text is not None):
            raise ValueError("caller mode requires caller_text, exclusively")
        if self.mode != "gemini" and self.model is not None:
            raise ValueError("model is only valid for gemini mode")
        return self


class Prose(CorpusModel):
    """Generated synthesis cites only evidence selected in the disclosed context."""

    text: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[ID] = Field(min_length=1, max_length=100)


Request = Annotated[Write | Read | RemoveSource | Ask, Field(discriminator="action")]


class Response(CorpusModel):
    """Bounded inspectable wiki results; synthesis never upgrades attributed claims."""

    status: Literal["written", "found", "no_evidence", "removed", "answered"]
    pages: list[dict] = Field(default_factory=list)
    next_offset: int | None = None
    context: list[dict] = Field(default_factory=list)
    context_sha256: Digest | None = None
    context_bytes: int = 0
    omitted_pages: int = 0
    retrieval: str = "canonical_wiki_fts_literal_terms_v1"
    synthesis: str | None = None
    synthesis_origin: Literal["none", "caller_text", "model_generated"] = "none"
    model_generated: bool = False
    model: str | None = None
    cited_evidence_ids: list[ID] = Field(default_factory=list)
    provider_calls: int = 0
    modified_pages: int = 0
