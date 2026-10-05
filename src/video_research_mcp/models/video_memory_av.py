"""Strict AV-memory requests, stored evidence records and identity/fact history.

Adapted from QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f
``src/capabilities/omni-memory`` (``omni_core.StoreBase`` containers and the
``qwen_mm_plugins_omni_memory/tools`` arguments), Apache-2.0. Changed: containers are
typed immutable snapshots with canonical record IDs, exact source spans, retained
artifact origins and an explicit observed/asserted/inferred basis; every request is
bound to a source digest and no request asks for a model answer.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, StrictBool, model_validator

from .image_edit import Digest, Number, StrictModel

WINDOW_SECONDS = 30.0
Kind = Literal["utterance", "visual", "acoustic", "audiovisual", "environment"]
Basis = Literal["observed", "asserted", "inferred"]
Confidence = Literal["high", "medium", "low"]
PersonId = Annotated[str, Field(pattern=r"^P\d{3}$")]
RecordId = Annotated[str, Field(pattern=r"^[a-z]+:[0-9a-f]{12}:\d{4}:\d{3}$")]
EvidenceId = Annotated[str, Field(min_length=1, max_length=96)]
Name = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^\S(?:.*\S)?$")]
Subject = Annotated[str, Field(pattern=r"^(?:P\d{3}|(?:event|topic|place|object):[A-Za-z0-9_.-]{1,64})$")]
Predicate = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
Value = Annotated[str, Field(min_length=1, max_length=2048)]
Query = Annotated[str, Field(min_length=1, max_length=1024)]
LocalPath = Annotated[str, Field(min_length=1, max_length=4096)]
Seconds = Annotated[Number, Field(ge=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
Revision = Annotated[int, Field(strict=True, ge=1)]
ModelId = Annotated[str, Field(pattern=r"^[A-Za-z0-9._/-]{1,128}$")]
Vector = Annotated[str, Field(pattern=r"^f64:[A-Za-z0-9+/]+={0,2}$", max_length=65536)]
Thinking = Literal["low", "medium", "high"]


class Origin(StrictModel):
    """The retained artifact and item that produced one record."""

    operation: Annotated[str, Field(min_length=1, max_length=64)]
    artifact_sha256: Digest
    item: Annotated[str, Field(min_length=1, max_length=128)]


class MemoryRecord(StrictModel):
    """One episodic record; its own source span is never clipped to its window."""

    record_id: RecordId
    kind: Kind
    window: Count
    start_seconds: Seconds
    end_seconds: Seconds
    basis: Basis
    text: Annotated[str, Field(min_length=1, max_length=8192)]
    person_id: PersonId | None = None
    origin: Origin


class Person(StrictModel):
    """A stable anonymous person; a name exists only through identity revisions."""

    person_id: PersonId
    source_label: Annotated[str, Field(min_length=1, max_length=128)]
    label_basis: Basis
    binding: Literal["transcript_speaker_label"] = "transcript_speaker_label"
    name: Name | None = None
    identity_status: Literal["unknown", "evidence_aligned", "user_asserted"] = "unknown"


class IdentityRevision(StrictModel):
    """One append-only name mapping change with its evidence and store revision."""

    revision_id: Annotated[str, Field(pattern=r"^P\d{3}@r\d+$")]
    person_id: PersonId
    name: Name | None
    previous_name: Name | None
    basis: Literal["evidence_aligned", "user_asserted"]
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1, max_length=32)]
    store_revision: Revision
    note: Annotated[str, Field(max_length=2048)] | None = None


class Suggestion(StrictModel):
    """A nonbinding name candidate that never changes a person's identity."""

    suggestion_id: Annotated[str, Field(pattern=r"^S:[0-9a-f]{12}$")]
    person_id: PersonId
    name: Name
    method: Literal["self_intro", "addressed", "model_inference"]
    evidence_ids: Annotated[list[RecordId], Field(min_length=1, max_length=32)]
    binding: Literal[False] = False


class Fact(StrictModel):
    """A keyed semantic triple citing stored records; losers stay superseded."""

    fact_id: Annotated[str, Field(pattern=r"^F:[0-9a-f]{12}$")]
    subject_id: Subject
    key: Predicate
    value: Value
    confidence: Confidence
    basis: Literal["asserted", "inferred"]
    evidence_ids: Annotated[list[RecordId], Field(min_length=1, max_length=64)]
    status: Literal["active", "superseded"] = "active"
    superseded_by: Annotated[str, Field(pattern=r"^F:[0-9a-f]{12}$")] | None = None
    created_revision: Revision
    updated_revision: Revision
    model: ModelId | None = None


class EmbeddingIndex(StrictModel):
    """Lossless vectors with the endpoint and model that actually produced them."""

    endpoint: Literal["google-genai:aio.models.embed_content"]
    model: ModelId
    dimension: Annotated[int, Field(strict=True, ge=1, le=4096)]
    vectors: dict[str, Vector]


class SourceInfo(StrictModel):
    """Exact source bytes and the presentation clock every artifact agreed on."""

    sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=1)]
    path: LocalPath
    duration_seconds: Annotated[Number, Field(gt=0)]


class ArtifactReceipt(StrictModel):
    """An admitted input or route response retained by content address."""

    kind: Literal["transcript", "av_events"]
    role: Literal["utterances", "occurrences", "environment"]
    operation: Annotated[str, Field(min_length=1, max_length=64)]
    sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=1)]
    retained: Annotated[str, Field(pattern=r"^artifacts/[a-f0-9]{64}\.json$")]
    origin: Literal["supplied", "route"]


class MemoryState(StrictModel):
    """One immutable revision of a complete source memory."""

    schema_version: Literal[1] = 1
    memory_id: Annotated[str, Field(pattern=r"^avm:[a-f0-9]{64}$")]
    revision: Revision
    source: SourceInfo
    windows: Count
    artifacts: list[ArtifactReceipt]
    records: list[MemoryRecord]
    persons: list[Person]
    identity_revisions: list[IdentityRevision] = []
    suggestions: list[Suggestion] = []
    facts: list[Fact] = []
    embeddings: EmbeddingIndex | None = None
    history: list[dict] = []


class ArtifactRef(StrictModel):
    """A caller-retained tool result bound by exact bytes."""

    kind: Literal["transcript", "av_events"]
    path: LocalPath
    sha256: Digest
    role: Literal["occurrences", "environment"] = "occurrences"


class AVRoute(StrictModel):
    """Optional per-window media_caption_events calls; planning is the default."""

    roles: Annotated[list[Literal["occurrences", "environment"]], Field(min_length=1, max_length=2)] = ["occurrences"]
    authorize_submission: StrictBool = False
    max_calls: Annotated[int, Field(strict=True, ge=1, le=64)] = 8
    thinking_level: Thinking = "low"

    @model_validator(mode="after")
    def unique_roles(self):
        """Reject duplicate route roles that would double provider calls."""
        if len(set(self.roles)) != len(self.roles):
            raise ValueError("AV route roles must be unique")
        return self


class EmbeddingOptions(StrictModel):
    """Explicit text-embedding endpoint use; without authorization calls are only planned."""

    model: ModelId
    output_dimensionality: Annotated[int, Field(strict=True, ge=1, le=4096)] | None = None
    authorize_provider_calls: StrictBool = False
    max_calls: Annotated[int, Field(strict=True, ge=1, le=64)] = 4


class InduceOptions(StrictModel):
    """Optional fact/name-suggestion induction through GeminiClient.generate_structured."""

    authorize_provider_calls: StrictBool = False
    model: ModelId | None = None
    thinking_level: Thinking = "low"
    max_batches: Annotated[int, Field(strict=True, ge=1, le=4)] = 1
    max_prompt_chars: Annotated[int, Field(strict=True, ge=1000, le=200000)] = 60000


class FactInput(StrictModel):
    """One caller-supplied fact; every evidence ID must already be stored."""

    subject_id: Subject
    key: Predicate
    value: Value
    confidence: Confidence
    evidence_ids: Annotated[list[RecordId], Field(min_length=1, max_length=32)]


class MemoryRef(StrictModel):
    """The memory directory and the exact source digest it must describe."""

    memory_dir: LocalPath
    expected_source_sha256: Digest


class Mutation(MemoryRef):
    """Optimistic concurrency for every change after the first build."""

    expected_revision: Revision


class BuildRequest(MemoryRef):
    """Fold admitted artifacts and optional route responses into revision 1."""

    action: Literal["build"]
    file_path: LocalPath
    artifacts: Annotated[list[ArtifactRef], Field(max_length=16)] = []
    av_route: AVRoute | None = None


class AddFactsRequest(Mutation):
    """Add supplied facts or induce inferred facts and nonbinding name suggestions."""

    action: Literal["add_facts"]
    mode: Literal["supplied", "induce"]
    facts: Annotated[list[FactInput], Field(max_length=256)] = []
    induce: InduceOptions = InduceOptions()

    @model_validator(mode="after")
    def mode_inputs(self):
        """Keep supplied facts and model induction as separate explicit requests."""
        if (self.mode == "supplied") != bool(self.facts):
            raise ValueError("Supplied mode requires facts; induce mode forbids them")
        return self


class AlignRequest(Mutation):
    """Append an identity revision; ``name=None`` returns the person to unknown."""

    action: Literal["align"]
    person_id: PersonId
    name: Name | None
    basis: Literal["evidence_aligned", "user_asserted"]
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1, max_length=32)]
    note: Annotated[str, Field(max_length=2048)] | None = None


class IndexRequest(Mutation):
    """Embed stored records and active facts that still lack vectors."""

    action: Literal["index"]
    embedding: EmbeddingOptions


class StatusRequest(MemoryRef):
    """Existence, revision and per-window evidence coverage."""

    action: Literal["status"]


class OverviewRequest(MemoryRef):
    """People, fact-key directory and retrieval capability used for planning."""

    action: Literal["overview"]


class PeopleRequest(MemoryRef):
    """One or all person dossiers with identity history and suggestions."""

    action: Literal["people"]
    person_id: PersonId | None = None


class DialogueRequest(MemoryRef):
    """Every stored utterance of one person, or of everyone, in time order."""

    action: Literal["person_dialogue"]
    person_id: PersonId | None = None
    start_seconds: Seconds = 0
    end_seconds: Seconds | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100

    @model_validator(mode="after")
    def ordered(self):
        """Reject reversed intervals, as plan time ranges do."""
        if self.end_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must not precede start_seconds")
        return self


class TimelineRequest(MemoryRef):
    """Records overlapping one source interval, chronologically."""

    action: Literal["timeline"]
    start_seconds: Seconds = 0
    end_seconds: Seconds | None = None
    kinds: Annotated[list[Kind], Field(max_length=5)] = []
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100

    @model_validator(mode="after")
    def ordered(self):
        """Reject reversed intervals, as plan time ranges do."""
        if self.end_seconds is not None and self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must not precede start_seconds")
        return self


class MomentRequest(MemoryRef):
    """All records of selected windows, optionally with an exact-source clip."""

    action: Literal["moment"]
    windows: Annotated[list[Count], Field(min_length=1, max_length=8)]
    export_clip: StrictBool = False
    file_path: LocalPath | None = None

    @model_validator(mode="after")
    def clip_source(self):
        """Exact clips need the original source path as well as its digest."""
        if self.export_clip and self.file_path is None:
            raise ValueError("export_clip requires file_path")
        return self


class SearchRequest(MemoryRef):
    """Hybrid keyword/dense search over memory records, utterances or facts."""

    action: Literal["search"]
    scope: Literal["memory", "dialogue", "facts"] = "memory"
    query: Query | None = None
    key_prefix: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    subject_id: Subject | None = None
    include_superseded: StrictBool = False
    top_k: Annotated[int, Field(strict=True, ge=1, le=50)] = 5
    embedding: EmbeddingOptions | None = None

    @model_validator(mode="after")
    def selector(self):
        """Require query text, or a fact filter for the facts scope."""
        if self.query is None and (self.scope != "facts" or not (self.key_prefix or self.subject_id)):
            raise ValueError("Search requires query, or key_prefix/subject_id for facts")
        return self


class PlanRequest(MemoryRef):
    """One caller-planned retrieval; the question is echoed, never answered."""

    action: Literal["plan"]
    question: Annotated[str, Field(max_length=2048)] = ""
    people: Annotated[list[PersonId], Field(max_length=16)] = []
    fact_keys: Annotated[list[Annotated[str, Field(min_length=3, max_length=160)]], Field(max_length=32)] = []
    queries: Annotated[list[Query], Field(max_length=8)] = []
    time_ranges: Annotated[list[tuple[Seconds, Seconds]], Field(max_length=8)] = []
    include_environment: StrictBool = False
    top_k: Annotated[int, Field(strict=True, ge=1, le=20)] = 5
    embedding: EmbeddingOptions | None = None

    @model_validator(mode="after")
    def nonempty(self):
        """Reject plans that name no retrieval step at all."""
        if not (self.question.strip() or self.people or self.fact_keys or self.queries
                or self.time_ranges or self.include_environment):
            raise ValueError("A plan must name at least one retrieval step")
        if any(end < start for start, end in self.time_ranges):
            raise ValueError("Plan time ranges must be ordered")
        return self


VideoMemoryRequest = Annotated[
    Union[BuildRequest, AddFactsRequest, AlignRequest, IndexRequest, StatusRequest,
          OverviewRequest, PeopleRequest, DialogueRequest, TimelineRequest, MomentRequest,
          SearchRequest, PlanRequest],
    Field(discriminator="action"),
]


class InducedFact(BaseModel):
    """Provider output item; admitted only after FactInput and evidence validation."""

    subject_id: Annotated[str, Field(max_length=80)]
    key: Annotated[str, Field(max_length=80)]
    value: Annotated[str, Field(max_length=2048)]
    confidence: Annotated[str, Field(max_length=16)]
    evidence_ids: Annotated[list[Annotated[str, Field(max_length=96)]], Field(max_length=32)]


class InducedName(BaseModel):
    """Provider name candidate; stored only as a nonbinding suggestion."""

    person_id: Annotated[str, Field(max_length=16)]
    name: Annotated[str, Field(max_length=128)]
    evidence_ids: Annotated[list[Annotated[str, Field(max_length=96)]], Field(max_length=32)]


class InducedFacts(BaseModel):
    """Structured induction response schema for one record batch."""

    facts: Annotated[list[InducedFact], Field(max_length=64)]
    name_suggestions: Annotated[list[InducedName], Field(max_length=32)] = []
