"""Instruction-driven deterministic evidence synthesis; Root owns mounting."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.synthesis import Request, Response
from ..synthesis import synthesize
from ..tracing import trace

synthesis_server = FastMCP("synthesis")
_ADAPTER = TypeAdapter(Request)
_SCHEMA = TypeAdapter(Response | ToolError).json_schema(mode="serialization")
_SCHEMA["type"] = "object"


@synthesis_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
@trace(name="synthesis_manage", span_type="TOOL")
async def synthesis_manage(
    request: Annotated[Request, Field(description="Instruction and local canonical corpus/wiki selection or labeled fixtures; cross_video quotations, duration-bounded heuristic chapters, or source-separated bug_report")],
) -> dict:
    """Synthesize bounded source evidence without a provider or generated factual prose.

    Args:
        request: Typed action, instruction, source pins, output budget and action scope.

    Returns:
        Exact quotations/citations, labeled chapter heuristics, or reported bug
        evidence separated from caller-inferred causes. Gaps cause abstention;
        source observations and frame references are not independently verified.
    """
    try:
        parsed = _ADAPTER.validate_python(request)
        return await synthesize(parsed)
    except Exception as error:
        return make_tool_error(error)
