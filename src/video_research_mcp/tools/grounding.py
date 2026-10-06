"""Citation validation, explicit abstention and bounded frame escalation tool."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..grounding import ground
from ..models.grounding import GroundingRequest, GroundingResult
from ..tracing import trace

grounding_server = FastMCP("grounding")
_SCHEMA = TypeAdapter(GroundingResult | ToolError).json_schema()
_SCHEMA["type"] = "object"


@grounding_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                               idempotentHint=False, openWorldHint=True),
)
@trace(name="grounded_answer", span_type="TOOL")
async def grounded_answer(
    request: Annotated[GroundingRequest, Field(description="Corpus query, caller claims with citations, repair policy and optional bounded frame escalation")],
) -> dict:
    """Validate caller claims against exactly retrieved evidence or abstain explicitly.

    Args:
        request: Canonical corpus query, caller-asserted claims with citations,
            artifact verification budget and optional escalation source/limits.

    Returns:
        Per-claim support, rejected or traced repaired citations, missing
        evidence, retrieved evidence, escalation attempts with actual decoded
        times and crops, or a typed error. No answer text is generated.
    """
    try:
        parsed = GroundingRequest.model_validate(request)
        return GroundingResult.model_validate(await ground(parsed)).model_dump(mode="json")
    except Exception as error:
        value = make_tool_error(error)
        if isinstance(error, ValueError):  # Same refusal category as temporal_ocr._error.
            value["category"] = "SCHEMA_VALIDATION_FAILED"
        return value
