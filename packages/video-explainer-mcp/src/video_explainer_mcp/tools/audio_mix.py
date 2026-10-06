"""Typed offline mix of licensed local narration, music and sound effects."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..audio_mix import mix_audio
from ..errors import make_tool_error
from ..models.audio_mix import AudioMixRequest
from ..types import ProjectId

audio_mix_server = FastMCP("audio_mix")


@audio_mix_server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
async def explainer_audio_mix(
    project_id: ProjectId,
    request: Annotated[AudioMixRequest, Field(description="Local narration/music/SFX cues with pinned bytes, pinned rights, levels and fades")],
) -> dict:
    """Mix licensed local audio cues into one WAV with music ducked under narration.

    Args:
        project_id: Existing project containing the audio files and their rights records.
        request: Cue intervals, gains, fades and ducking; commercial=true requires commercial rights.

    Returns:
        Output receipt with sources, rights, recipe, cache key and signal QA (peak, clipping,
        duration, edges), or a structured error. Listening quality stays UNQUALIFIED; nothing is
        generated, downloaded or sent to a provider.
    """
    try:
        return await mix_audio(project_id, request)
    except Exception as error:
        result = make_tool_error(error)
        if getattr(error, "__notes__", None):
            result["cleanup_liability"] = error.__notes__
        return result
