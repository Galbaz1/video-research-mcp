"""Bounded deterministic hard cuts, timestamped storyboards, similarity and extraction."""

import json
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError
from ..image_tool_results import image_blocks
from ..models.scene_assets import (
    AudioDedupRequest, AudioExportRequest, ClipSelectionRequest,
    FrameDedupRequest, SceneRequest, StoryboardRequest,
)
from ..models.scene_delivery import SourceAssetResponse
from ..native_media_results import native_error, native_operation
from ..tracing import trace

media_scenes_server = FastMCP("scene-assets")
_LOCAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                         idempotentHint=False, openWorldHint=False)
_SCHEMA = TypeAdapter(SourceAssetResponse | ToolError).json_schema()
_SCHEMA["type"] = "object"


async def _result(metadata, include_image=False):
    """Verify artifact bytes and preserve every evidence row in the finite JSON response."""
    if metadata.get("operation") == "timestamped_storyboard":
        await image_blocks(metadata, False)
        preview = {"artifacts": [metadata["artifact"]]}
    else:
        preview = metadata
    blocks, delivery = await image_blocks(preview, include_image)
    value = SourceAssetResponse(metadata=metadata, native_images=delivery).model_dump(mode="json")
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, allow_nan=False)), *blocks],
                          structured_content=value)


@media_scenes_server.tool(output_schema=_SCHEMA, annotations=_LOCAL)
@trace(name="video_detect_scenes", span_type="TOOL")
async def video_detect_scenes(
    request: Annotated[SceneRequest, Field(description="Exact local source, bounded window and explicit hard-cut threshold; no semantic scene claim")],
) -> CallToolResult:
    """Detect hard visual cuts and return contiguous intervals with actual source PTS.

    Args:
        request: Source revision, interval and cut limits.

    Returns:
        Complete boundary population and coverage or a structured local error.
    """
    try:
        from ..media_scenes import detect_scenes

        async with native_operation() as generated:
            metadata = await detect_scenes(request)
            generated.append(metadata)
            return await _result(metadata)
    except Exception as exc:
        return native_error(exc)


@media_scenes_server.tool(output_schema=_SCHEMA, annotations=_LOCAL)
@trace(name="video_storyboard", span_type="TOOL")
async def video_storyboard(
    request: Annotated[StoryboardRequest, Field(description="Exact local source, at most 120-second window and sixteen actual frame tiles with burned source timestamps")],
    include_image: Annotated[bool, Field(description="Emit the actual storyboard PNG within native byte limits")] = True,
) -> CallToolResult:
    """Create a measured source storyboard with literal absolute source-clock labels.

    Args:
        request: Source revision, interval and grid.
        include_image: Include bounded native storyboard bytes.

    Returns:
        Original PTS, labeled pixels, every frame artifact and exact export manifest.
    """
    try:
        from ..media_storyboard import create_storyboard

        async with native_operation() as generated:
            metadata = await create_storyboard(request)
            generated.append(metadata)
            return await _result(metadata, include_image)
    except Exception as exc:
        return native_error(exc)


@media_scenes_server.tool(output_schema=_SCHEMA, annotations=_LOCAL)
@trace(name="video_deduplicate_frames", span_type="TOOL")
async def video_deduplicate_frames(
    request: Annotated[FrameDedupRequest, Field(description="Every candidate source point and explicit greedy dHash Hamming threshold; visual similarity cannot establish identity")],
    include_image: Annotated[bool, Field(description="Include bounded native candidate frames; all decisions remain in text")] = False,
) -> CallToolResult:
    """Compare bounded source frames without dropping similar or failed candidates.

    Args:
        request: Source revision, candidate points and similarity threshold.
        include_image: Include bounded candidate PNGs.

    Returns:
        Every original candidate, representative, distance and exact frame provenance.
    """
    try:
        from ..media_frame_dedup import deduplicate_frames

        async with native_operation() as generated:
            metadata = await deduplicate_frames(request)
            generated.append(metadata)
            return await _result(metadata, include_image)
    except Exception as exc:
        return native_error(exc)


@media_scenes_server.tool(output_schema=_SCHEMA, annotations=_LOCAL)
@trace(name="audio_deduplicate", span_type="TOOL")
async def audio_deduplicate(
    request: Annotated[AudioDedupRequest, Field(description="All explicit source audio intervals, up to120 seconds aggregate, and lossy MFCC cosine threshold")],
) -> CallToolResult:
    """Compare local audio candidates while retaining silence, errors and uncertainty.

    Requires the optional audio extra and local FFmpeg. Similarity does not
    establish equal speech, speaker identity or permission to delete evidence.

    Args:
        request: Source revision, candidate intervals and similarity threshold.

    Returns:
        Full candidate denominator, PCM identities, MFCC decisions and limitations.
    """
    try:
        from ..audio_fingerprints import dedup_audio

        async with native_operation() as generated:
            metadata = await dedup_audio(request)
            generated.append(metadata)
            return await _result(metadata)
    except Exception as exc:
        return native_error(exc)


@media_scenes_server.tool(output_schema=_SCHEMA, annotations=_LOCAL)
@trace(name="audio_clip_export", span_type="TOOL")
async def audio_clip_export(
    request: Annotated[AudioExportRequest, Field(description="Exact local audio/video source; omitted endpoints select whole track within 240-second/8MiB WAV limits")],
) -> CallToolResult:
    """Export a whole or one-sided audio selection to a unique private 16kHz mono WAV.

    Originals and prior exports remain unchanged. Caller-selected output paths
    and overwriting are rejected. Use image_manifest_read for verified restart.

    Args:
        request: Source revision and optional half-open endpoints.

    Returns:
        Actual sample clocks, WAV/PCM hashes and durable manifest or a local error.
    """
    try:
        from ..audio_assets import export_audio

        async with native_operation() as generated:
            metadata = await export_audio(request)
            generated.append(metadata)
            return await _result(metadata)
    except Exception as exc:
        return native_error(exc)


@media_scenes_server.tool(output_schema=_SCHEMA, annotations=_LOCAL)
@trace(name="video_clip_select", span_type="TOOL")
async def video_clip_select(
    request: Annotated[ClipSelectionRequest, Field(description="Exact source video; omitted endpoints resolve from source under existing 60-second/256-frame/8MiB clip gates")],
) -> CallToolResult:
    """Export a whole or one-sided bounded video selection using measured clip timing.

    Args:
        request: Source revision, optional endpoints and explicit audio inclusion.

    Returns:
        Resolved requested interval, actual decoded source/output clocks and manifest.
    """
    try:
        from ..media_clip_export import export_selected_clip

        async with native_operation() as generated:
            metadata = await export_selected_clip(request)
            generated.append(metadata)
            return await _result(metadata)
    except Exception as exc:
        return native_error(exc)
