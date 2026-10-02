"""Sound, music and measured project-bound narration tools."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..models.narration import NarrationRequest
from ..plan_artifacts import require_binding
from ..planning import require_approved, save_plan
from ..planning_production import production_transaction
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


@audio_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_narration(
    project_id: ProjectId,
    request: Annotated[NarrationRequest, Field(description="Measure approved narration, preview a voice, or admit contained custom WAV")],
) -> dict:
    """Produce measured WAV and timing receipts from the current approved script.

    Args:
        project_id: Existing configured project with an approved bound script.
        request: Explicit audio action, provider, voice and performance settings.

    Returns:
        Measured audio and alignment receipts, or retained sentence failures.
        Synthetic/provider timing does not verify spoken-content correctness.
    """
    try:
        from ..narration_run import produce_narration

        with production_transaction(project_id) as (project, connection, state):
            if state is None:
                raise ValueError("Create and approve a managed plan and bind its script before narration")
            script = require_binding(project, state, "script")
            result = await produce_narration(project, state, script, request)
            if result["success"]:
                require_approved(project, state)
                require_binding(project, state, "script")
                if request.action in {"generate", "custom"}:
                    state["bindings"]["narration"] = result["binding"]
                    require_binding(project, state, "narration")
                save_plan(connection, state)
            return {"project_id": project_id, **result, "factual_success": False,
                    "visual_audio_semantics": "not_verified"}
    except Exception as exc:
        return make_tool_error(exc)
