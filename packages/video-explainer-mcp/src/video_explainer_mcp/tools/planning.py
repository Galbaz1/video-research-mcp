"""Noninteractive source-accounted video plan creation, revision and approval."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..models.planning import PlanRequest
from ..planning import apply_plan
from ..types import ProjectId

planning_server = FastMCP("planning")


@planning_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_plan(
    project_id: ProjectId,
    request: Annotated[PlanRequest, Field(description="Create/show/revise/approve with expected revision")],
) -> dict:
    """Manage a complete editorial plan through MCP without a stdin review session.

    Args:
        project_id: Existing configured project containing an evidence packet.
        request: Typed action and complete replacement content for create/revise.

    Returns:
        Current plan, source integrity, approval revision and actual artifact bindings.
    """
    try:
        return apply_plan(project_id, request)
    except Exception as exc:
        return make_tool_error(exc)
