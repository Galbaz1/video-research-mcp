"""Bounded model-vision requests, configured origins and inferred geometry."""

from typing import Annotated, Literal
from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .image_edit import CropRegion, Digest, Number, ResizeSpec, StrictModel
from ..errors import ToolError


class VisionBackend(StrictModel):
    """One operator-selected compatible endpoint; requests cannot replace credentials."""

    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    model: Annotated[str, Field(min_length=1, max_length=256)]
    api_key_env: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]*API_KEY$")] = None
    local: bool = False
    capabilities: Annotated[list[Literal["images", "video", "structured_json"]], Field(min_length=1, max_length=3)]
    video_delivery: Literal["sampled_frames", "dashscope_temporary"] = "sampled_frames"
    structured_format: Literal["json_object", "json_schema"] = "json_object"
    upload_policy_url: str | None = None
    max_video_seconds: Annotated[Number, Field(gt=0, le=7200)] = 120

    @model_validator(mode="after")
    def configured_origin(self):
        """Fence local origins and bind temporary storage to the selected account origin."""
        p = urlsplit(self.base_url)
        if not p.hostname or p.username or p.password or p.query or p.fragment or any(ord(c) < 33 for c in self.base_url):
            raise ValueError("Vision base URL must have an origin and no credentials/query/fragment")
        if self.local:
            if p.scheme not in {"http", "https"} or p.hostname not in {"127.0.0.1", "::1"}:
                raise ValueError("Local vision requires an explicitly configured literal loopback origin")
        elif p.scheme != "https":
            raise ValueError("Remote vision requires HTTPS")
        if not self.local:
            try:
                address = ip_address(p.hostname)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise ValueError("Remote vision cannot address a private or loopback IP")
        if self.video_delivery == "dashscope_temporary":
            expected = f"https://{p.netloc}/api/v1/uploads"
            if self.local or p.hostname not in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} or self.upload_policy_url != expected or p.port not in (None, 443) or not self.api_key_env:
                raise ValueError("Temporary storage requires the exact selected official DashScope policy origin and credential")
        elif self.upload_policy_url is not None:
            raise ValueError("Upload policy belongs only to the explicit temporary-storage route")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("Backend capabilities must be unique")
        return self


class VisionSource(StrictModel):
    """An exact original image, source frame, or bounded video selection."""

    kind: Literal["image", "frame", "video"] = "image"
    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest
    time_seconds: Annotated[Number | None, Field(ge=0)] = None
    crop: CropRegion | None = None
    resize: ResizeSpec | None = None
    start_seconds: Annotated[Number, Field(ge=0)] = 0
    end_seconds: Annotated[Number | None, Field(gt=0)] = None
    fps: Annotated[Number, Field(ge=0.1, le=10)] = 1
    max_frames: Annotated[int, Field(strict=True, ge=1, le=32)] = 16

    @model_validator(mode="after")
    def selected_media(self):
        """Reject ambiguous point/window/crop requests before local preparation."""
        if (self.kind == "frame") != (self.time_seconds is not None):
            raise ValueError("Only frame sources require time_seconds")
        if self.kind == "video":
            if self.crop is not None or self.resize is not None:
                raise ValueError("Video chat uses bounded whole-frame sampling; crop/resize belong to frame sources")
            if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
                raise ValueError("Video end must exceed start")
        elif self.start_seconds != 0 or self.end_seconds is not None:
            raise ValueError("Video intervals belong only to video sources")
        return self


class VisionLimits(StrictModel):
    """Still/frame transmission limits without fabricated video windows."""

    max_calls: Annotated[int, Field(strict=True, ge=1, le=9)] = 2
    max_tokens: Annotated[int, Field(strict=True, ge=1, le=2000000)] = 100000
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=8192)] = 2048

    @model_validator(mode="after")
    def output_reservation(self):
        """Reject an output reservation larger than the declared total limit."""
        if self.max_output_tokens > self.max_tokens:
            raise ValueError("max_output_tokens exceeds max_tokens")
        return self


class VisionRequest(StrictModel):
    """One explicit model workflow; dry plans do not authorize submission."""

    sources: Annotated[list[VisionSource], Field(min_length=1, max_length=4)]
    instruction: Annotated[str, Field(min_length=1, max_length=8192)]
    backend: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")] = "gemini"
    dry_run: bool = True
    authorize_submission: bool = False
    limits: VisionLimits = VisionLimits()
    thinking_level: Literal["low", "medium", "high"] = "medium"
    output_schema: dict | None = None
    export_crops: bool = False


class InferredRegion(StrictModel):
    """Strict normalized1000 corners relative to one transmitted prepared image."""

    source_index: Annotated[int, Field(strict=True, ge=0, le=3)]
    label: Annotated[str, Field(min_length=1, max_length=1024)]
    bbox: tuple[Number, Number, Number, Number]

    @model_validator(mode="after")
    def ordered_normalized_corners(self):
        """Reject nonfinite, reversed or out-of-bounds model geometry."""
        x, y, a, b = self.bbox
        if min(self.bbox) < 0 or max(self.bbox) > 1000 or a <= x or b <= y:
            raise ValueError("Model bbox must be ordered normalized1000 xyxy within 0..1000")
        return self


class VisionAnswer(StrictModel):
    """Model interpretation and proposed regions; neither establishes observation."""

    answer: Annotated[str, Field(max_length=32768)]
    regions: Annotated[list[InferredRegion], Field(max_length=16)] = []


class VisionResponse(StrictModel):
    """Observed payload lineage kept distinct from a model's interpretation."""

    status: Literal["planned", "complete"]
    operation: Literal["vision_chat", "ocr", "grounding"]
    backend: dict
    request_sha256: Digest
    preparations: list[dict]
    payload_receipt: list[dict]
    model_output: dict | None
    regions: list[dict]
    execution: dict
    uploads: list[dict]
    provenance: dict


class VisionFailure(ToolError):
    """Keep attempted transmissions and storage uncertainty after an unsuccessful call."""

    execution: dict
    payload_receipt: list[dict]
    request_sha256: Digest | None
    uploads: list[dict]
