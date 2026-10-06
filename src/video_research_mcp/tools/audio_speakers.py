"""Local anonymous speaker turns, explicit relabels, samples, registry listing and enrollment."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.speakers import EnrollRequest, SpeakersRequest, SpeakersResult
from ..speakers import enroll, run_action
from ..tracing import trace

audio_speakers_server = FastMCP("audio-speakers")
_SCHEMA = TypeAdapter(SpeakersResult | ToolError).json_schema()
_SCHEMA["type"] = "object"
_SPEAKERS = TypeAdapter(SpeakersRequest)


@audio_speakers_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
    ),
)
@trace(name="audio_speakers", span_type="TOOL")
async def audio_speakers(
    request: Annotated[SpeakersRequest, Field(
        description="action diarize|relabel|samples|registry with SHA-bound inputs; writes only a new output directory",
    )],
) -> dict:
    """Diarize, relabel, export samples or list the registry without persisting voiceprints.

    Diarize returns anonymous SPEAKER_NN turns on the source clock with a
    cluster-similarity scalar that is not an identity or probability. Relabel
    writes a new record from explicit assignments; registry matches are ranked
    suggestions only. Execution requires an explicit runtime descriptor and
    ``dry_run=false``; the optional worker runs in its own interpreter.

    Args:
        request: One discriminated speaker action request.

    Returns:
        Planned or complete result with records and artifacts, or a ToolError.
    """
    try:
        return await run_action(_SPEAKERS.validate_python(request))
    except Exception as error:
        return make_tool_error(error)


@audio_speakers_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False,
    ),
)
@trace(name="audio_speaker_enroll", span_type="TOOL")
async def audio_speaker_enroll(
    request: Annotated[EnrollRequest, Field(
        description="Explicit speaker_name, caller consent statement, registry path, runtime descriptor and source",
    )],
) -> dict:
    """Persist one model-keyed voiceprint for an explicitly supplied speaker name.

    Names are never inferred. The entry is keyed by (name, embedding-model
    SHA-256); replacing an existing entry requires ``replace_existing``. No
    audio is stored in the registry.

    Args:
        request: Name, consent statement, registry, runtime and audio source.

    Returns:
        Planned or complete enrollment without the voiceprint, or a ToolError.
    """
    try:
        return await enroll(EnrollRequest.model_validate(request))
    except Exception as error:
        return make_tool_error(error)
