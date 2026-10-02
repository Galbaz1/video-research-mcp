"""One explicit local tutorial artifact tool with read-only dry-run defaults."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError
from ..models.video_note import VideoNoteRequest, VideoNoteResult
from ..tracing import trace
from ..video_note import create_note

video_note_server = FastMCP("video-note")
_SCHEMA = TypeAdapter(VideoNoteResult | ToolError).json_schema()
_SCHEMA["type"] = "object"


@video_note_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@trace(name="video_note_create", span_type="TOOL")
async def video_note_create(request: Annotated[VideoNoteRequest, Field(
    description="Exact local source SHA, ordered supplied steps and PDF destination; dry-run default. Optional AV inference needs its own explicit submission grant.")]) -> dict:
    """Create a source-linked illustrated tutorial PDF or validate a read-only dry plan.

    Actual generation retains exact source PNGs, page rasters and a manifest/receipt.
    Missing illustrations or AV inference preserve supplied text with warnings.
    Deterministic PDF checks do not establish factual or human review.

    Args:
        request: Exact original, source-absolute steps, destination and workflow grant.

    Returns:
        Dry-plan validation or committed PDF/lineage identities and performed checks.
    """
    return await create_note(request)
