"""Quality improvement tools — refine, feedback, factcheck."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import get_config
from ..errors import make_tool_error
from ..runner import run_cli
from ..types import ProjectId, RefinePhase

logger = logging.getLogger(__name__)
quality_server = FastMCP("quality")


@quality_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_refine(
    project_id: ProjectId,
    phase: Annotated[RefinePhase, Field(description="Which phase to refine")],
) -> dict:
    """Refine a pipeline step's output for better quality.

    Args:
        project_id: Target project.
        phase: Script refinement.

    Returns:
        Dict with success status and refinement details.
    """
    try:
        result = await run_cli(
            "refine", project_id, "--phase", phase,
            "--projects-dir", str(get_config().resolved_projects_path),
        )
        return {
            "project_id": project_id,
            "phase": phase,
            "success": True,
            "duration_seconds": result.duration_seconds,
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)


@quality_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_feedback(
    project_id: ProjectId,
    feedback: Annotated[str, Field(description="Feedback text to add to the project")],
) -> dict:
    """Add feedback to a project for iterative improvement.

    Args:
        project_id: Target project.
        feedback: Free-text feedback to incorporate.

    Returns:
        Dict with confirmation.
    """
    try:
        result = await run_cli("feedback", project_id, "add", feedback)
        return {
            "project_id": project_id,
            "success": True,
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)


@quality_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def explainer_factcheck(
    project_id: ProjectId,
) -> dict:
    """Run fact-checking on the project's script content.

    Args:
        project_id: Project to fact-check.

    Returns:
        Dict with fact-check results.
    """
    try:
        result = await run_cli("factcheck", project_id)
        return {
            "project_id": project_id,
            "success": True,
            "duration_seconds": result.duration_seconds,
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)
