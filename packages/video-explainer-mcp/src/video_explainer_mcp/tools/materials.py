"""Typed local material assembly tools."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..materials_render import assemble_materials
from ..models.materials import MaterialsRequest
from ..types import ProjectId

materials_server = FastMCP("materials")


@materials_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_materials_assemble(
    project_id: ProjectId,
    request: Annotated[MaterialsRequest, Field(description="Ordered scene/script bindings, local source and rights pins")],
) -> dict:
    """Assemble exact local visuals with a retained fitted recipe and full MP4 qualification.

    Args:
        project_id: Existing project receiving the durable material manifest.
        request: Caller ordered inputs and separate rights declarations.

    Returns:
        Exact qualified output, provenance and recipe, or a structured error.
    """
    try:
        return await assemble_materials(project_id, request)
    except Exception as error:
        result = make_tool_error(error)
        if getattr(error, "__notes__", None):
            result["cleanup_liability"] = error.__notes__
        return result
