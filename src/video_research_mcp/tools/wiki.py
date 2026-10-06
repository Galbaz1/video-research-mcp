"""Versioned attributed wiki pages and context-first questions on the canonical index."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.wiki import Request, Response
from ..tracing import trace
from ..wiki import ask, read
from ..wiki_store import remove_source, write

wiki_server = FastMCP("wiki")
_ADAPTER = TypeAdapter(Request)
_SCHEMA = TypeAdapter(Response | ToolError).json_schema()
_SCHEMA["type"] = "object"


@wiki_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                idempotentHint=False, openWorldHint=True),
)
@trace(name="wiki_manage", span_type="TOOL")
async def wiki_manage(
    request: Annotated[Request, Field(description="Explicit canonical concept/evidence identities; write/get/history/list/toc/search/remove_source/ask, with prose disabled by default")],
) -> dict:
    """Preserve evidence-linked page history and expose the basis of wiki synthesis.

    Args:
        request: Typed local operation, source identity, revision pins and finite bounds.

    Returns:
        Immutable page receipts, retrieved attributed evidence/context, an explicitly
        labeled synthesis, or a typed error. Identity selection never implies entity merging.
    """
    try:
        parsed = _ADAPTER.validate_python(request)
        if parsed.action == "ask":
            result = await ask(parsed)
        elif parsed.action == "write":
            result = write(parsed)
        elif parsed.action == "remove_source":
            result = remove_source(parsed)
        else:
            result = read(parsed)
        return Response.model_validate(result).model_dump(mode="json")
    except Exception as error:
        return make_tool_error(error)
