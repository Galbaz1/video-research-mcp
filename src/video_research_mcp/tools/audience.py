"""Typed local audience sample import, exact comment retrieval and transparent metrics."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..audience import execute
from ..errors import ToolError, make_tool_error
from ..models.audience import Request, Response
from ..tracing import trace

audience_server = FastMCP("audience")
_REQUEST = TypeAdapter(Request)
_SCHEMA = TypeAdapter(Response | ToolError).json_schema()
_SCHEMA["type"] = "object"


@audience_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
@trace(name="audience_manage", span_type="TOOL")
async def audience_manage(
    request: Annotated[Request, Field(description="Explicit canonical comments collection; import exact supplied sample, search immutable samples, or analyze a fixed cohort/timezone")],
) -> dict:
    """Persist comments and return evidence-linked deterministic audience heuristics.

    Args:
        request: Typed local operation, immutable sample identities and finite bounds.

    Returns:
        Validated provenance, exact quotes or transparent metrics, or a structured error.
        No provider or YouTube acquisition is performed by this tool.
    """
    try:
        return execute(_REQUEST.validate_python(request))
    except Exception as error:
        return make_tool_error(error)
