"""Concrete external raster segmentation requests and artifact/readiness records."""

import ipaddress
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .image_delivery import ImageDelivery
from .image_edit import Digest, ImageArtifact, ManifestArtifact, Number


class StrictModel(BaseModel):
    """Reject extra fields, implicit scalar coercion and nonfinite values."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class SegmentationRequest(StrictModel):
    """Bind one original still image and an explicit optional submission grant."""

    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest
    prompt: Annotated[str, Field(min_length=1, max_length=512)]
    service_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    dry_run: bool = True
    submission_authorized: bool = False

    @model_validator(mode="after")
    def useful_prompt(self):
        """Refuse a whitespace-only prompt without editing its approved text."""
        if not self.prompt.strip():
            raise ValueError("Segmentation requires a nonempty prompt")
        return self


class SegmentationService(StrictModel):
    """Operator-selected endpoint and declarations, without model-load attestation."""

    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    local: bool = False
    origin: Literal["mock-fixture", "model-service"]
    api_key_env: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")] = None
    declared_model: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    checkpoint_sha256: Digest | None = None

    @model_validator(mode="after")
    def fixed_origin(self):
        """Admit only a clean HTTPS origin or explicitly local literal loopback."""
        if any(ord(char) <= 32 or ord(char) == 127 for char in self.base_url):
            raise ValueError("Service URL contains invalid characters")
        parsed = urlsplit(self.base_url)
        if not parsed.hostname or parsed.username is not None or parsed.password is not None or "?" in self.base_url or "#" in self.base_url:
            raise ValueError("Service URL requires a host without userinfo, query or fragment")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Service port is invalid")
        if self.local:
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "::1"}:
                raise ValueError("Local services require literal loopback")
        elif parsed.scheme != "https":
            raise ValueError("Remote services require HTTPS")
        else:
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise ValueError("Remote service address must be public")
        return self


class SegmentationArtifact(ImageArtifact):
    """Actual encoded PNG identity and decoded pixel identity on the original grid."""

    pixel_sha256: Digest
    pixel_mode: Literal["RGB", "RGBA", "L"]
    origin: Literal["source_derived", "mock_fixture", "external_service_prediction"]


class SegmentationMask(StrictModel):
    """Uncalibrated score and a validated original-grid binary mask proposal."""

    index: Annotated[int, Field(ge=0, le=15)]
    score: Annotated[Number, Field(ge=0, le=1)]
    box_xyxy: Annotated[list[Number], Field(min_length=4, max_length=4)]
    mask: SegmentationArtifact
    stored_mode: Literal["L", "1"]
    foreground_pixels: Annotated[int, Field(ge=1)]
    total_pixels: Annotated[int, Field(ge=1, le=1000000)]
    coverage: Annotated[Number, Field(gt=0, le=1)]
    coordinate_convention: Literal["continuous_original_pixel_xyxy"] = "continuous_original_pixel_xyxy"
    semantic_correctness_verified: Literal[False] = False


class SegmentationResult(StrictModel):
    """Planned or completed wire/image artifacts with separate readiness declarations."""

    status: Literal["planned", "complete"]
    source: dict
    artifact: SegmentationArtifact
    artifacts: list[SegmentationArtifact]
    masks: list[SegmentationMask]
    num_masks: Annotated[int, Field(ge=0, le=16)]
    outcome: Literal["planned", "mask_proposals", "abstention"]
    service: dict
    readiness: dict
    request: dict
    request_sha256: Digest
    operation_sha256: Digest
    response_sha256: Digest | None
    provenance: dict
    warnings: list[str]
    limits: dict
    manifest: ManifestArtifact


class SegmentationResponse(StrictModel):
    """Public metadata plus exact native-delivery outcomes from the shared transport."""

    metadata: SegmentationResult
    native_images: list[ImageDelivery]
