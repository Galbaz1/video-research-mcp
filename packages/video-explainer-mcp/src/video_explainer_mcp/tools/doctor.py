"""Public local renderer diagnostics without provider, install or render activity."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..prereqs import doctor
from ..types import ProjectId

doctor_server = FastMCP("doctor")


@doctor_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def explainer_doctor(
    project_id: Annotated[
        ProjectId | None,
        Field(description="Optional project to inspect for the selected render route"),
    ] = None,
) -> dict:
    """Inspect exact renderer entry, Node/media/browser and generation prerequisites.

    Args:
        project_id: Optional existing project with configured storyboard paths.

    Returns:
        Technical readiness and unsupported capabilities; provider access remains unchecked.
    """
    try:
        return (await doctor(project_id)).model_dump(mode="json")
    except Exception as exc:
        return make_tool_error(exc)
