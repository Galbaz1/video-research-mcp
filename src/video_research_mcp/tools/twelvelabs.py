"""Explicit optional TwelveLabs REST workflows with provider-attributed observations."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..models.twelvelabs import TwelveLabsError, TwelveLabsRequest, TwelveLabsResponse
from ..tracing import trace
from ..twelvelabs_client import execute

twelvelabs_server = FastMCP("twelvelabs")
_SCHEMA = TypeAdapter(TwelveLabsResponse | TwelveLabsError).json_schema()
_SCHEMA["type"] = "object"


@twelvelabs_server.tool(output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@trace(name="twelvelabs_call", span_type="TOOL")
async def twelvelabs_call(
    request: Annotated[TwelveLabsRequest, Field(description="One current hosted REST operation with explicit IDs, parameters, BYOK enablement and separate submission/media/destruction grants")],
) -> dict:
    """Plan or perform one bounded TwelveLabs asset/index/search/embed/entity/analysis operation.

    Disabled by default. Dry plans read only selected fenced local media and make
    no DNS, provider or database calls. Execution requires explicit BYOK/network
    authority; media disclosure and deletion/cancellation have separate grants.
    Each call makes at most one HTTP request with no retries or automatic polling.
    Reusing an identical job_id reads the attested local receipt without resending.
    Remote readiness, exact clip seconds and IDs stay provider observations.

    Args:
        request: Current REST route, bounded payload and explicit side-effect choices.

    Returns:
        Typed plan/remote observation or error, exact response hash and durable call
        receipt. Charges, original remote bytes and factual identity remain unknown.
    """
    return await execute(request)
