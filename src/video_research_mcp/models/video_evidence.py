"""Source-bound temporal OCR, receipt-only speech and uncertain numeric candidates."""

from fractions import Fraction
import math
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from ..errors import ToolError
from .image_edit import CropRegion, Digest, ImageEditResult, Number, ResizeSpec, StrictModel
from .image_ocr import ImageOCRRequest, ImageOCRResult
from .native_media import NativeCoverage
from .transcript import TranscriptRequest, TranscriptResult


class TemporalOCRRequest(StrictModel):
    """Observe explicit source points with one local OCR policy and optional readback."""

    file_path: str = Field(min_length=1, max_length=4096)
    expected_source_sha256: Digest
    times_seconds: Annotated[
        list[Annotated[Number, Field(ge=0)]], Field(min_length=1, max_length=6)
    ]
    engine: Literal["vision", "tesseract"]
    crop: CropRegion | None = None
    resize: ResizeSpec | None = None
    languages: list[str] = Field(default_factory=list, max_length=8)
    max_pixels: StrictInt = Field(default=1_000_000, ge=1, le=1_000_000)
    track_numbers: StrictBool = False
    transcript: TranscriptRequest | None = None

    @model_validator(mode="after")
    def source_policy(self):
        """Reuse image options and reject ambiguous clocks or a new speech submission."""
        if any(b <= a for a, b in zip(self.times_seconds, self.times_seconds[1:])):
            raise ValueError("times_seconds must be strictly increasing")
        ImageOCRRequest.model_validate(
            self.model_dump(exclude={"times_seconds", "track_numbers", "transcript"})
        )
        if self.transcript and (
            self.transcript.action != "readback"
            or self.transcript.file_path != self.file_path
            or self.transcript.expected_source_sha256 != self.expected_source_sha256
        ):
            raise ValueError(
                "transcript requires exact same source/digest and receipt-only readback"
            )
        return self


class OCRFrameClock(StrictModel):
    """The existing preparation frame clock; requested time is never its observation."""

    requested_seconds: Annotated[Number, Field(ge=0)]
    actual_seconds: Annotated[Number, Field(ge=0)]
    original_pts: StrictInt
    time_base: str = Field(min_length=3, max_length=64)
    selection_method: Literal["first_decoded_at_or_after"]
    approximate: Literal[False]
    delta_seconds: Number
    decoded_frame_sha256: Digest
    decoded_width: StrictInt = Field(gt=0)
    decoded_height: StrictInt = Field(gt=0)


class OCRPreparation(ImageEditResult):
    """Reuse existing edit transforms and require an actual video frame clock."""

    frame: OCRFrameClock


class TimelineOCR(ImageOCRResult):
    """Reuse the complete OCR contract with typed source-frame preparation."""

    preparation: OCRPreparation

    @model_validator(mode="after")
    def original_clock(self):
        """Bind observed time to source PTS rather than a copied request timestamp."""
        frame = self.preparation.frame
        basis = Fraction(frame.time_base)
        actual = float(frame.original_pts * basis) - self.source["container_start_seconds"]
        if (
            basis <= 0
            or basis != Fraction(self.source["time_base"])
            or frame.actual_seconds < frame.requested_seconds
            or not math.isclose(actual, frame.actual_seconds, abs_tol=1e-9, rel_tol=0)
            or not math.isclose(
                frame.delta_seconds, actual - frame.requested_seconds, abs_tol=1e-9, rel_tol=0
            )
        ):
            raise ValueError("OCR preparation clock differs from its original source PTS")
        return self


class NumericObservation(StrictModel):
    """Exact single-line decimal token in the shared ROI, or explicit ambiguity."""

    status: Literal["parsed", "missing", "ambiguous", "unsupported"]
    token: str | None = Field(default=None, max_length=128)
    value: str | None = Field(default=None, max_length=128)
    observation_indices: list[StrictInt] = Field(default_factory=list, max_length=128)
    confidence: Annotated[Number | None, Field(ge=0, le=1)] = None
    uncertainty: str = "OCR text/confidence are backend observations, not verified numeric truth"


class OCRTimelinePoint(StrictModel):
    """One requested point remains present even when its native operation fails."""

    index: StrictInt = Field(ge=0, le=5)
    requested_seconds: Annotated[Number, Field(ge=0)]
    status: Literal["not_run", "complete", "failed"] = "not_run"
    reason: str | None = "not_attempted"
    error: ToolError | None = None
    cleanup_error: ToolError | None = None
    ocr: TimelineOCR | None = None
    text_changed: StrictBool | None = None
    number: NumericObservation | None = None


class NumericReversal(StrictModel):
    """A decrease between adjacent observed decimals, not semantic bug correctness."""

    basis: Literal["ocr_numeric_heuristic"] = "ocr_numeric_heuristic"
    uncertain: Literal[True] = True
    previous_point_index: StrictInt = Field(ge=0, le=5)
    point_index: StrictInt = Field(ge=0, le=5)
    actual_seconds: Annotated[Number, Field(ge=0)]
    previous_value: str = Field(max_length=128)
    value: str = Field(max_length=128)
    previous_confidence: Annotated[Number | None, Field(ge=0, le=1)]
    confidence: Annotated[Number | None, Field(ge=0, le=1)]
    source_sha256: Digest
    previous_raw_backend_sha256: Digest
    raw_backend_sha256: Digest
    uncertainty: str = "Unverified OCR recognition; numeric decrease is a heuristic candidate"


class TimelineSpeech(StrictModel):
    """Existing receipt readback retains caption versus model/word/speaker provenance."""

    status: Literal["absent", "verified_readback", "failed", "not_run"] = "absent"
    transcript: TranscriptResult | None = None
    error: ToolError | None = None


class TemporalOCRResult(StrictModel):
    """Bounded point observations and separate speech and numeric heuristic channels."""

    operation: Literal["video_ocr_timeline"] = "video_ocr_timeline"
    status: Literal["complete", "partial", "failed"] = "failed"
    request: TemporalOCRRequest
    source: dict | None = None
    source_verified: StrictBool = False
    points: list[OCRTimelinePoint] = Field(min_length=1, max_length=6)
    speech: TimelineSpeech = Field(default_factory=TimelineSpeech)
    numeric_candidates: list[NumericReversal] = Field(default_factory=list, max_length=5)
    artifacts: list[dict] = Field(default_factory=list, max_length=57)
    artifact_bytes: StrictInt = Field(default=0, ge=0, le=8_388_608)
    coverage: NativeCoverage | None = None
    provenance: dict = {
        "ocr": "local_backend_observations_not_verified_text_truth",
        "speech": "retained_transcript_provenance; captions are assertions, model words/speakers are inference",
        "numeric_candidates": "uncertain_ocr_numeric_heuristic",
        "continuous_observation": False,
        "visual_pruning": "none; every selected point retained",
        "new_speech_inference": False,
    }
    limits: dict = {
        "max_points": 6,
        "deadline_seconds": 300,
        "aggregate_artifact_bytes": 8_388_608,
        "provider_calls": 0,
        "weights_or_installs": 0,
    }
    error: ToolError | None = None
