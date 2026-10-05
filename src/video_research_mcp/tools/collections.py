"""Local named collections, workspace recall and bounded owned-media lifecycle."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..collections import execute
from ..errors import ToolError, make_tool_error
from ..models.collections import Request, Response
from ..tracing import trace

collections_server = FastMCP("collections")
_ADAPTER = TypeAdapter(Request)
_SCHEMA = TypeAdapter(Response | ToolError).json_schema()
_SCHEMA["type"] = "object"


@collections_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                idempotentHint=False, openWorldHint=False),
)
@trace(name="collections_manage", span_type="TOOL")
async def collections_manage(
    request: Annotated[Request, Field(description="Explicit canonical index and workspace; configure/create/select/list/recall/health/attach/admit/pin/delete/prune")],
) -> dict:
    """Manage persistent local collections and recall existing evidence without inference.

    Args:
        request: Typed local operation with provenance, revision and finite bounds.

    Returns:
        A validated receipt, bounded prior-work evidence, partial cleanup liability,
        or a typed error. Selection is workspace context, not authentication.
    """
    try:
        result = execute(_ADAPTER.validate_python(request))
        return Response.model_validate(result).model_dump(mode="json")
    except Exception as error:
        result = make_tool_error(error)
        if isinstance(error, ValueError) and str(error).startswith("Quota rejects admission"):
            result.update(category="FILE_TOO_LARGE", retryable=False,
                          hint="Prune unreferenced owned media or reconcile cleanup liabilities before a new admission.")
        return result
