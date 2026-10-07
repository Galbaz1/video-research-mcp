"""Finite image requests and model-specific operator declarations."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .materials import PinnedFile


class ImageOperation(BaseModel):
    """An explicit operation instruction; caller labels do not authenticate a principal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    principal: str = Field(min_length=1, max_length=100)
    authorize: bool = Field(default=False, strict=True)


class ImageReference(BaseModel):
    """Ordered actual image bytes, with a public URL required only for translation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["input", "identity", "style"]
    source: PinnedFile
    public_url: str | None = Field(default=None, max_length=2048)


class ImageGenerationRequest(BaseModel):
    """Freeze every caller intention before the single generation intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    logical_job_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    operation: ImageOperation
    mode: Literal["text_to_image", "image_edit", "image_translate"]
    model: Literal["qwen-image-2.0-pro", "qwen-mt-image"]
    prompt: str = Field(default="", max_length=1000)
    negative_prompt: str = Field(default="", max_length=500)
    size: str | None = Field(default=None, pattern=r"^[0-9]{3,4}\*[0-9]{3,4}$")
    n: int = Field(default=1, ge=1, le=6, strict=True)
    seed: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    prompt_extend: bool = Field(default=False, strict=True)
    watermark: bool | None = Field(default=None, strict=True)
    source_lang: str | None = None
    target_lang: str | None = None
    image_segment: bool = Field(default=False, strict=True)
    script_id: str = Field(min_length=1, max_length=100)
    scene_id: str = Field(min_length=1, max_length=100)
    script: PinnedFile
    scene: PinnedFile
    references: list[ImageReference] = Field(default_factory=list, max_length=3)
    continuation: PinnedFile | None = None
    unaffected_artifacts: list[PinnedFile] = Field(default_factory=list, max_length=16)
    transparent_background: bool = Field(default=False, strict=True)
    label: Literal["synthetic illustrative"] = "synthetic illustrative"
    quote: PinnedFile
    spend_authorized: bool = Field(default=False, strict=True)
    max_cost: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: Literal["USD", "CNY"]
    max_polls: int = Field(default=20, ge=1, le=120, strict=True)


class ImagePriceDeclaration(BaseModel):
    """Model-specific per-image price provenance declared by the operator."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_kind: Literal["operator_declaration"]
    provider: Literal["dashscope"]
    model: Literal["qwen-image-2.0-pro", "qwen-mt-image"]
    mode: Literal["text_to_image", "image_edit", "image_translate"]
    unit: Literal["image"]
    price_per_image: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: Literal["USD", "CNY"]
    principal: str = Field(min_length=1, max_length=100)
    source_url: str = Field(max_length=2048)
    source_revision: str = Field(min_length=1, max_length=200)
    recorded_at: datetime


class ImageAccessDeclaration(BaseModel):
    """Selected model/origin access declaration, without a provider acceptance claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_kind: Literal["operator_declaration"]
    provider: Literal["dashscope"]
    model: Literal["qwen-image-2.0-pro", "qwen-mt-image"]
    api_origin: str = Field(max_length=256)
    principal: str = Field(min_length=1, max_length=100)
    access: Literal["operator_declares_access"]
    source_url: str = Field(max_length=2048)
    source_revision: str = Field(min_length=1, max_length=200)
    recorded_at: datetime


class ImageQuote(BaseModel):
    """An exact request quote with immutable price and access source files."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_kind: Literal["operator_declaration"]
    provider: Literal["dashscope"]
    model: Literal["qwen-image-2.0-pro", "qwen-mt-image"]
    mode: Literal["text_to_image", "image_edit", "image_translate"]
    api_origin: str = Field(max_length=256)
    principal: str = Field(min_length=1, max_length=100)
    unit: Literal["image"]
    price_per_image: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: Literal["USD", "CNY"]
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_at: datetime
    valid_until: datetime
    price_source: PinnedFile
    model_access_source: PinnedFile


class ImageTaskOutput(BaseModel):
    """Official asynchronous translation task fields used for recovery."""

    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    task_status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"]
    image_url: str | None = Field(default=None, max_length=4096)
    message: str | None = Field(default=None, max_length=2000)


class ImageTaskResponse(BaseModel):
    """Provider task identity remains separate from request and durable job identity."""

    output: ImageTaskOutput
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")


class ImageGenerationResult(BaseModel):
    """Typed durable state and byte proof, with quality and live admission left open."""

    job_id: str
    status: str
    recorded_status: str
    provider_request_id: str | None
    provider_task_id: str | None
    request_sha256: str
    source_revision: str
    state: dict
    artifact_hashes: dict[str, str]
    attestation: dict
    error: str | None
