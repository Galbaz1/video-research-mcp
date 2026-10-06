"""Public local correction lessons and fixed-case replay history."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..corrections import execute
from ..errors import ToolError, make_tool_error
from ..models.corrections import Request, Response
from ..tracing import trace

corrections_server = FastMCP("corrections")
_ADAPTER = TypeAdapter(Request)
_SCHEMA = TypeAdapter(Response | ToolError).json_schema()
_SCHEMA["type"] = "object"


@corrections_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                idempotentHint=False, openWorldHint=False),
)
@trace(name="correction_manage", span_type="TOOL")
async def correction_manage(
    request: Annotated[Request, Field(description="Canonical workspace/collection; record immutable reported correction, replay declared exact rule, list or export bounded history")],
) -> dict:
    """Retain correction lessons and evaluate fixed caller-supplied replay outcomes.

    Args:
        request: Explicit source identities, reported authority, revision and bounds.

    Returns:
        Typed durable history or a tool error. Rule pass is not verified truth;
        provider errors and abstention remain denominator outcomes. No inference.
    """
    try:
        return execute(_ADAPTER.validate_python(request))
    except Exception as error:
        return make_tool_error(error)
