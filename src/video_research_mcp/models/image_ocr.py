"""Explicit local OCR requests and source-bound geometric observations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, model_validator

from .image_edit import CropRegion, ResizeSpec
from .media import Digest


class ImageOCRRequest(BaseModel):
    """Prepare one local image/frame and use only the explicitly selected local engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    file_path: str = Field(min_length=1, max_length=4096)
    engine: Literal["tesseract", "vision"]
    expected_source_sha256: Digest | None = None
    time_seconds: FiniteFloat | None = Field(default=None, ge=0, strict=True)
    crop: CropRegion | None = None
    resize: ResizeSpec | None = None
    max_pixels: StrictInt = Field(default=1_000_000, ge=1, le=1_000_000)
    languages: list[str] = Field(default_factory=list, max_length=8)
    locate: str | None = Field(default=None, min_length=1, max_length=256)
    max_matches: StrictInt = Field(default=16, ge=1, le=32)
    detect_barcodes: StrictBool = False
    detect_document_bounds: StrictBool = False

    @model_validator(mode="after")
    def backend_options(self):
        """Reject flag-like identifiers and unsupported detector requests before preparation."""
        import re

        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", value) for value in self.languages):
            raise ValueError("languages must contain bounded backend language identifiers")
        if self.engine == "tesseract" and (self.detect_barcodes or self.detect_document_bounds):
            raise ValueError("Barcode/document detectors require the explicitly selected vision engine")
        return self


class OCRBoundary(BaseModel):
    """Declared adapter precision policy and actual unclipped prepared-pixel overshoot."""

    model_config = ConfigDict(extra="forbid")
    policy: Literal["exact", "native_normalized_precision"]
    normalized_epsilon: FiniteFloat = Field(ge=0, le=2**-24)
    left_pixels: FiniteFloat = Field(ge=0)
    top_pixels: FiniteFloat = Field(ge=0)
    right_pixels: FiniteFloat = Field(ge=0)
    bottom_pixels: FiniteFloat = Field(ge=0)


class OCRObservation(BaseModel):
    """A raw local backend observation mapped through declared pixel-corner transforms."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["word", "line", "barcode", "document"]
    text: str | None = Field(default=None, max_length=4096)
    payload: str | None = Field(default=None, max_length=4096)
    symbology: str | None = Field(default=None, max_length=128)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    raw_box: list[FiniteFloat] = Field(min_length=4, max_length=4)
    raw_points: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=4, max_length=4)
    coordinate_space: Literal["normalized_bottom_left", "prepared_top_left_pixels"]
    prepared_points: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=4, max_length=4)
    oriented_points: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=4, max_length=4)
    stored_points: list[tuple[FiniteFloat, FiniteFloat]] = Field(min_length=4, max_length=4)
    line_id: list[StrictInt] | None = None
    geometry_boundary: OCRBoundary | None = None


class ImageOCRResult(BaseModel):
    """Bounded source observations and exact artifacts, without semantic structure claims."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["complete"]
    engine: Literal["tesseract", "vision"]
    preparation: dict
    observations: list[OCRObservation] = Field(max_length=128)
    text: str = Field(max_length=65536)
    matches: list[dict] = Field(max_length=32)
    match_count: StrictInt = Field(ge=0)
    matches_truncated: StrictBool
    raw_backend_artifact: dict
    source: dict
    artifacts: list[dict]
    runtime: dict
    limits: dict
    provenance: dict
    manifest: dict
