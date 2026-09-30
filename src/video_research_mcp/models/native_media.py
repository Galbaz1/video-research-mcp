"""Typed deterministic media views and source-bound transcript selection."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, model_validator

from .media import Digest

NativeImageStatus = Literal[
    "included", "partial", "text_only", "inline_byte_limit", "inline_total_limit"
]
CropBox = Annotated[list[StrictInt], Field(min_length=4, max_length=4)]


class NativeSource(BaseModel):
    """Exact original bytes with measured local container/stream metadata."""

    model_config = ConfigDict(extra="allow")

    path: str
    sha256: Digest
    bytes: int = Field(gt=0)
    source_revision: str
    duration_seconds: FiniteFloat | None
    container_start_seconds: FiniteFloat | None
    stream_start_seconds: FiniteFloat | None = None
    stream_duration_seconds: FiniteFloat | None = None
    presentation_end_seconds: FiniteFloat | None = None
    stored_width: int | None
    stored_height: int | None
    display_width: int | None
    display_height: int | None
    sample_aspect_ratio: str | None = None
    display_geometry_basis: str | None = None
    pixel_aspect_verified: bool | None = None
    rotation_degrees: FiniteFloat | None
    time_base: str | None
    stream_index: int | None
    streams: list[dict]
    chapters: list[dict]
    metadata_method: str


class RequestedWindow(BaseModel):
    """Half-open requested window relative to the measured container presentation origin."""

    start_seconds: FiniteFloat
    end_seconds: FiniteFloat


class NativeCoverage(BaseModel):
    """Returned sampling points establish extraction, never continuous observation."""

    sampled_points: list[FiniteFloat]
    decoded_count: int = Field(
        ge=0, description="Decoded frame artifacts returned, not every frame visited by the decoder"
    )
    requested_window: RequestedWindow | None
    complete: bool = Field(description="Requested sampling completed; does not mean fully watched")
    stop_reason: str | None
    watched_intervals: list = Field(max_length=0)


class NativeArtifact(BaseModel):
    """An extracted PNG bound to its actual bytes and dimensions."""

    path: str
    sha256: Digest
    bytes: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    native_image_status: NativeImageStatus = "text_only"


class NativeFrame(NativeArtifact):
    """Requested time and original decoded PTS remain distinct after crop/scale."""

    requested_seconds: FiniteFloat | None
    actual_seconds: FiniteFloat | None
    original_pts: int | None
    time_base: str | None
    selection_method: str
    approximate: bool
    delta_seconds: FiniteFloat | None
    crop_box: CropBox | None


class NativeTile(BaseModel):
    """Exact sheet placement and the source frame represented by that tile."""

    frame_index: int = Field(ge=0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    actual_seconds: FiniteFloat | None
    original_pts: int | None
    time_base: str | None
    source_frame_sha256: Digest


class TranscriptSegment(BaseModel):
    """Caller-supplied text/times, not verified speech or factual evidence."""

    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat = Field(ge=0)
    text: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def ordered(self):
        """Reject reversed source intervals at the public boundary."""
        if self.end_seconds < self.start_seconds:
            raise ValueError("Transcript segment ends before it starts")
        return self


class FrameTranscript(BaseModel):
    """A bounded supplied transcript tied to exact original video bytes."""

    source_sha256: Digest
    segments: list[TranscriptSegment] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def bounded_text(self):
        """Bound the aggregate supplied text before query matching or decoding."""
        if sum(len(segment.text.encode("utf-8")) for segment in self.segments) > 64 * 1024:
            raise ValueError("Supplied transcript exceeds 64 KiB of text")
        return self


class TranscriptMatch(BaseModel):
    """Deterministic lexical selection with no semantic-confidence claim."""

    segment_index: int = Field(ge=0)
    segment: TranscriptSegment
    matched_tokens: list[str]
    query_tokens: list[str]
    method: Literal["lexical_token_overlap"] = "lexical_token_overlap"
    transcript_status: Literal["caller_supplied_unverified"] = "caller_supplied_unverified"


class NativeMediaResult(BaseModel):
    """Metadata, point frames or a tiled view, usable by native and text clients."""

    source: NativeSource
    frames: list[NativeFrame] = Field(default_factory=list, max_length=48)
    artifact: NativeArtifact | None = None
    tiles: list[NativeTile] = Field(default_factory=list, max_length=48)
    coverage: NativeCoverage | None = None
    status: Literal["complete", "partial"] = "complete"
    limits: dict = Field(default_factory=dict)
    native_image_status: NativeImageStatus = "text_only"
    transcript_match: TranscriptMatch | None = None
