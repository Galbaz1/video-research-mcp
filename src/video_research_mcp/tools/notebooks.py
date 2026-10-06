"""Local notebooks over the canonical corpus: import, scoped query, cited notes, export and status."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.notebooks import Request, Response
from ..notebooks import execute
from ..tracing import trace

notebooks_server = FastMCP("notebooks")
_REQUEST = TypeAdapter(Request)
_SCHEMA = TypeAdapter(Response | ToolError).json_schema()
_SCHEMA["type"] = "object"


@notebooks_server.tool(output_schema=_SCHEMA, annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False))
@trace(name="notebook_manage", span_type="TOOL")
async def notebook_manage(
    request: Annotated[Request, Field(description="Explicit canonical index, workspace and notebook; import/query/note/export/status")],
) -> dict:
    """Keep local notebooks whose notes cite exact canonical observation passages.

    Args:
        request: Typed local operation. Import keeps the supplied notebook ID and revision; notes
            append a revision with citations bound to exact observation versions; queries search
            only the notebook's own collections and notes; export returns the document and a
            Markdown report whose appendix quotes each supporting passage.

    Returns:
        A structured receipt or a structured error. No model, provider, network or external
        service is used, and no credential is read, stored or exported.
    """
    try:
        return execute(_REQUEST.validate_python(request))
    except Exception as error:
        return make_tool_error(error)
