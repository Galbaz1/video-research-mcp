"""Typed local and explicitly configured stock material tools."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..materials_remote import download_material, search_materials
from ..materials_render import assemble_materials
from ..models.materials import MaterialsRequest, StockDownload, StockSearch
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


@materials_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def explainer_materials_search(
    project_id: ProjectId,
    request: Annotated[StockSearch, Field(description="Pinned source configuration and finite stock query")],
) -> dict:
    """Search explicitly authorized stock metadata; results grant no asset rights.

    Args:
        project_id: Existing project containing the source permission record.
        request: Source configuration, caller and finite page range.

    Returns:
        Illustrative candidates or an explicit retained partial page failure.
    """
    try:
        return await search_materials(project_id, request)
    except Exception as error:
        result = make_tool_error(error)
        if getattr(error, "__notes__", None):
            result["cleanup_liability"] = error.__notes__
        return result


@materials_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_materials_download(
    project_id: ProjectId,
    request: Annotated[StockDownload, Field(description="Exact stock rendition, pinned rights and explicit source authority")],
) -> dict:
    """Download an exact authorized rendition into a durable illustrative material receipt.

    Args:
        project_id: Existing project receiving the exact downloaded bytes.
        request: Configured source, caller authority, asset rights, URL and hash.

    Returns:
        Exact acquired source receipt, without claiming rendered or factual success.
    """
    try:
        return await download_material(project_id, request)
    except Exception as error:
        result = make_tool_error(error)
        if getattr(error, "__notes__", None):
            result["cleanup_liability"] = error.__notes__
        return result
