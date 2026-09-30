"""Finite source-bound JSON reports and native delivery for deterministic scene assets."""

import json

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .image_delivery import ImageDelivery
from .native_media import NativeSource


class SourceAssetMetadata(BaseModel):
    """Preserve complete operation-specific evidence alongside required source and limits."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    source: NativeSource
    limits: dict[str, JsonValue]

    @model_validator(mode="before")
    @classmethod
    def finite_json(cls, value):
        """Reject nonfinite nested provider-free evidence before any success is published."""
        json.dumps(value, allow_nan=False)
        return value


class SourceAssetResponse(BaseModel):
    """One complete local report with explicit delivery of actual bounded image bytes."""

    model_config = ConfigDict(extra="forbid")
    metadata: SourceAssetMetadata
    native_images: list[ImageDelivery]
