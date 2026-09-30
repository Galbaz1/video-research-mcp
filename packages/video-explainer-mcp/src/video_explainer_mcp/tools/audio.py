"""Audio tools — sound effects and background music."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..runner import run_cli
from ..types import ProjectId, SoundAction

logger = logging.getLogger(__name__)
audio_server = FastMCP("audio")


@audio_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_sound(
    project_id: ProjectId,
    action: Annotated[SoundAction, Field(description="'analyze' scenes or 'generate' sound effects")],
) -> dict:
    """Analyze scenes for sound cues or generate sound effects.

    Args:
        project_id: Target project.
        action: Either 'analyze' (identify sound opportunities) or
                'generate' (create sound effects).

    Returns:
        Dict with action results.
    """
    try:
        result = await run_cli("sound", project_id, action)
        return {
            "project_id": project_id,
            "action": action,
            "success": True,
            "duration_seconds": result.duration_seconds,
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)


@audio_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_music(
    project_id: ProjectId,
) -> dict:
    """Generate background music for the video.

    Args:
        project_id: Target project.

    Returns:
        Dict with music generation results.
    """
    try:
        result = await run_cli("music", project_id, "generate")
        return {
            "project_id": project_id,
            "success": True,
            "duration_seconds": result.duration_seconds,
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)
