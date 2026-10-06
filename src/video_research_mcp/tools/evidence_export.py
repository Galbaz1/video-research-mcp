"""Pure local exports over canonical evidence; Root mounts this sub-server."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..evidence_export import export
from ..models.evidence_export import Request, Response
from ..tracing import trace

evidence_export_server = FastMCP("evidence-export")
_SCHEMA = TypeAdapter(Response | ToolError).json_schema()
_SCHEMA["type"] = "object"


@evidence_export_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
)
@trace(name="evidence_export", span_type="TOOL")
async def evidence_export(
    request: Annotated[Request, Field(description="Canonical corpus/wiki/collection selection or explicit fixture records; new local output directory and finite HTML/Markdown/JSON byte bounds")],
) -> dict:
    """Export escaped, standalone evidence and retain exact provenance labels.

    Args:
        request: Local selection, exclusive output path, formats and frame policy.

    Returns:
        Readback-verified artifacts, named frame issues, provenance and zero
        provider calls, or a typed error. Collection recall retains canonical LRU use.
    """
    try:
        parsed = Request.model_validate(request)
        return await export(parsed)
    except Exception as error:
        return make_tool_error(error)
