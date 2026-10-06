"""Refinement tool: probe-gated phases and durable revision-bound feedback."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.refinement import FeedbackRequest, FeedbackResult
from ..refinement import manage_feedback
from ..types import ProjectId

refinement_server = FastMCP("refinement")
_SCHEMA = TypeAdapter(FeedbackResult | ToolError).json_schema()
_SCHEMA["type"] = "object"


@refinement_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
async def explainer_refinement(
    project_id: ProjectId,
    request: Annotated[FeedbackRequest, Field(
        description="capabilities, or add/show/apply/retry revision-bound feedback with a typed patch or a probed CLI phase")],
) -> dict:
    """Probe refine phases and add, show, apply or retry revision-bound feedback.

    Args:
        project_id: Existing configured project with a managed plan (planning.sqlite3).
        request: `capabilities` runs only the CLI's refine help. `add` binds feedback to
            the expected plan revision, scene digest, bound artifacts and, for visual
            feedback, exact render bytes and frame time. `apply`/`retry` consume one capped
            round: a typed scene patch creates the next draft plan revision; a CLI phase
            runs only when the probe lists it (script phase through the approved producer).

    Returns:
        The durable feedback record with target revision and every attempt's result, the
        feedback list, or the probe; or a structured error. Visual findings remain caller
        or model assertions; this tool neither watches renders nor claims generative success.
    """
    try:
        return await manage_feedback(project_id, request)
    except Exception as error:
        return make_tool_error(error)
