"""Explicit source-bound joint audio/video inference without implicit submissions."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..av_events import analyze_music, caption_events, count_events, ground_events
from ..media_perception import perceive_media
from ..models.av_events import (
    AnalyzeMusicRequest, AVEventsFailure, AVEventsResponse, CaptionEventsRequest,
    CountEventsRequest, GroundEventsRequest,
)
from ..models.media_perception import AVPerceptionFailure, AVPerceptionRequest, AVPerceptionResponse
from ..tracing import trace

media_perceive_server = FastMCP("media-perception")
_SCHEMA = TypeAdapter(AVPerceptionResponse | AVPerceptionFailure).json_schema()
_SCHEMA["type"] = "object"
_EVENTS_SCHEMA = TypeAdapter(AVEventsResponse | AVEventsFailure).json_schema()
_EVENTS_SCHEMA["type"] = "object"


@media_perceive_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="media_perceive", span_type="TOOL")
async def media_perceive(request: Annotated[AVPerceptionRequest, Field(
    description="Exact local media, bounded ordered windows and explicit Gemini submission grant; dry plans are the default")]) -> dict:
    """Infer separate spoken and visible source evidence across bounded AV windows.

    Local dry plans prepare exact sampled frames and decoded PCM with no provider
    calls. Submission requires the exact workflow grant and configured account.
    Model intervals map back to source seconds; sampled images leave visual gaps.

    Args:
        request: Source digest, instruction, local selection and execution limits.

    Returns:
        Source/window lineage, inferred evidence and accounting or a structured error.
    """
    return await perceive_media(request)


@media_perceive_server.tool(output_schema=_EVENTS_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="media_caption_events", span_type="TOOL")
async def media_caption_events(request: Annotated[CaptionEventsRequest, Field(
    description="Exact local AV selection and source-supported event captions; dry preparation by default")]) -> dict:
    """Caption timed audio, visual and combined occurrences with submitted support.

    Args:
        request: Exact source, instruction, selection and explicit submission grant.

    Returns:
        Inferred occurrences, measured source windows and execution accounting.
    """
    return await caption_events(request)


@media_perceive_server.tool(output_schema=_EVENTS_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="media_count_events", span_type="TOOL")
async def media_count_events(request: Annotated[CountEventsRequest, Field(
    description="Target event and exact local selection; count is derived from retained supported occurrence records")]) -> dict:
    """Count retained inferred occurrences of a target in bounded source windows.

    Counts concern admitted records in submitted evidence. Overlapping records
    remain distinct, and sampled frames leave gaps where events may be missed.

    Args:
        request: Target, exact source, selection and explicit submission grant.

    Returns:
        Supported records, derived count or partial count, abstentions and usage.
    """
    return await count_events(request)


@media_perceive_server.tool(output_schema=_EVENTS_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="media_ground_events", span_type="TOOL")
async def media_ground_events(request: Annotated[GroundEventsRequest, Field(
    description="Query with positive top_k; retain all admitted records and disclose selected and truncated matches")]) -> dict:
    """Ground a query in source-supported intervals with uncalibrated scores.

    Args:
        request: Query, match limit, exact source and explicit submission grant.

    Returns:
        Retained evidence, selected matches and the complete truncation population.
    """
    return await ground_events(request)


@media_perceive_server.tool(output_schema=_EVENTS_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="media_analyze_music", span_type="TOOL")
async def media_analyze_music(request: Annotated[AnalyzeMusicRequest, Field(
    description="Audio-only analysis of an exact local source; timed structure and inferred musical properties")]) -> dict:
    """Infer timed musical sections and properties from actual decoded audio.

    Instruments, mood, tags, tempo, key and meter remain model interpretations.
    Submitted PCM clocks and hashes identify the evidence for each section.

    Args:
        request: Exact audio or video source, selection and submission grant.

    Returns:
        Inferred musical sections, measured audio windows and abstention accounting.
    """
    return await analyze_music(request)
