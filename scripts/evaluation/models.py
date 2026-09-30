"""Strict file-boundary contracts for frozen evaluation bundles and outcomes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["ok", "abstained", "unavailable", "error", "timeout", "refused", "empty"]


class Record(BaseModel):
    """Reject extra fields rather than silently ignoring a changed contract."""

    model_config = ConfigDict(extra="forbid")


class Source(Record):
    """Immutable local source snapshot or media asset."""

    id: str
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    modality: str
    content_type: str


class Case(Record):
    """Input given to both systems; labels are stored separately."""

    id: str
    family: str
    workflow: str
    modalities: list[str]
    question: str
    sources: list[Source]
    sampling: dict


class Evidence(Record):
    """An exact source passage, optionally associated with a time interval."""

    source_id: str
    quote: str | None = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def interval(self):
        """Require paired, ordered interval boundaries when present."""
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("interval needs both boundaries")
        if self.start_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("interval ends before it starts")
        return self


class Fact(Record):
    """Canonical fact with all independently labeled required passages."""

    id: str
    text: str = Field(min_length=1)
    evidence: list[Evidence]


class Temporal(Record):
    """Exact reference interval, scored independently of prose."""

    id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def interval(self):
        """Reject reversed intervals at the result boundary."""
        if self.end_ms < self.start_ms:
            raise ValueError("interval ends before it starts")
        return self


class Label(Record):
    """Reference outcome withheld from system prompts."""

    facts: list[Fact]
    expected_abstention: bool
    temporal: list[Temporal]
    required_artifacts: list[str]
    expected_status: Status


class Claim(Record):
    """System answer decomposed into claims without self-assigned confidence."""

    fact_id: str
    text: str
    citations: list[Evidence]


class Artifact(Record):
    """System output whose bytes will be checked independently."""

    id: str
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Usage(Record):
    """Observed resource fields independent of answer-schema validity."""

    latency_ms: int | None = Field(ge=0)
    calls: int | None = Field(ge=0)
    auxiliary_calls: int | None = Field(ge=0)
    cost_usd: float | None = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)


class Outcome(Usage):
    """One attempt, including explicit failure and usage observations."""

    case_id: str
    status: Status
    claims: list[Claim]
    temporal: list[Temporal]
    artifacts: list[Artifact]


class Receipt(Record):
    """Run controls frozen before execution; missing telemetry remains unknown."""

    run_id: str
    split: Literal["development", "heldout"]
    mode: Literal["offline_contract", "live"]
    candidate_revision: str
    baseline_revision: str
    system: str
    provider_settings: dict
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    protocol_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluator_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    inputs_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    labels_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    outputs_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_snapshots_sha256: str | None
    experiment_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_ids: list[str]
    budget: dict
    authority_receipt: str | None
    human_audit: dict
