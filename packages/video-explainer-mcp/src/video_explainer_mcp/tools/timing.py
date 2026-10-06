"""Typed public narration/storyboard timing inspection and bounded repair."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.timing import TimingRequest, TimingResult
from ..storyboard_timing import manage_timing
from ..types import ProjectId

timing_server = FastMCP("timing")
_SCHEMA = TypeAdapter(TimingResult | ToolError).json_schema()
_SCHEMA["type"] = "object"


@timing_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
)
async def explainer_timing(
    project_id: ProjectId,
    request: Annotated[TimingRequest, Field(description="Inspect current timing or repair with the observed timing revision")],
) -> dict:
    """Inspect or repair existing narration-driven scene and animation timing.

    Args:
        project_id: Existing configured project with a managed approved plan.
        request: Inspect, or explicit repair CAS; no provider/alignment invocation.

    Returns:
        Current/stale/missing timing, source-bound manifest and affected/reused scenes,
        or a structured error. Native render verification remains separate.
    """
    try:
        return TimingResult.model_validate(manage_timing(project_id, request)).model_dump()
    except Exception as error:
        return make_tool_error(error)
