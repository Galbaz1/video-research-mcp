"""Public bounded local aspect/caption variants; Root owns registration."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..models.variants import VariantRequest
from ..types import ProjectId
from ..variants import create_variants

variants_server = FastMCP("variants")


@variants_server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
async def explainer_variants(
    project_id: ProjectId,
    request: Annotated[VariantRequest, Field(description="Completed current render, contiguous approved scenes, exact local TTF and source words/SRT; bounded aspect batch")],
) -> dict:
    """Produce local shorts/aspect variants without changing approved claims or timing.

    Args:
        project_id: Existing configured project with approved bound artifacts.
        request: Exact source render/audio/caption/font and selected scene/aspect population.

    Returns:
        Durable individual outcomes and configuration/output hashes, or a structured
        refusal. Source-only tests do not qualify native pixels or factual semantics.
    """
    try:
        return await create_variants(project_id, VariantRequest.model_validate(request))
    except Exception as error:
        result = make_tool_error(error)
        if getattr(error, "__notes__", None):
            result["cleanup_liability"] = error.__notes__
        return result
