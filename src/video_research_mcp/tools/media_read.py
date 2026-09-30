"""Inspectable local images and decoded video points/windows without provider inference."""

import re
from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field, FiniteFloat, StrictInt, TypeAdapter

from ..errors import ToolError
from ..models.native_media import CropBox, FrameTranscript, NativeMediaResult, TranscriptMatch
from ..native_media_results import native_error, native_operation, native_result
from ..tracing import trace

media_read_server = FastMCP("media-read")
_OUTPUT_SCHEMA = TypeAdapter(NativeMediaResult | ToolError).json_schema()
_OUTPUT_SCHEMA["type"] = "object"
_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)
_FILE = Field(min_length=1, max_length=4096, description="Regular local media path within LOCAL_FILE_ACCESS_ROOT")
_PIXELS = Field(ge=1, le=1_000_000, description="Maximum output pixels per frame")
_IMAGE = Field(description="Include bounded native PNG blocks; false returns text metadata")


@media_read_server.tool(output_schema=_OUTPUT_SCHEMA, annotations=_ANNOTATIONS)
@trace(name="media_info", span_type="TOOL")
async def media_info(file_path: Annotated[str, _FILE]) -> CallToolResult:
    """Inspect exact local media bytes, stream metadata, rotation, audio and chapters.

    Uses independently installed FFprobe and a bounded private stable snapshot.
    This performs no provider upload and does not establish watched coverage.

    Args:
        file_path: Original local video, image or audio.

    Returns:
        Typed source metadata or a redacted structured error.
    """
    from ..media_probe import inspect_media

    try:
        return await native_result({"source": await inspect_media(file_path)}, False)
    except Exception as exc:
        return native_error(exc)


@media_read_server.tool(output_schema=_OUTPUT_SCHEMA, annotations=_ANNOTATIONS)
@trace(name="image_read", span_type="TOOL")
async def image_read(
    file_path: Annotated[str, _FILE],
    max_pixels: Annotated[StrictInt, _PIXELS] = 1_000_000,
    include_image: Annotated[bool, _IMAGE] = True,
) -> CallToolResult:
    """Return a bounded local still image as inspectable PNG and exact source metadata.

    Animated inputs expose one still with an explicit limitation. Native output
    may be processed by the host's model; this server invokes no model or upload.

    Args:
        file_path: Original local PNG, JPEG, WebP, BMP, GIF or TIFF.
        max_pixels: Output resolution ceiling.
        include_image: Emit native image blocks or text metadata.

    Returns:
        Extracted image provenance and native/text content, or a structured error.
    """
    from ..media_image_read import read_image

    try:
        async with native_operation() as generated:
            metadata = await read_image(file_path, max_pixels=max_pixels)
            generated.append(metadata)
            return await native_result(metadata, include_image)
    except Exception as exc:
        return native_error(exc)


@media_read_server.tool(output_schema=_OUTPUT_SCHEMA, annotations=_ANNOTATIONS)
@trace(name="video_frame", span_type="TOOL")
async def video_frame(
    file_path: Annotated[str, _FILE],
    time_seconds: Annotated[FiniteFloat, Field(ge=0, description="Time relative to measured container presentation origin")],
    selection: Annotated[Literal["precise", "keyframe"], Field(description="Decoded point or explicitly approximate indexed keyframe")] = "precise",
    max_pixels: Annotated[StrictInt, _PIXELS] = 1_000_000,
    crop_box: Annotated[CropBox | None, Field(description="x,y,width,height in rotated source pixel grid; explicit SAR policy; crop before scale")] = None,
    include_image: Annotated[bool, _IMAGE] = True,
) -> CallToolResult:
    """Retrieve a source frame with requested time, original decoded PTS and actual delta.

    Times are relative to the measured container presentation origin. Precise
    selection returns the first decoded frame at or after the request.
    Keyframe selection reports its measured approximation and selection method.

    Args:
        file_path: Original local video.
        time_seconds: Requested source-relative time.
        selection: Precise decode or approximate keyframe retrieval.
        max_pixels: Output resolution ceiling.
        crop_box: Optional region in display coordinates.
        include_image: Emit native image blocks or text metadata.

    Returns:
        One measured source frame or a redacted structured error.
    """
    from ..media_frames import frame_at

    try:
        async with native_operation() as generated:
            metadata = await frame_at(file_path, time_seconds=time_seconds, max_pixels=max_pixels,
                                      crop_box=crop_box, selection=selection)
            generated.append(metadata)
            return await native_result(metadata, include_image)
    except Exception as exc:
        return native_error(exc)


@media_read_server.tool(output_schema=_OUTPUT_SCHEMA, annotations=_ANNOTATIONS)
@trace(name="video_frames", span_type="TOOL")
async def video_frames(
    file_path: Annotated[str, _FILE],
    start_seconds: Annotated[FiniteFloat, Field(ge=0, description="Inclusive source-relative window start")] = 0,
    end_seconds: Annotated[FiniteFloat | None, Field(ge=0, description="Exclusive window end; defaults to measured video presentation end")] = None,
    mode: Annotated[Literal["frames", "sheet", "filmstrip", "scenes", "keyframes"], Field(description="Uniform stills/grid/vertical strip, scene changes, or keyframes")] = "sheet",
    fps: Annotated[FiniteFloat, Field(gt=0, le=30, description="Maximum selected rate for uniform frames")] = 1,
    max_frames: Annotated[StrictInt, Field(ge=1, le=48, description="Maximum returned frames; cap stop remains explicit")] = 24,
    max_pixels: Annotated[StrictInt, _PIXELS] = 250_000,
    crop_box: Annotated[CropBox | None, Field(description="x,y,width,height in rotated source pixel grid; explicit SAR policy; crop before scale")] = None,
    include_image: Annotated[bool, _IMAGE] = True,
) -> CallToolResult:
    """Inspect a bounded burst/window or timestamped contact sheet without a watched claim.

    Dense filmstrips require a narrow window and explicit FPS. Selection retains
    changed text; it performs no similarity pruning or OCR. Sheet tiles carry
    actual source times/digests. Scene/keyframe sampling may miss short events.

    Args:
        file_path: Original local video.
        start_seconds: Window start.
        end_seconds: Window end.
        mode: Individual frames, grid, vertical strip, scenes or keyframes.
        fps: Uniform maximum selection rate.
        max_frames: Output frame ceiling.
        max_pixels: Resolution ceiling per frame.
        crop_box: Optional display-pixel crop.
        include_image: Emit native image blocks or text metadata.

    Returns:
        Actual returned points, limits, artifacts and completeness, or a structured error.
    """
    from ..media_frame_views import contact_sheet
    from ..media_frames import sample_frames

    try:
        selection = {"scenes": "scene", "keyframes": "keyframe"}.get(mode, "uniform")
        async with native_operation() as generated:
            metadata = await sample_frames(file_path, start_seconds=start_seconds,
                                           end_seconds=end_seconds, fps=fps, max_frames=max_frames,
                                           max_pixels=max_pixels, crop_box=crop_box, selection=selection)
            generated.append(metadata)
            if mode != "frames":
                metadata = await contact_sheet(metadata, columns=1 if mode == "filmstrip" else 4)
                generated.append(metadata)
            return await native_result(metadata, include_image)
    except Exception as exc:
        return native_error(exc)


@media_read_server.tool(output_schema=_OUTPUT_SCHEMA, annotations=_ANNOTATIONS)
@trace(name="video_frame_by_query", span_type="TOOL")
async def video_frame_by_query(
    file_path: Annotated[str, _FILE],
    query: Annotated[str, Field(min_length=1, max_length=1024, description="Lexical query matched against supplied transcript tokens")],
    transcript: Annotated[FrameTranscript, Field(description="Source SHA256 and bounded timestamped segments; supplied speech remains unverified")],
    max_pixels: Annotated[StrictInt, _PIXELS] = 1_000_000,
    include_image: Annotated[bool, _IMAGE] = True,
) -> CallToolResult:
    """Select a frame by lexical transcript match, requiring the exact video digest.

    Segment times use the container-relative presentation clock. Ties choose the
    earliest segment. A zero-token match abstains. The supplied transcript remains
    unverified; the extracted frame carries measured PTS.

    Args:
        file_path: Original local video.
        query: Text tokens to match.
        transcript: Caller-supplied transcript bound to source bytes.
        max_pixels: Output resolution ceiling.
        include_image: Emit native image blocks or text metadata.

    Returns:
        Matched segment and exact decoded frame provenance, or a structured error.
    """
    from ..media_frames import frame_at

    try:
        transcript = FrameTranscript.model_validate(transcript)
        tokens = sorted(set(re.findall(r"\w+", query.casefold())))
        choices = []
        for index, segment in enumerate(transcript.segments):
            matched = sorted(set(tokens) & set(re.findall(r"\w+", segment.text.casefold())))
            choices.append((-len(matched), segment.start_seconds, index, matched))
        score, _, index, matched = min(choices)
        if score == 0:
            raise ValueError("No lexical transcript match; no frame selected")
        async with native_operation() as generated:
            metadata = await frame_at(file_path, time_seconds=transcript.segments[index].start_seconds,
                                      max_pixels=max_pixels, expected_source_sha256=transcript.source_sha256)
            generated.append(metadata)
            metadata["transcript_match"] = TranscriptMatch(
                segment_index=index, segment=transcript.segments[index], matched_tokens=matched,
                query_tokens=tokens,
            ).model_dump(mode="json")
            return await native_result(metadata, include_image)
    except Exception as exc:
        return native_error(exc)
