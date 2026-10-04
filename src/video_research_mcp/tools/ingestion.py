"""Local original-source extraction with located derivatives and durable readback."""

import asyncio
import time
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..config import get_config
from ..image_preprocessing import check_worker, image_worker
from ..ingestion import ingest_source, read_ingestion
from ..job_store import JobStore
from ..models.ingestion import SourceIngestRequest
from ..tracing import trace

ingestion_server = FastMCP("source-ingestion")


def _cancel_job(job_id, cancelled, deadline):
    """Join receipt readback and cancellation mutation before returning local state."""
    store = JobStore(readback_check=lambda: check_worker(cancelled, deadline))
    row = store.get(job_id)
    if row is None or row["kind"] != "source_ingestion":
        raise ValueError("Unknown source ingestion job")
    check_worker(cancelled, deadline)
    return store.cancel(job_id)


@ingestion_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True,
))
@trace(name="source_ingest", span_type="TOOL")
async def source_ingest(
    request: Annotated[SourceIngestRequest, Field(
        description="Original file or public HTTPS response, selected format, source ID and revision"
    )],
) -> dict:
    """Retain original bytes and extract bounded elements with explicit source positions.

    The default builtin parser preserves local extraction behavior. Explicit
    parser=docling requires an operator-qualified pinned loopback deployment and
    authorize_submission=true before source retention or upload. That route sends
    the exact retained original once, with OCR and enrichment disabled. Empty/error
    extraction fails; identical source/revision/parser work reuses its durable job.
    Deployment identity and semantic fidelity remain unverified. No indexing occurs.

    Args:
        request: One selected original and its preserved identity.

    Returns:
        Located elements, original and derivative byte commitments, job identity,
        explicit extraction limitations, or an actionable tool error.
    """
    try:
        return await ingest_source(request)
    except Exception as error:
        return make_tool_error(error)


@ingestion_server.tool(annotations=ToolAnnotations(
    readOnlyHint=True, idempotentHint=True, openWorldHint=False,
))
@trace(name="source_ingest_read", span_type="TOOL")
async def source_ingest_read(
    job_id: Annotated[str, Field(min_length=1, max_length=128,
                               description="Durable source ingestion job ID")],
) -> dict:
    """Recheck a retained ingestion job and read exact located extraction bytes.

    Args:
        job_id: The ID returned by source_ingest, including after restart.

    Returns:
        Revalidated original/derivative evidence or current failure/unknown state.
    """
    try:
        return await read_ingestion(job_id)
    except Exception as error:
        return make_tool_error(error)


@ingestion_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False,
))
@trace(name="source_ingest_cancel", span_type="TOOL")
async def source_ingest_cancel(
    job_id: Annotated[str, Field(min_length=1, max_length=128,
                               description="Durable source ingestion job ID")],
) -> dict:
    """Request cancellation without promoting an unfinished extraction to success.

    The owner acknowledges cancellation after its bounded parser has joined;
    this request alone does not prove that a running native process has stopped.

    Args:
        job_id: The ingestion ID returned while another call owns extraction.

    Returns:
        Current durable cancellation state with an explicit acknowledgement limit.
    """
    try:
        timeout = get_config().media_acquire_timeout_seconds
        async with asyncio.timeout(timeout):
            row = await image_worker(_cancel_job, job_id, deadline=time.monotonic() + timeout)
        result = {"job_id": job_id, "status": row["status"],
                  "termination_verified": row["status"] == "cancelled", "indexed": False}
        if row["request"].get("parser", {}).get("selected_parser") == "docling":
            result.update(termination_verified=False, remote_conversion="may_continue",
                          local_owner_acknowledged=row["status"] == "cancelled")
        return result
    except Exception as error:
        return make_tool_error(error)
