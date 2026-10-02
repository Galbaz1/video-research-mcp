"""Readback and checkpoint cancellation for durable video analysis jobs."""

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..job_store import JobStore
from ..tracing import trace

jobs_server = FastMCP("jobs")


@jobs_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
@trace(name="job_status", span_type="TOOL")
async def job_status(
    job_id: Annotated[
        str, Field(min_length=1, max_length=128, description="Recorded durable job ID")
    ],
) -> dict:
    """Read retained job identity, outcomes and current byte attestation.

    Args:
        job_id: The durable ID returned in job_receipt.

    Returns:
        Actual SQLite record and independent byte attestation, or a tool error.
    """
    try:
        result = await asyncio.to_thread(JobStore().get, job_id)
        if result is None:
            raise KeyError(f"Job not found: {job_id}")
        return result
    except Exception as exc:
        return make_tool_error(exc)


@jobs_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
@trace(name="job_cancel", span_type="TOOL")
async def job_cancel(
    job_id: Annotated[
        str, Field(min_length=1, max_length=128, description="Durable video batch or window-run ID")
    ],
) -> dict:
    """Cancel queued video work or request its owner stop at the next checkpoint.

    Args:
        job_id: The video batch or window run's durable ID.

    Returns:
        Actual local state; provider termination remains unknown.
    """
    try:
        store = JobStore()
        job = store.get(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        if job["kind"] not in {"video_batch", "video_windows"}:
            raise ValueError(
                "Use research_web_cancel or explainer_render_cancel for this operation"
            )
        result = store.cancel(job_id)
        return {
            **result,
            "provider_termination": "unknown",
            "cancellation_effect": "queued work stopped"
            if result["status"] == "cancelled"
            else "owner checkpoint requested"
            if result["status"] == "cancel_requested"
            else "already terminal",
        }
    except Exception as exc:
        return make_tool_error(exc)
