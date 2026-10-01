"""Explicit source-bound joint audio/video inference without implicit submissions."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..media_perception import perceive_media
from ..models.media_perception import AVPerceptionFailure, AVPerceptionRequest, AVPerceptionResponse
from ..tracing import trace

media_perceive_server = FastMCP("media-perception")
_SCHEMA = TypeAdapter(AVPerceptionResponse | AVPerceptionFailure).json_schema()
_SCHEMA["type"] = "object"


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
