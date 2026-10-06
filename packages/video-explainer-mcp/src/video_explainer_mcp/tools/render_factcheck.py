"""Render fact-check tool: source support and rendered text/audio/frame additions."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.render_factcheck import RenderFactcheckRequest, RenderFactcheckResult
from ..render_factcheck import render_factcheck
from ..types import ProjectId

render_factcheck_server = FastMCP("render_factcheck")
_SCHEMA = TypeAdapter(RenderFactcheckResult | ToolError).json_schema()
_SCHEMA["type"] = "object"


@render_factcheck_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
async def explainer_render_factcheck(
    project_id: ProjectId,
    request: Annotated[RenderFactcheckRequest, Field(
        description="Asserted claim judgments, already-recovered rendered caption/ASR/OCR text and an optional render receipt")],
) -> dict:
    """Check packet claim support and reconcile rendered additions against approved claims.

    Args:
        project_id: Existing configured project with input/evidence-packet.json.
        request: Judgments are recorded beside verified support; observations are matched
            independently of their declared claim IDs. No model/OCR/ASR/render runs here.

    Returns:
        Per-claim verified support, asserted judgment and corrections; per-observation
        additions; separate factual support, narration clarity, legibility, synchronization
        and render completion dimensions; or a structured error when inputs cannot load.
    """
    try:
        return render_factcheck(project_id, request)
    except Exception as error:
        return make_tool_error(error)
