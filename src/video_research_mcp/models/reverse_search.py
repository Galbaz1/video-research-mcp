"""Exact frame-query lineage and pending identity checks for Serper Lens."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .image_edit import Digest, Number, StrictModel
from .native_media import NativeMediaResult
from .search_provider import ProviderRejection, SearchExecution, SourceLimits
from ..errors import ToolError


class ReverseFrameRequest(SourceLimits):
    """One existing captured point; publication and search require separate grants."""

    capture: NativeMediaResult
    authorize_public_upload: Annotated[bool, Field(strict=True)] = False
    max_query_bytes: Annotated[int, Field(strict=True, ge=1, le=128 * 1024)] = 128 * 1024
    num_results: Annotated[int, Field(strict=True, ge=1, le=10)] = 5

    @model_validator(mode="after")
    def one_point(self):
        """Require a complete precise point rather than inferred whole-video coverage."""
        if self.capture.status != "complete" or len(self.capture.frames) != 1:
            raise ValueError("Reverse search requires one complete captured frame")
        frame = self.capture.frames[0]
        if (frame.approximate or frame.actual_seconds is None or frame.requested_seconds is None
                or frame.original_pts is None or frame.time_base is None
                or frame.selection_method != "first_decoded_at_or_after"):
            raise ValueError("Reverse search requires precise decoded point metadata")
        return self


class FrameQuery(StrictModel):
    """Read-back byte identities; temporal relationship remains caller-supplied capture metadata."""

    source_sha256: Digest
    source_bytes: Annotated[int, Field(strict=True, gt=0)]
    frame_sha256: Digest
    frame_bytes: Annotated[int, Field(strict=True, gt=0)]
    width: Annotated[int, Field(strict=True, gt=0)]
    height: Annotated[int, Field(strict=True, gt=0)]
    requested_seconds: Number
    actual_seconds: Number
    original_pts: Annotated[int, Field(strict=True)]
    time_base: str
    crop_box: list[int] | None
    source_reference: str
    capture_metadata_origin: Literal["caller_supplied"] = "caller_supplied"
    original_and_frame_bytes_verified_at_admission: Literal[True] = True
    watched_intervals: list = []


class FramePublication(StrictModel):
    """Public disclosure receipt; absent acknowledgement never implies no upload."""

    publisher: Literal["uguu"] = "uguu"
    status: Literal["not_attempted", "outcome_unknown", "url_received", "bytes_verified"] = "not_attempted"
    url: str | None = None
    attempted_at: str | None = None
    acknowledged_at: str | None = None
    submitted_image_sha256: Digest | None = None
    submitted_image_bytes: Annotated[int | None, Field(strict=True, ge=0)] = None
    hosted_response_sha256: Digest | None = None
    retention_verified: Literal[False] = False
    deletion_verified: Literal[False] = False
    service_contract_live_verified: Literal[False] = False


class LensCandidate(StrictModel):
    """Untrusted similarity suggestion; no field promotes an entity or original source."""

    url: str
    title: str | None
    source: str | None
    image_url: str | None
    identity_asserted: Literal[False] = False
    verification_status: Literal["pending_appearance_text_context"] = "pending_appearance_text_context"
    url_dns_verified: Literal[False] = False


class ReverseFrameResponse(StrictModel):
    """Planned or bounded search with full publication and rejected-result accounting."""

    operation: Literal["reverse_frame"] = "reverse_frame"
    status: Literal["planned", "complete", "partial"]
    backend: Literal["serper"] = "serper"
    query: FrameQuery
    request_sha256: Digest
    publication: FramePublication
    results: Annotated[list[LensCandidate], Field(max_length=10)] = []
    rejections: Annotated[list[ProviderRejection], Field(max_length=100)] = []
    returned_population: Annotated[int, Field(strict=True, ge=0, le=100)] = 0
    execution: SearchExecution
    source_content_role: Literal["data"] = "data"
    identity_asserted: Literal[False] = False
    factual_success: Literal[False] = False


class ReverseFrameError(ToolError):
    """Retain publication uncertainty and attempts even when no search result is promoted."""

    operation: Literal["reverse_frame"] = "reverse_frame"
    backend: Literal["serper"] = "serper"
    query: FrameQuery | None = None
    publication: FramePublication
    execution: SearchExecution
    factual_success: Literal[False] = False
