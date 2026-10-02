"""Persistent render tools with owned subprocess cancellation and lease heartbeats."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..job_store import JobStore
from ..jobs import get_job, reconcile_job
from ..models.pipeline import RenderResult
from ..render_artifacts import verify_output
from ..render_validation import qualification_valid
from ..render_worker import (
    _background_tasks as _background_tasks,
    _job_tasks,
    _run_render as _run_render,
    _cancel_ack,
    cancel_background_renders as cancel_background_renders,
    recover_render_jobs as recover_render_jobs,
    start_render,
)
from ..types import ProjectId, RenderResolution

render_server = FastMCP("render")


@render_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_render(
    project_id: ProjectId,
    resolution: Annotated[RenderResolution, Field(description="Output resolution")] = "720p",
    fast: Annotated[bool, Field(description="Use fast/preview quality")] = True,
) -> dict:
    """Render the explainer and wait for a verified fresh output revision.

    Args:
        project_id: Project with completed pipeline steps.
        resolution: Video resolution preset.
        fast: Use fast/preview quality.

    Returns:
        RenderResult with exact output path and duration, or a tool error.
    """
    try:
        result, output = await _run_render(project_id, resolution, fast)
        return RenderResult(
            project_id=project_id,
            success=True,
            output_file=output,
            duration_seconds=result.duration_seconds,
            resolution=resolution,
            message="MP4 fully decoded; renderer identity and content semantics remain unverified",
        ).model_dump() | {
            "playability_verified": True,
            "real_renderer_verified": False,
            "visual_audio_semantics": "not_verified",
        }
    except Exception as exc:
        return make_tool_error(exc)


@render_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_render_start(
    project_id: ProjectId,
    resolution: Annotated[RenderResolution, Field(description="Output resolution")] = "720p",
    fast: Annotated[bool, Field(description="Use fast/preview quality")] = True,
) -> dict:
    """Start one persisted background render and return its durable job ID.

    Args:
        project_id: Project to render.
        resolution: Video resolution preset.
        fast: Use fast/preview quality.

    Returns:
        Job ID and running status for polling after a client or server restart.
    """
    try:
        row = await start_render(project_id, resolution, fast)
        return {
            "job_id": row["job_id"],
            "project_id": project_id,
            "status": row["status"],
            "message": "Render accepted — poll with explainer_render_poll",
            "source_revision": row["source_revision"],
            "request_sha256": row["request_sha256"],
        }
    except Exception as exc:
        return make_tool_error(exc)


async def _poll_response(row: dict) -> dict:
    """Report persisted state with fresh artifact readback, never trusting status alone."""
    result = row["result"] or {}
    artifact = result.get("output")
    verified = (
        bool(artifact)
        and row["attestation"]["verified"]
        and await asyncio.to_thread(verify_output, artifact)
    )
    playable = verified and qualification_valid(artifact)
    status, error = row["status"], row["error"] or ""
    if status == "running" and (row["lease_until"] or 0) <= time.time():
        status, error = "unknown", "Process lease expired; execution and termination are unverified"
    if status == "completed" and not playable:
        status, error = "unknown", "Completed output lacks current byte-bound full-decode proof"
    if row["attestation"]["request_integrity"] != "verified":
        status, error = "unknown", "Render request failed integrity readback"
    return {
        "job_id": row["job_id"],
        "project_id": row["request"]["project_id"],
        "status": status,
        "recorded_status": row["status"],
        "output_file": artifact["path"] if playable else "",
        "error": error,
        "duration_seconds": result.get("duration_seconds", 0.0),
        "started_at": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat(),
        "completed_at": datetime.fromtimestamp(row["updated_at"], timezone.utc).isoformat()
        if row["status"] in {"completed", "failed", "cancelled", "partial"}
        else None,
        "source_revision": row["source_revision"],
        "request_sha256": row["request_sha256"],
        "result_sha256": row["result_sha256"],
        "settings": {
            "resolution": row["request"]["resolution"],
            "fast": row["request"]["fast"],
            "render_timeout": row["request"]["render_timeout"],
        },
        "provider_operation_id": row["external_id"],
        "artifact_hashes": row["artifact_hashes"],
        "artifact_verified": verified,
        "playability_verified": playable,
        "qualification": artifact.get("qualification") if playable else None,
        "real_renderer_verified": False,
        "visual_audio_semantics": "not_verified",
        "attestation": row["attestation"],
        "lease_until": row["lease_until"],
        "attempts": row["attempts"],
    }


@render_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def explainer_render_poll(
    job_id: Annotated[str, Field(description="Job ID from explainer_render_start")],
) -> dict:
    """Poll a durable render; orphaned process ownership remains explicitly unknown.

    Args:
        job_id: The render job identifier.

    Returns:
        Persisted job fields, source/request/operation binding and verified artifact hashes.
    """
    try:
        row = await asyncio.to_thread(get_job, job_id)
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return await _poll_response(row)
    except Exception as exc:
        return make_tool_error(exc)


@render_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_render_cancel(
    job_id: Annotated[str, Field(description="Job ID from explainer_render_start")],
) -> dict:
    """Request cancellation and join owned work; foreign process state stays unverified.

    Args:
        job_id: The durable render job identifier.

    Returns:
        Cancellation state, acknowledgement and current persisted evidence.
    """
    try:
        if get_job(job_id) is None:
            raise KeyError(f"Job not found: {job_id}")
        row = JobStore().cancel(job_id)
        owned = _job_tasks.get(job_id)
        if row["status"] == "cancel_requested" and owned:
            if not owned[1].cancelling():
                owned[1].cancel()
            await asyncio.gather(owned[1], return_exceptions=True)
            _cancel_ack(job_id, owned[0])
        row = await asyncio.to_thread(reconcile_job, job_id)
        response = await _poll_response(row)
        response["cancellation_scope"] = (
            "owned_posix_process_group" if os.name == "posix" else "owned_cli_only"
        )
        response["cancellation_acknowledged"] = row["status"] == "cancelled" and (
            row["external_id"] is None or os.name == "posix"
        )
        if row["status"] == "cancelled" and not response["cancellation_acknowledged"]:
            response["error"] = "Owned CLI joined; descendant process termination is unverified"
        if row["status"] == "cancel_requested" and not owned:
            response["error"] = (
                "Cancellation requested; this process cannot verify termination of old work"
            )
        return response
    except Exception as exc:
        return make_tool_error(exc)
