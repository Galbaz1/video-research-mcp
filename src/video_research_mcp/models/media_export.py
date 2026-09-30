"""Typed local source-clip requests and measured derived-artifact receipts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, model_validator

from .media import Digest
from .native_media import CropBox, NativeSource, RequestedWindow


class ClipExportRequest(BaseModel):
    """A bounded half-open source-relative interval in display crop coordinates."""

    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(min_length=1, max_length=4096)
    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat = Field(gt=0)
    max_pixels: StrictInt = Field(default=1_000_000, ge=1, le=1_000_000)
    crop_box: CropBox | None = None
    expected_source_sha256: Digest | None = None
    include_audio: StrictBool = True

    @model_validator(mode="after")
    def bounded_window(self):
        """Reject reversed or overlong windows before touching source bytes."""
        if not 0 < self.end_seconds - self.start_seconds <= 60:
            raise ValueError("Clip interval must be positive and at most 60 seconds")
        return self


class ClipFrame(BaseModel):
    """An actual original decoded frame, distinct from requested boundaries."""

    actual_seconds: FiniteFloat
    original_pts: int
    time_base: str


class SelectedInterval(BaseModel):
    """Known selected frame points without inferring the final frame hold duration."""

    first_frame_seconds: FiniteFloat
    last_frame_seconds: FiniteFloat
    end_seconds: None = None
    last_frame_hold_verified: Literal[False] = False


class ClipArtifact(BaseModel):
    """One private encoded clip bound to measured bytes and display dimensions."""

    path: str
    sha256: Digest
    bytes: int = Field(gt=0, le=8 * 1024 * 1024)
    mime: Literal["video/mp4"] = "video/mp4"
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class EncodedClip(BaseModel):
    """Actual encoded container properties plus independently decoded frame timing."""

    duration_seconds: FiniteFloat = Field(gt=0)
    frame_count: int = Field(ge=1, le=256)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    first_frame_seconds: FiniteFloat
    last_frame_seconds: FiniteFloat
    decoded_frame_seconds: list[FiniteFloat] = Field(min_length=1, max_length=256)
    decoded_frame_pts: list[int] = Field(min_length=1, max_length=256)
    time_base: str
    video_codec: str
    frame_timing_verified: Literal[True] = True


class ClipAudio(BaseModel):
    """Decoded audio clocks; no perceptual or semantic synchrony assertion."""

    included: bool
    status: str
    source_decoded: dict | None = None
    output_decoded: dict | None = None
    source_av_start_delta_seconds: FiniteFloat | None = None
    output_av_start_delta_seconds: FiniteFloat | None = None
    output_end_padding_seconds: FiniteFloat | None = None
    timestamp_start_delta_error_seconds: FiniteFloat | None = None
    perceptual_sync_verified: Literal[False] = False


class ExportManifest(BaseModel):
    """Durable canonical manifest bytes required for source/artifact restart verification."""

    path: str
    sha256: Digest
    bytes: int = Field(gt=0, le=128 * 1024)


class ClipExportResult(BaseModel):
    """Complete bounded extraction with measured provenance and durable readback."""

    model_config = ConfigDict(extra="forbid")

    source: NativeSource
    operation: Literal["source_clip_export"] = "source_clip_export"
    provenance: Literal["extracted_source_clip"] = "extracted_source_clip"
    coordinate_space: Literal["display_pixels"] = "display_pixels"
    requested_interval: RequestedWindow
    actual_selected_interval: SelectedInterval
    source_frames: list[ClipFrame] = Field(min_length=1, max_length=256)
    artifacts: list[ClipArtifact] = Field(min_length=1, max_length=1)
    output: EncodedClip
    audio: ClipAudio
    crop_box: CropBox | None
    manifest: ExportManifest
    status: Literal["complete"] = "complete"
    watched_intervals: list = Field(default_factory=list, max_length=0)
    limits: dict
