"""Explicit development image submit, poll, finalize and cancel operations."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..image_generation import cancel_image_generation, recover_image_generation, submit_image_generation
from ..models.image_generation import ImageGenerationRequest, ImageOperation

image_generation_server = FastMCP("image_generation")


@image_generation_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_image_generation_submit(
    project_id: Annotated[str, Field(description="Existing approved project ID")],
    request: Annotated[ImageGenerationRequest, Field(description="Exact image request and bounded per-image spend instruction")],
) -> dict:
    """Submit one logical image job after all source and price/access checks.

    Args:
        project_id: Configured project with exact source and reference files.
        request: Frozen mapped image mode and explicit spend declaration.

    Returns:
        Typed durable image state or the standard tool error.
    """
    try:
        return await submit_image_generation(project_id, request)
    except Exception as error:
        return make_tool_error(error)


@image_generation_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_image_generation_poll(
    job_id: Annotated[str, Field(description="Durable image job ID")],
    operation: Annotated[ImageOperation, Field(description="Unique authorized bounded recovery operation")],
) -> dict:
    """Fetch one documented translation task or finalize an already captured response.

    Args:
        job_id: Durable image job retained across restarts.
        operation: Unique explicit operation; reuse returns durable state.

    Returns:
        Typed recovered state and image proof or the standard tool error.
    """
    try:
        return await recover_image_generation(job_id, operation)
    except Exception as error:
        return make_tool_error(error)


@image_generation_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_image_generation_finalize(
    job_id: Annotated[str, Field(description="Durable image job with captured output")],
    operation: Annotated[ImageOperation, Field(description="Unique authorized image custody operation")],
) -> dict:
    """Download and qualify captured outputs without a new generation or task fetch.

    Args:
        job_id: Existing image job with a recoverable response.
        operation: Explicit bounded custody instruction.

    Returns:
        Typed actual image format/dimension/hash proof or the standard tool error.
    """
    try:
        return await recover_image_generation(job_id, operation, finalize=True)
    except Exception as error:
        return make_tool_error(error)


@image_generation_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_image_generation_cancel(
    job_id: Annotated[str, Field(description="Durable image job ID")],
    operation: Annotated[ImageOperation, Field(description="Unique authorized cancellation instruction")],
) -> dict:
    """Refuse synchronous cancel or cancel a fresh PENDING translation and confirm it.

    Args:
        job_id: Existing selected image job.
        operation: Explicit caller cancellation intent.

    Returns:
        Typed refusal or confirmed provider cancellation, or the standard tool error.
    """
    try:
        return await cancel_image_generation(job_id, operation)
    except Exception as error:
        return make_tool_error(error)
