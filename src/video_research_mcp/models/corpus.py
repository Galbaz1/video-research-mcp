"""Bounded supplied observations and context-only corpus requests."""

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:@-]+$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Vector = Annotated[list[Annotated[float, Field(ge=-1e6, le=1e6)]], Field(min_length=1, max_length=1024)]


class CorpusModel(BaseModel):
    """Reject unknown fields and nonfinite numeric input at the boundary."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EvidenceRef(CorpusModel):
    """Caller-supplied artifact identity; bytes are not authenticated by the index."""

    artifact_id: ID
    kind: Literal["frame", "transcript", "description"]
    path: str = Field(min_length=1, max_length=2048)
    sha256: Digest


class Observation(CorpusModel):
    """One exact source interval and its supplied evidence references."""

    video_id: ID
    observation_id: ID
    source_revision: ID
    media_digest: Digest
    kind: Literal["speech", "OCR", "description"]
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=8000)
    entities: list[ID] = Field(default_factory=list, max_length=32)
    artifact_refs: list[EvidenceRef] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def ordered_span(self):
        """Require an ordered finite interval, preserving exact supplied endpoints."""
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds precedes start_seconds")
        return self


class VectorPatch(CorpusModel):
    """A vector bound to one exact observation, revision, digest and model."""

    observation_id: ID
    source_revision: ID
    media_digest: Digest
    model: ID
    values: Vector

    @model_validator(mode="after")
    def nonzero(self):
        """Reject a vector that cannot define a finite cosine direction."""
        if not any(self.values) or not all(math.isfinite(v) for v in self.values):
            raise ValueError("vector must be finite and nonzero")
        return self


class GraphRoute(CorpusModel):
    """Explicit separately operated context route; both keyword sets avoid extraction."""

    endpoint: str = Field(min_length=1, max_length=256)
    mode: Literal["local", "global", "hybrid", "mix"] = "mix"
    hl_keywords: list[ID] = Field(min_length=1, max_length=16)
    ll_keywords: list[ID] = Field(min_length=1, max_length=16)


class CorpusRequest(CorpusModel):
    """Common filesystem and collection scope for every index operation."""

    index_path: str = Field(min_length=1, max_length=2048)
    collection: ID


class IndexRequest(CorpusRequest):
    """Atomically index supplied observations with an optimistic collection revision."""

    action: Literal["index"]
    expected_revision: int = Field(ge=0)
    observations: list[Observation] = Field(min_length=1, max_length=100)
    vectors: list[VectorPatch] = Field(default_factory=list, max_length=100)


class RepairRequest(CorpusRequest):
    """Replace supplied vectors without inspecting, downloading or processing media."""

    action: Literal["repair"]
    expected_revision: int = Field(ge=1)
    vectors: list[VectorPatch] = Field(min_length=1, max_length=100)


class QueryRequest(CorpusRequest):
    """Require explicit current video revisions; return evidence context only."""

    action: Literal["query"]
    query: str = Field(min_length=1, max_length=2000)
    source_revisions: dict[ID, ID] = Field(min_length=1, max_length=100)
    mode: Literal["fts", "dense", "hybrid"] = "hybrid"
    query_vector: Vector | None = None
    vector_model: ID | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    token_budget: int = Field(default=2048, ge=32, le=32768)
    graph: GraphRoute | None = None

    @model_validator(mode="after")
    def vector_identity(self):
        """A supplied query vector requires its model identity and a nonzero direction."""
        if (self.query_vector is None) != (self.vector_model is None):
            raise ValueError("query_vector and vector_model must be supplied together")
        if self.query_vector is not None and not any(self.query_vector):
            raise ValueError("query vector must be nonzero")
        return self


Request = Annotated[IndexRequest | RepairRequest | QueryRequest, Field(discriminator="action")]


class CorpusResponse(CorpusModel):
    """Inspectable source results; there is deliberately no generated-answer field."""

    status: Literal["indexed", "repaired", "found", "no_evidence"]
    collection: ID
    index_revision: int
    context: dict = Field(default_factory=dict)
    retrieval: dict = Field(default_factory=dict)
    total_token_budget: int = 0
    estimated_tokens: int = 0
    token_estimator: str = "utf8_bytes_div4_ceil_v1"
    evidence_verification: str = "supplied_artifact_identities_not_independently_verified"
