"""Typed native-media metadata; crop provenance does not certify source truth."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CropResult(BaseModel):
    """Exact local pixel operation and hashes, usable by text-only MCP clients."""

    source_sha256: Digest
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    crop_box: list[int] = Field(min_length=4, max_length=4)
    artifact: str
    artifact_sha256: Digest
    artifact_width: int = Field(gt=0)
    artifact_height: int = Field(gt=0)
    operation: Literal["source-crop"]
    coordinate_space: Literal["original_image_pixels"] = "original_image_pixels"
    artifact_kind: Literal["extracted"] = "extracted"
    source_kind: Literal["unverified"] = "unverified"
    native_image_status: Literal["included", "text_only", "inline_byte_limit"]
