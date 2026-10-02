"""Public native delivery metadata for image edits and verified manifests."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .image_edit import ImageEditResult


class ImageDelivery(BaseModel):
    """One artifact's explicit native transport outcome."""

    model_config = ConfigDict(extra="forbid")
    path: str
    mime: Literal["image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"]
    status: Literal["text_only", "included", "inline_byte_limit", "inline_total_limit", "unsupported_native_mime"]


class ImageEditResponse(BaseModel):
    """Typed edit provenance and delivery of its actual image bytes."""

    model_config = ConfigDict(extra="forbid")
    metadata: ImageEditResult
    native_images: list[ImageDelivery]


class ImageManifestResponse(BaseModel):
    """Digest-verified image, clip or OCR manifest and optional image blocks."""

    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]
    verified: Literal[True] = True
    native_images: list[ImageDelivery]
