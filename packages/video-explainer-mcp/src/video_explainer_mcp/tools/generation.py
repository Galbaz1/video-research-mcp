"""Three explicit public operations for the selected durable video API."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..generation import cancel_generation, poll_generation, submit_generation
from ..models.generation import GenerationOperation, GenerationRequest

generation_server = FastMCP("generation")


@generation_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_generation_submit(
    project_id: Annotated[str, Field(description="Existing approved project ID")],
    request: Annotated[GenerationRequest, Field(description="Frozen scene request and explicit bounded spend instruction")],
) -> dict:
    """Submit one logical selected video job after all pre-spend checks.

    Args:
        project_id: Existing configured project containing pinned scene/script inputs.
        request: Exact selected parameters, caller authorization and cost bound.

    Returns:
        Typed durable generation readback or the standard tool error.
    """
    try:
        return await submit_generation(project_id, request)
    except Exception as exc:
        return make_tool_error(exc)


@generation_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_generation_poll(
    job_id: Annotated[str, Field(description="Durable selected generation job ID")],
    operation: Annotated[GenerationOperation, Field(description="Explicit authorized bounded poll operation")],
) -> dict:
    """Fetch once and qualify a completed asset without resubmitting generation.

    Args:
        job_id: Job returned by submit, including after a server restart.
        operation: Unique authorized operation ID; a replay returns durable readback.

    Returns:
        Typed source/operation/artifact readback or the standard tool error.
    """
    try:
        return await poll_generation(job_id, operation)
    except Exception as exc:
        return make_tool_error(exc)


@generation_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_generation_cancel(
    job_id: Annotated[str, Field(description="Durable selected generation job ID")],
    operation: Annotated[GenerationOperation, Field(description="Explicit authorized cancel operation")],
) -> dict:
    """Cancel only a freshly PENDING provider task and fetch confirmation.

    Args:
        job_id: Selected job with a durably bound provider task ID.
        operation: Unique authorized cancel instruction; ACK alone is not cancellation.

    Returns:
        Typed durable cancellation observation or the standard tool error.
    """
    try:
        return await cancel_generation(job_id, operation)
    except Exception as exc:
        return make_tool_error(exc)
