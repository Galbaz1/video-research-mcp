"""Concrete bounded local image editing requests and verified result records."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Point = tuple[Number, Number]
Matrix = tuple[tuple[Number, Number, Number], tuple[Number, Number, Number],
               tuple[Number, Number, Number]]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class StrictModel(BaseModel):
    """Reject undeclared fields and nonfinite values at the public boundary."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CropRegion(StrictModel):
    """Integer pixel xywh or normalized1000 xyxy in the oriented source grid."""

    space: Literal["pixel", "normalized1000"] = "pixel"
    coordinates: tuple[Annotated[int, Field(strict=True)], Annotated[int, Field(strict=True)],
                       Annotated[int, Field(strict=True)], Annotated[int, Field(strict=True)]] | tuple[Number, Number, Number, Number]

    @model_validator(mode="before")
    @classmethod
    def pixel_integers(cls, value):
        """Keep pixel crops exact rather than silently rounding caller coordinates."""
        if isinstance(value, dict) and value.get("space", "pixel") == "pixel":
            if any(type(v) is not int for v in value.get("coordinates", ())):
                raise ValueError("Pixel crop coordinates must be integers")
        return value

    @model_validator(mode="after")
    def ordered_bounds(self):
        """Reject nonpositive or reversed crop extents before any source read."""
        x, y, a, b = self.coordinates
        if min(x, y) < 0 or (self.space == "pixel" and min(a, b) <= 0):
            raise ValueError("Crop coordinates must have positive extents")
        if self.space == "normalized1000" and (max(self.coordinates) > 1000 or a <= x or b <= y):
            raise ValueError("Normalized crop must be ordered inside 0..1000")
        return self


class ResizeSpec(StrictModel):
    """An explicit exact target size; the caller chooses its aspect ratio."""

    width: Annotated[int, Field(strict=True, ge=1, le=4096)]
    height: Annotated[int, Field(strict=True, ge=1, le=4096)]


class ImageAnnotation(StrictModel):
    """Source-grid box/circle/arrow corners or number/text anchors."""

    kind: Literal["box", "circle", "arrow", "number", "text"]
    space: Literal["pixel", "normalized1000"] = "pixel"
    coordinates: tuple[Number, ...]
    text: Annotated[str, Field(max_length=256)] = ""
    color: Annotated[str, Field(pattern=r"^#[a-fA-F0-9]{6}$")] = "#e53935"
    width: Annotated[int, Field(strict=True, ge=1, le=12)] = 2
    font_size: Annotated[int, Field(strict=True, ge=8, le=64)] = 16
    closeup_padding: Annotated[Number | None, Field(ge=0, le=0.4)] = None

    @model_validator(mode="after")
    def geometry_and_text(self):
        """Require one concrete geometry and a useful label for text or numbers."""
        expected = 4 if self.kind in {"box", "circle", "arrow"} else 2
        if len(self.coordinates) != expected:
            raise ValueError(f"{self.kind} requires {expected} coordinates")
        if min(self.coordinates) < 0 or (self.space == "normalized1000" and max(self.coordinates) > 1000):
            raise ValueError("Annotation coordinates exceed their coordinate space")
        if self.kind in {"box", "circle"}:
            x, y, a, b = self.coordinates
            if a <= x or b <= y:
                raise ValueError("Annotation corners must be ordered")
        if self.kind == "arrow" and self.coordinates[:2] == self.coordinates[2:]:
            raise ValueError("Arrow endpoints must differ")
        if self.kind == "text" and not self.text:
            raise ValueError("Text annotations require text")
        if self.kind == "number" and not self.text.isdecimal():
            raise ValueError("Number annotations require a decimal text label")
        if self.kind not in {"box", "circle"} and self.closeup_padding is not None:
            raise ValueError("Closeups apply only to box and circle annotations")
        return self


class CutoutSpec(StrictModel):
    """Explicit outer/inner polygon rings or a conservative opaque-background seed."""

    method: Literal["polygon", "flood"]
    space: Literal["pixel", "normalized1000"] = "pixel"
    rings: Annotated[list[list[Point]], Field(max_length=16)] = []
    seed: Point | None = None
    tolerance: Annotated[int, Field(strict=True, ge=0, le=765)] = 26
    crop_to_bbox: bool = True

    @model_validator(mode="after")
    def concrete_method(self):
        """Reject ambiguous cutouts and cap caller geometry independently of pixels."""
        if sum(len(ring) for ring in self.rings) > 512:
            raise ValueError("Cutout polygons exceed the 512 point limit")
        if self.method == "polygon":
            if self.seed is not None or not self.rings or any(not 3 <= len(r) <= 128 for r in self.rings):
                raise ValueError("Polygon cutouts require outer/inner rings of 3..128 points")
        elif self.rings or self.seed is None:
            raise ValueError("Flood cutouts require a seed and no polygon rings")
        points = [p for ring in self.rings for p in ring] + ([self.seed] if self.seed else [])
        if any(min(p) < 0 or (self.space == "normalized1000" and max(p) > 1000) for p in points):
            raise ValueError("Cutout coordinates exceed their coordinate space")
        return self


class ImageEditRequest(StrictModel):
    """One bounded source, optional precise video point, and deterministic edit chain."""

    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest | None = None
    time_seconds: Annotated[Number | None, Field(ge=0)] = None
    crop: CropRegion | None = None
    resize: ResizeSpec | None = None
    annotations: Annotated[list[ImageAnnotation], Field(max_length=32)] = []
    cutout: CutoutSpec | None = None
    output_format: Literal["png", "jpeg", "webp", "bmp", "gif"] = "png"
    quality: Annotated[int, Field(strict=True, ge=1, le=100)] = 85
    include_exif: bool = False
    jpeg_background: tuple[Annotated[int, Field(strict=True, ge=0, le=255)],
                           Annotated[int, Field(strict=True, ge=0, le=255)],
                           Annotated[int, Field(strict=True, ge=0, le=255)]] = (255, 255, 255)
    max_pixels: Annotated[int, Field(strict=True, ge=1, le=1000000)] = 1000000


class ImageArtifact(StrictModel):
    """One exact encoded artifact and its geometry/provenance role."""

    path: str
    sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=1, le=8388608)]
    width: Annotated[int, Field(strict=True, ge=1)]
    height: Annotated[int, Field(strict=True, ge=1)]
    mime: Literal["image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"]
    role: Literal["image", "closeup", "alpha_mask"] = "image"
    annotation_index: int | None = None
    output_box: tuple[int, int, int, int] | None = None
    output_to_source: Matrix | None = None


class ImageTransforms(StrictModel):
    """Forward and inverse homogeneous pixel-corner transforms."""

    stored_to_oriented: Matrix
    oriented_to_output: Matrix
    source_to_output: Matrix
    output_to_source: Matrix


class ManifestArtifact(StrictModel):
    """The externally digest-bound canonical JSON manifest file."""

    path: str
    sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=1, le=131072)]


class ImageEditResult(StrictModel):
    """A complete local edit with source identity, artifacts and restart readback."""

    status: Literal["complete"]
    source: dict
    frame: dict | None
    artifact: ImageArtifact
    artifacts: list[ImageArtifact]
    transforms: ImageTransforms
    request: dict
    request_sha256: Digest
    operation_sha256: Digest
    provenance: dict
    warnings: list[str]
    cutout: dict | None
    limits: dict
    manifest: ManifestArtifact
