"""Finite selected Wan requests and explicit caller operations."""

from decimal import Decimal
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .materials import PinnedFile


GenerationModel = Literal["wan2.7-t2v", "wan2.7-i2v", "wan2.2-s2v",
                          "happyhorse-1.0-t2v", "happyhorse-1.0-i2v",
                          "happyhorse-1.0-r2v", "happyhorse-1.0-video-edit"]


class GenerationOperation(BaseModel):
    """An explicit caller instruction, without a principal-authentication claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    principal: str = Field(min_length=1, max_length=100)
    authorize: bool = Field(default=False, strict=True)


class GenerationReference(BaseModel):
    """A pinned reference intent that must have qualified selected-model support."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["first_frame", "last_frame", "identity", "style", "driving_audio", "first_clip",
                  "portrait", "reference", "source_video"]
    source: PinnedFile
    public_url: str | None = Field(default=None, max_length=4096, exclude_if=lambda v: v is None)


class GenerationRequest(BaseModel):
    """Freeze one logical scene generation, refusing unsupported intent before spend."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    logical_job_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    operation: GenerationOperation
    quote: PinnedFile
    model: GenerationModel = "wan2.7-t2v"
    prompt: str = Field(default="", max_length=5000)
    negative_prompt: str = Field(default="", max_length=500)
    duration: Annotated[int, Field(gt=0, lt=20, strict=True)] | Annotated[
        float, Field(gt=0, lt=20, strict=True, allow_inf_nan=False)] = 5
    resolution: Literal["480P", "720P", "1080P"] = "720P"
    ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "21:9", "9:21"] | None = "16:9"
    expected_dimensions: tuple[
        Annotated[int, Field(ge=16, le=8192, strict=True)],
        Annotated[int, Field(ge=16, le=8192, strict=True)],
    ] | None = Field(default=None, exclude_if=lambda value: value is None)
    seed: int = Field(default=0, ge=0, le=2147483647, strict=True)
    prompt_extend: bool = Field(default=False, strict=True, exclude_if=lambda value: value is False)
    watermark: bool = Field(default=True, strict=True, exclude_if=lambda value: value is True)
    script_id: str = Field(min_length=1, max_length=100)
    scene_id: str = Field(min_length=1, max_length=100)
    script: PinnedFile
    scene: PinnedFile
    references: list[GenerationReference] = Field(default_factory=list, max_length=10)
    continuation: PinnedFile | None = None
    transparent_background: bool = Field(default=False, strict=True)
    audio_setting: Literal["auto", "origin"] | None = Field(default=None, exclude_if=lambda v: v is None)
    expected_audio: Literal["present", "absent"] = "present"
    label: Literal["synthetic illustrative"] = "synthetic illustrative"
    max_polls: int = Field(default=20, ge=2, le=120, strict=True)
    spend_authorized: bool = Field(default=False, strict=True)
    max_cost: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: Literal["USD", "CNY"]


    @model_validator(mode="after")
    def selected_wan_limits(self):
        """Preserve original selected Wan schema refusal boundaries."""
        if self.model in {"wan2.7-t2v", "wan2.7-i2v"} and (
                not isinstance(self.duration, int) or not 2 <= self.duration <= 15
                or self.resolution not in {"720P", "1080P"}
                or self.ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4"}
                or len(self.references) > 4 or not self.prompt):
            raise ValueError("Selected Wan parameters exceed the original schema")
        return self

    @model_validator(mode="before")
    @classmethod
    def input_derived_ratio(cls, value):
        """Keep absent ratio intent distinct from unsupported explicit controls."""
        if isinstance(value, dict) and value.get("model") in {
                "wan2.2-s2v", "happyhorse-1.0-i2v", "happyhorse-1.0-video-edit"} and "ratio" not in value:
            return {**value, "ratio": None}
        return value


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
    results: dict[str, str] | None = None


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
    model: GenerationModel
    resolution: Literal["480P", "720P", "1080P"]
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
    model: GenerationModel
    resolution: Literal["480P", "720P", "1080P"]
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
    model: GenerationModel
    principal: str = Field(min_length=1, max_length=100)
    access: Literal["operator_declares_access"]
    source_url: str = Field(max_length=2048)
    source_revision: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
