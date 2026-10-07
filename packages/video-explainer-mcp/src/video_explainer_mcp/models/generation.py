"""Finite selected Wan requests and explicit caller operations."""

from decimal import Decimal
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .materials import PinnedFile


class GenerationOperation(BaseModel):
    """An explicit caller instruction, without a principal-authentication claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    principal: str = Field(min_length=1, max_length=100)
    authorize: bool = Field(default=False, strict=True)


class GenerationReference(BaseModel):
    """A pinned reference intent that must have qualified selected-model support."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["first_frame", "last_frame", "identity", "style", "driving_audio", "first_clip"]
    source: PinnedFile


class GenerationRequest(BaseModel):
    """Freeze one logical scene generation, refusing unsupported intent before spend."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    logical_job_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    operation: GenerationOperation
    quote: PinnedFile
    model: Literal["wan2.7-t2v", "wan2.7-i2v"] = "wan2.7-t2v"
    prompt: str = Field(min_length=1, max_length=5000)
    negative_prompt: str = Field(default="", max_length=500)
    duration: int = Field(default=5, ge=2, le=15, strict=True)
    resolution: Literal["720P", "1080P"] = "720P"
    ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4"] = "16:9"
    seed: int = Field(default=0, ge=0, le=2147483647, strict=True)
    script_id: str = Field(min_length=1, max_length=100)
    scene_id: str = Field(min_length=1, max_length=100)
    script: PinnedFile
    scene: PinnedFile
    references: list[GenerationReference] = Field(default_factory=list, max_length=4)
    continuation: PinnedFile | None = None
    transparent_background: bool = Field(default=False, strict=True)
    expected_audio: Literal["present", "absent"] = "present"
    label: Literal["synthetic illustrative"] = "synthetic illustrative"
    max_polls: int = Field(default=20, ge=2, le=120, strict=True)
    spend_authorized: bool = Field(default=False, strict=True)
    max_cost: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: Literal["USD", "CNY"]


class GenerationResult(BaseModel):
    """A typed durable readback, with qualification kept distinct from status."""

    model_config = ConfigDict(extra="forbid")
    job_id: str
    status: str
    recorded_status: str
    provider: Literal["dashscope"] = "dashscope"
    model: str
    source_revision: str
    request_sha256: str
    provider_operation_id: str | None
    state: dict
    artifact_hashes: dict[str, str]
    attestation: dict
    error: str | None


class TaskOutput(BaseModel):
    """Validate only the selected official task fields used by the adapter."""

    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    task_status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"]
    video_url: str | None = Field(default=None, max_length=4096)


class TaskResponse(BaseModel):
    """Typed official fetch/submit response; unused provider prose is not retained."""

    output: TaskOutput
    request_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")


class OperatorQuote(BaseModel):
    """Hash-pinned operator declaration, without provider or authentication proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_kind: Literal["operator_declaration"]
    provider: Literal["dashscope"]
    api_origin: str = Field(max_length=256)
    model: Literal["wan2.7-t2v"]
    resolution: Literal["720P", "1080P"]
    currency: Literal["USD", "CNY"]
    price_per_second: Decimal = Field(gt=0, allow_inf_nan=False)
    principal: str = Field(min_length=1, max_length=100)
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_at: datetime
    valid_until: datetime
    price_source: PinnedFile
    model_access_source: PinnedFile


class PriceDeclaration(BaseModel):
    """Exact selected price and primary-source provenance declared by the operator."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_kind: Literal["operator_declaration"]
    provider: Literal["dashscope"]
    model: Literal["wan2.7-t2v"]
    resolution: Literal["720P", "1080P"]
    currency: Literal["USD", "CNY"]
    price_per_second: Decimal = Field(gt=0, allow_inf_nan=False)
    principal: str = Field(min_length=1, max_length=100)
    source_url: str = Field(max_length=2048)
    source_revision: str = Field(min_length=1, max_length=200)
    recorded_at: datetime


class ModelAccessDeclaration(BaseModel):
    """Operator-declared selected model access with exact origin/source provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_kind: Literal["operator_declaration"]
    provider: Literal["dashscope"]
    api_origin: str = Field(max_length=256)
    model: Literal["wan2.7-t2v"]
    principal: str = Field(min_length=1, max_length=100)
    access: Literal["operator_declares_access"]
    source_url: str = Field(max_length=2048)
    source_revision: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
