"""Captions-first transcript extraction and explicitly selected optional ASR."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.transcript import TranscriptFailure, TranscriptRequest, TranscriptResult
from ..tracing import trace
from ..transcript import transcribe


audio_transcribe_server = FastMCP("audio-transcription")
_SCHEMA = TypeAdapter(TranscriptResult | TranscriptFailure | ToolError).json_schema()
_SCHEMA["type"] = "object"


@audio_transcribe_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True,
    ),
)
@trace(name="audio_transcribe", span_type="TOOL")
async def audio_transcribe(
    request: Annotated[TranscriptRequest, Field(
        description="Exact local source, associated captions, source range and absent output directory; optional ASR requires explicit backend and submission authority",
    )],
) -> dict:
    """Extract exact caption intervals or infer speech through an explicit backend.

    Supplied cue and word times remain source assertions. Model-derived words
    and speaker labels remain inference. Caption selection precedes ASR;
    local-only selection forbids cloud requests. Readback requires the retained
    receipt digest and exact source identity. No local model is installed.

    Args:
        request: Source digest, caption policy, audio limits and export selection.

    Returns:
        Transcript records, provenance, attempts, exports and restart receipt,
        or a structured error retaining available partial execution evidence.
    """
    try:
        return await transcribe(request)
    except Exception as error:
        return make_tool_error(error)
