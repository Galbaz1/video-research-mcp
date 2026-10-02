"""Sequential leased window runs; ambiguous windows never automatically resubmit."""

from __future__ import annotations

import asyncio
import copy
import hashlib
from pathlib import Path
import time
from uuid import uuid4

from google.genai import types

from .errors import make_tool_error
from .execution_budget import ExecutionBudget
from .job_execution import job_submission
from .job_store import JobStore
from .models.execution import ExecutionLimits
from .models.video_windows import WindowRunLimits
from .research_jobs import TERMINAL, live_lease, retained_result
from .tools.video_core import analyze_video
from .tools.video_file import _video_file_content
from .tools.video_url import _video_content
from .video_window_plan import fingerprint, validate_plan
from .video_window_state import (
    COUNTERS,
    failure_status,
    response_status,
    run_usage,
    stopped_run,
    summarize_run,
)


def _checked(job: dict | None) -> dict:
    """Reject corrupted canonical evidence before claiming or replacing checkpoints."""
    if (
        not job
        or job["kind"] != "video_windows"
        or job["attestation"]["request_integrity"] != "verified"
        or job["attestation"]["result_integrity"] not in {"verified", "absent"}
    ):
        raise ValueError("Window job evidence failed canonical readback attestation")
    return job


def _admit(store, plan, limits, job_id, token):
    """Bind one deterministic child to its terminal parent and immutable new limits."""
    previous = None
    if token:
        parent = _checked(store.get(token))
        if (
            parent["status"] != "partial"
            or not parent["result"]
            or parent["result"].get("continuation_token") != token
        ):
            raise ValueError("Continuation requires the token of a clean terminal partial run")
        frozen = parent["request"]["plan"]
        for key in ("request", "source", "runtime", "schema_sha256", "prompt_preamble_sha256"):
            if plan[key] != frozen[key]:
                raise ValueError("Continuation source/request/model/schema/settings differ")
        plan, previous = frozen, parent["result"]
        child = "windows-" + fingerprint({"parent_job_id": token})
        if job_id is not None and job_id != child:
            raise ValueError("Continuation job_id must be its deterministic child identity")
        job_id = child
    revision = hashlib.sha256(
        b"".join(
            (Path(__file__).parent / name).read_bytes()
            for name in (
                "video_window_plan.py",
                "video_window_run.py",
                "video_window_state.py",
                "models/video_windows.py",
            )
        )
    ).hexdigest()
    request = {
        "plan": plan,
        "limits": limits.model_dump(),
        "parent_job_id": token,
        "previous_result": previous,
    }
    return _checked(store.create("video_windows", request, revision, job_id=job_id))


def _seed(job):
    """Retain parent outcomes while resetting only this child's five run counters."""
    prior = job["request"]["previous_result"]
    items = copy.deepcopy(prior["windows"] if prior else job["request"]["plan"]["windows"])
    for item in items:
        item.setdefault("status", "queued")
        if item["status"] == "running":
            item.update(status="unknown", error="Interrupted submission; not resubmitted")
    return {
        "windows": items,
        "previous_usage": prior["execution_usage"] if prior else dict.fromkeys(COUNTERS, 0),
        "preparation": {"state": "not_started"},
    }


def _save(store, job, owner, state, status=None, reason="running", release=False):
    """Attest the current row and CAS progress without overriding cancellation."""
    current = _checked(store.get(job["job_id"]))
    result = summarize_run(job, state, status or current["status"], reason)
    if not store.checkpoint(job["job_id"], owner, status=status, result=result, release=release):
        raise RuntimeError("Window run lost live checkpoint ownership")


def _submission_stop(store, job_id, owner):
    """Read attested cancellation and live ownership immediately before a submission."""
    row = _checked(store.get(job_id))
    if (
        row["owner"] != owner
        or row["lease_until"] is None
        or row["lease_until"] <= time.time()
        or row["status"] not in {"running", "cancel_requested"}
    ):
        return "ownership_lost"
    return "cancel_requested" if row["status"] == "cancel_requested" else None


def _generation_check(store, job_id, owner):
    """Reject a generation whose count completed after cancellation or lease loss."""
    if reason := _submission_stop(store, job_id, owner):
        raise RuntimeError(f"Window generation blocked: {reason}")


def _next_limits(job, state, item):
    """Reserve capacity for both count and generation before preparing or sending media."""
    limits, used = job["request"]["limits"], run_usage(state["windows"], job["job_id"])
    remaining = {
        name: limits[name] - used[counter]
        for name, counter in zip(
            ("max_calls", "max_tokens", "max_output_tokens", "max_frames", "max_windows"), COUNTERS
        )
    }
    if (
        remaining["max_calls"] < 2
        or remaining["max_windows"] < 2
        or remaining["max_frames"] < 2 * item["requested_frames"]
        or remaining["max_tokens"] < 1
        or remaining["max_output_tokens"] < 1
    ):
        return None
    remaining["max_output_tokens"] = min(remaining["max_output_tokens"], remaining["max_tokens"])
    return ExecutionLimits(
        **remaining,
        start_ms=item["start_ms"],
        end_ms=item["end_ms"],
        fps=job["request"]["plan"]["fps"],
    )


def _metadata(item, fps):
    """Express strict millisecond coordinates using current SDK duration strings."""
    return types.VideoMetadata(
        fps=fps,
        start_offset=f"{item['start_ms'] // 1000}.{item['start_ms'] % 1000:03d}s",
        end_offset=f"{item['end_ms'] // 1000}.{item['end_ms'] % 1000:03d}s",
    )


async def _prepare(plan, item):
    """Prepare once and verify both current originals and inline transport bytes."""
    if plan["source"]["kind"] == "remote_url":
        return _video_content(plan["source"]["uri"], item["prompt"]), ""
    contents, digest, uri = await _video_file_content(
        plan["source"]["path"], item["prompt"], video_metadata=_metadata(item, plan["fps"])
    )
    await asyncio.to_thread(validate_plan, plan)
    if digest != plan["source"]["sha256"]:
        raise ValueError("Prepared content commitment differs from the frozen source")
    for part in contents.parts:
        if (
            part.inline_data is not None
            and hashlib.sha256(part.inline_data.data).hexdigest() != digest
        ):
            raise ValueError("Prepared inline bytes differ from the frozen source")
    media = [
        part
        for part in contents.parts
        if part.inline_data is not None or part.file_data is not None
    ]
    if len(media) != 1 or (media[0].file_data is not None and media[0].file_data.file_uri != uri):
        raise ValueError("Prepared video transport does not bind the frozen local source")
    return contents, uri


async def _generate_window(plan, item, prepared):
    """Build the actual static SDK request from the one retained prepared Content."""
    contents = prepared.model_copy(deep=True)
    for part in contents.parts:
        if part.text is not None:
            part.text = item["prompt"]
        else:
            part.video_metadata, part.media_processing = (
                _metadata(item, plan["fps"]),
                types.MediaProcessing.STATIC,
            )
    request = plan["request"]
    source = plan["source"]
    return await analyze_video(
        contents,
        instruction=item["prompt"],
        content_id=source["video_id"] if source["kind"] == "remote_url" else source["sha256"],
        source_label=source.get("uri") or source["path"],
        output_schema=request["output_schema"],
        thinking_level=request["thinking_level"],
        use_cache=False,
        local_filepath=source.get("path", ""),
    )


async def _window(store, job, owner, state, item, prepared, limits):
    """Checkpoint one submission before SDK calls; never retry an ambiguous result."""
    plan = job["request"]["plan"]
    await asyncio.to_thread(validate_plan, plan)
    if reason := _submission_stop(store, job["job_id"], owner):
        return reason
    item.update(status="running", run_job_id=job["job_id"])
    item.pop("execution_usage", None)
    _save(store, job, owner, state)
    budget = ExecutionBudget(
        limits, generation_check=lambda: _generation_check(store, job["job_id"], owner)
    )
    try:
        with budget.activate():
            result = await _generate_window(plan, item, prepared)
        await asyncio.to_thread(validate_plan, plan)
        item.update(result=result, status="completed")
        item["execution_usage"] = budget.report()
        item["status"] = response_status(result, item["execution_usage"])
        if run_usage([item], job["job_id"])["output_tokens"] > limits.max_output_tokens:
            item.update(status="failed", error="Provider exceeded the reserved output allowance")
    except asyncio.CancelledError:
        item.update(status="unknown", error="Interrupted submission; provider completion unknown")
        raise
    except Exception as error:
        item.update(status=failure_status(error, budget.calls), result=make_tool_error(error))
    finally:
        item["execution_usage"] = budget.report()
        reason = _submission_stop(store, job["job_id"], owner)
        if reason and not any(call["kind"] == "generate_content" for call in budget.calls):
            item.update(status="queued", generation_dispatch="not_sent")
        if reason != "ownership_lost":
            _save(store, job, owner, state)
    if reason:
        if reason == "cancel_requested" and item["status"] == "completed":
            item.update(status="completed_after_cancel", reconciliation_required=True)
        return reason
    if item["status"] == "queued":
        return "budget_exhausted"
    return "running" if item["status"] == "completed" else "unresolved"


async def _run(store, job, owner, state):
    """Stop before preparation or another call whenever capacity/ownership is unavailable."""
    if any(item["status"] not in {"completed", "queued"} for item in state["windows"]):
        return "unresolved"
    prepared = None
    for item in state["windows"]:
        if item["status"] != "queued":
            continue
        if _checked(store.get(job["job_id"]))["status"] == "cancel_requested":
            return "cancel_requested"
        limits = _next_limits(job, state, item)
        if limits is None:
            return "budget_exhausted"
        if prepared is None:
            state["preparation"] = {"state": "running", "generation_budget_included": False}
            _save(store, job, owner, state)
            try:
                prepared, uri = await _prepare(job["request"]["plan"], item)
                state["preparation"].update(
                    state="completed",
                    file_api_used=bool(uri),
                    uploaded_uri_freshness="unknown" if uri else "not_used",
                )
            finally:
                if (
                    job["request"]["plan"]["preparation"]["provider_route"]
                    == "File API upload/cache validation"
                ):
                    from .tools.video_file import _upload_cache_dir
                    from .tools.video_upload import upload_receipt

                    source = job["request"]["plan"]["source"]
                    state["preparation"]["upload_receipt"] = upload_receipt(
                        source["sha256"], source["mime_type"], _upload_cache_dir()
                    )
                    state["preparation"]["upload_receipt_scope"] = (
                        "lifetime_of_retained_resource; wire attempts and hard wallclock remain unknown"
                    )
            if _checked(store.get(job["job_id"]))["status"] == "cancel_requested":
                return "cancel_requested"
        reason = await _window(store, job, owner, state, item, prepared, limits)
        if reason != "running":
            return reason
    return "completed"


async def execute_windows(
    plan: dict,
    limits: WindowRunLimits,
    *,
    job_id: str | None = None,
    continuation_token: str | None = None,
) -> dict:
    """Run pending windows once under a canonical lease, or return attested progress.

    Args:
        plan: Dry planner's frozen local source and requested window selection.
        limits: This run's count/generation limits; child limits freeze at admission.
        job_id: Optional immutable explicit identity for retries or restart.
        continuation_token: Clean partial parent's identity for one deterministic child.

    Returns:
        Ordered outcomes, unresolved/remaining windows and canonical job attestation.
    """
    limits = WindowRunLimits.model_validate(limits)
    await asyncio.to_thread(validate_plan, plan)
    store = JobStore()
    job = _admit(store, plan, limits, job_id, continuation_token)
    if job["status"] in TERMINAL:
        return retained_result(job)
    owner = uuid4().hex
    claimed = store.claim(job["job_id"], owner)
    if claimed is None:
        return retained_result(_checked(store.get(job["job_id"])))
    job = _checked(claimed)
    state = copy.deepcopy(job["result"]) if job["result"] else _seed(job)
    for item in state["windows"]:
        if item["status"] == "running":
            item.update(status="unknown", error="Interrupted submission; not resubmitted")
    try:
        with job_submission():
            async with live_lease(store, job["job_id"], owner):
                reason = await _run(store, job, owner, state)
    except asyncio.CancelledError:
        if _submission_stop(store, job["job_id"], owner) != "ownership_lost":
            store.cancel(job["job_id"])
            _save(store, job, owner, state, "partial", "interrupted", True)
        raise
    except Exception as error:
        state["error"] = make_tool_error(error)
        reason = "preparation_or_binding_failed"
    if _submission_stop(store, job["job_id"], owner) == "ownership_lost":
        return {
            **retained_result(_checked(store.get(job["job_id"]))),
            "stopped_run": stopped_run(state, job["job_id"]),
        }
    status = "completed" if reason == "completed" else "partial"
    _save(store, job, owner, state, status, reason, True)
    return retained_result(_checked(store.get(job["job_id"])))
