"""Durable video-window planning and explicitly bounded execution."""

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..models.video_windows import WindowAnalysisRequest, WindowRunLimits
from ..tracing import trace
from ..video_window_plan import plan_windows
from ..video_window_run import execute_windows

video_windows_server = FastMCP("video_windows")


@video_windows_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
))
@trace(name="video_analyze_windows", span_type="TOOL")
async def video_analyze_windows(
    request: Annotated[
        dict,
        Field(description="Exactly one local file_path or YouTube url, instruction, start_ms/end_ms, window_ms, optional fps/output_schema/thinking_level; remote byte identity and freshness remain unknown"),
    ],
    execution_budget: Annotated[
        dict,
        Field(description="Explicit max_calls/max_tokens/max_output_tokens/max_frames/max_windows for this run; counts and generations each consume media transmissions, File API preparation is reported separately"),
    ],
    dry_run: Annotated[
        bool, Field(strict=True, description="Return a frozen local plan with zero provider calls; false explicitly executes against the configured provider"),
    ] = True,
    job_id: Annotated[
        str | None, Field(min_length=1, max_length=128, description="Optional caller ID for one immutable durable run; retrying this ID never repeats a recorded window"),
    ] = None,
    continuation_token: Annotated[
        str | None, Field(min_length=1, max_length=128, description="Previous partial-run token; binds source/settings/windows and resolves one idempotent child run"),
    ] = None,
) -> dict:
    """Plan or execute contiguous source windows with retained partial outcomes.

    Args:
        request: Source, instruction, interval and requested sampling settings.
        execution_budget: Five explicit generation/count limits for this run.
        dry_run: Return the plan without uploading or contacting the provider.
        job_id: Optional immutable run identity for safe retry/readback.
        continuation_token: Partial-run identity for the next bounded run.

    Returns:
        A local plan or durable ordered results, unresolved windows, remaining work,
        actual attempt counters and a continuation token. Model output does not
        establish factual/media review or complete observed source coverage.
    """
    try:
        typed_request = WindowAnalysisRequest.model_validate(request)
        limits = WindowRunLimits.model_validate(execution_budget)
        plan = await asyncio.to_thread(plan_windows, typed_request, limits)
        if dry_run:
            return {**plan, "dry_run": True, "network_calls": 0, "provider_calls": 0}
        return await execute_windows(
            plan, limits, job_id=job_id, continuation_token=continuation_token
        )
    except Exception as exc:
        return make_tool_error(exc)
