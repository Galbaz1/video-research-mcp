"""Atomic bounded build/append/resume over the existing immutable AV snapshot store.

Independent protocol implementation, referencing QwenLM/Qwen-MM-Plugins
@07736672525443c7f8a3f6405eed37d2236f023f, Apache-2.0. Changes: frozen denominators,
strict source/config/revision commitments, no automatic retries or background jobs.
"""

import asyncio
from datetime import datetime, timezone
import time

from ..models.video_memory_av import MemoryState, SourceInfo
from ..models.video_memory_lifecycle import Checkpoint
from . import av_build, av_store, lifecycle_inputs as inputs, lifecycle_records, retrieval


def coverage(state, checkpoint) -> dict:
    """Report durable progress, separate from observation density or semantic quality."""
    planned = sum(s.planned_windows for s in checkpoint.segments)
    total = sum(s.source.duration_seconds for s in checkpoint.segments)
    return {"exists": True, "memory_id": state.memory_id, "revision": state.revision,
            "complete": len(checkpoint.extracted) == planned,
            "extracted": len(checkpoint.extracted), "planned": planned,
            "extracted_clips": checkpoint.extracted, "failure": checkpoint.failure,
            "config_sha256": checkpoint.config_sha256, "duration_seconds": total,
            "clock_basis": "caller_asserted", "records": len(state.records),
            "people": len(state.persons), "active_facts": sum(f.status == "active" for f in state.facts),
            "segments": [s.model_dump(mode="json") for s in checkpoint.segments]}


def _entry(action, checkpoint, costs) -> dict:
    """Embed the current complete plan in the same atomic revision as its records."""
    return {"action": action, "at": datetime.now(timezone.utc).isoformat(),
            "lifecycle": checkpoint.model_dump(mode="json"), "costs": costs}


def _next(state, checkpoint, action, costs):
    """Retain historical failures, referencing immutable prior revisions instead of copying plans."""
    following = state.model_copy(deep=True)
    for entry in following.history:
        if "lifecycle" in entry:
            previous = entry.pop("lifecycle")
            entry.update(checkpoint_revision=state.revision, extracted=len(previous["extracted"]),
                         failure=previous["failure"])
    following.revision += 1
    following.history.append(_entry(action, checkpoint, costs))
    return following


def _ready(request) -> None:
    """Reject unconfigured extraction before any source or durable build work."""
    route = request.config.av_route
    if route is not None and not route.authorize_submission:
        raise inputs.LifecycleFailure("AV route submission is not authorized", "config", status="unavailable")
    if request.action in {"build", "append"} and any(not s.artifacts for s in request.segments) and route is None:
        raise inputs.LifecycleFailure("Every source needs supplied observations or an authorized AV route",
                                      "config", status="unavailable")


def _begin(request):
    checkpoint = Checkpoint(config_sha256=inputs.config_digest(request.config),
                            segments=inputs.plan(request.segments))
    source = request.segments[0]
    if source.expected_source_sha256 != request.expected_source_sha256:
        raise ValueError("Build anchor digest differs from the first planned source")
    root = av_store.local_path(request.memory_dir)
    if av_store.load(root, request.expected_source_sha256) is not None:
        raise ValueError("A canonical memory already exists; use append or resume")
    inputs.verify_source(source)
    state = MemoryState(memory_id="avm:" + request.expected_source_sha256, revision=1,
                        source=SourceInfo(sha256=source.expected_source_sha256,
                                          bytes=source.expected_source_bytes, path=source.file_path,
                                          duration_seconds=source.duration_seconds),
                        windows=av_build.window_count(sum(s.source.duration_seconds for s in checkpoint.segments)),
                        artifacts=[], records=[], persons=[], history=[_entry("plan", checkpoint, {})])
    inputs.commit(root, state, {})
    return root, state, checkpoint


def _append(request, root, state, checkpoint):
    if not coverage(state, checkpoint)["complete"]:
        raise ValueError("Incomplete memory must be resumed before append")
    checkpoint = checkpoint.model_copy(deep=True)
    checkpoint.segments = inputs.plan(request.segments, checkpoint.segments)
    checkpoint = Checkpoint.model_validate(checkpoint.model_dump())
    checkpoint.failure = None
    following = _next(state, checkpoint, "append_plan", {})
    following.windows = av_build.window_count(sum(s.source.duration_seconds for s in checkpoint.segments))
    inputs.commit(root, following, {})
    return following, checkpoint


async def _window(request, planned, window, admitted, retained, costs, remaining):
    """Admit one requested window and retain each optional native delegation receipt."""
    route = request.config.av_route
    if route:
        calls = inputs.calls_for_window(route, window, planned.source.duration_seconds)
        if len(costs["route_calls"]) + len(calls) > route.max_calls:
            raise inputs.LifecycleFailure("Invocation AV route call limit reached", "reject", limit="route_calls")
        responses = []
        async with asyncio.timeout(remaining):
            for call in calls:
                receipt = {**call, "status": "attempted", "execution": None}
                costs["route_calls"].append(receipt)
                try:
                    response = await inputs.run_route(route, planned.source.file_path,
                                                       planned.source.expected_source_sha256, [call])
                except Exception as error:
                    receipt["status"] = "failed"
                    receipt["error_type"] = type(error).__name__
                    raise
                receipt.update(av_build.route_costs(response)[0])
                responses.extend(response)
        routed, data = inputs.admit_route(planned.source, responses)
        start, end = window * 30.0, min((window + 1) * 30.0, planned.source.duration_seconds)
        if any(r.start_seconds < start or r.end_seconds > end + av_build.CLOCK_TOLERANCE_SECONDS
               for _, result in routed for r in result.records):
            raise ValueError("AV route records lie outside the requested source window")
        admitted, retained = [*admitted, *routed], retained | data
    if not admitted:
        raise inputs.LifecycleFailure("No observations available for extraction", "config", status="unavailable")
    if sum(map(len, retained.values())) > av_build.MAX_TOTAL_BYTES:
        raise ValueError("Window artifact payload exceeds 32 MiB")
    return admitted, retained


def _failed(root, state, checkpoint, clip_id, error, costs):
    """Persist the failed segment without publishing its unaccepted records or processing later ones."""
    checkpoint = checkpoint.model_copy(deep=True)
    report = getattr(error, "report", {})
    checkpoint.failure = {"clip_id": clip_id, "kind": report.get("failure", inputs.classify(error)),
                          "error_type": type(error).__name__, "report": report}
    following = _next(state, checkpoint, "failed", costs)
    inputs.commit(root, following, {})
    return following, checkpoint


async def _ingest(request, root, state, checkpoint, deadline):
    """Process only the missing chronological prefix within one finite invocation."""
    costs, processed, stopped = {"route_calls": []}, 0, None
    for planned in checkpoint.segments:
        remaining = [w for w in range(planned.planned_windows)
                     if f"{planned.source.segment_id}:{w}" not in checkpoint.extracted]
        if not remaining:
            continue
        admitted, retained = None, {}
        for window in remaining:
            clip_id = f"{planned.source.segment_id}:{window}"
            if processed >= request.limits.max_windows or time.monotonic() >= deadline:
                stopped = "window_limit" if processed >= request.limits.max_windows else "timeout"
                return state, checkpoint, costs, stopped
            try:
                inputs.verify_source(planned.source)
                if admitted is None:
                    admitted, retained = inputs.supplied(planned.source)
                observed, data = await _window(request, planned, window, admitted, retained, costs,
                                                max(0.001, deadline - time.monotonic()))
                if time.monotonic() >= deadline:
                    raise TimeoutError("Invocation deadline expired before checkpoint publication")
                progress = checkpoint.model_copy(deep=True)
                progress.extracted.append(clip_id)
                progress.failure = None
                following = _next(state, progress, "extract", costs)
                lifecycle_records.accumulate(following, planned, window, observed)
                inputs.verify_source(planned.source)
            except Exception as error:
                state, checkpoint = _failed(root, state, checkpoint, clip_id, error, costs)
                return state, checkpoint, costs, "failed_segment"
            # Publication errors propagate: no retry or second write to conceal a failed checkpoint.
            inputs.commit(root, following, data)
            state, checkpoint = following, progress
            processed += 1
    return state, checkpoint, costs, stopped


async def run(request) -> dict:
    """Execute one finite lifecycle invocation and return durable readback coverage."""
    if request.action == "status":
        _, state, checkpoint = inputs.load(request)
        return coverage(state, checkpoint) | {"status": "complete" if coverage(state, checkpoint)["complete"]
                                              else "incomplete", "action": "status", "costs": {"route_calls": []}}
    _ready(request)
    deadline = time.monotonic() + request.limits.timeout_seconds
    if request.action == "build":
        root, state, checkpoint = _begin(request)
    else:
        root, state, checkpoint = inputs.load(request)
        if request.action == "append":
            state, checkpoint = _append(request, root, state, checkpoint)
    state, checkpoint, costs, stopped = await _ingest(request, root, state, checkpoint, deadline)
    durable = av_store.load(root, request.expected_source_sha256)
    if durable.revision != state.revision:
        raise inputs.LifecycleFailure("Revision changed before durable readback", "reject")
    result = coverage(durable, checkpoint)
    return result | {"action": request.action, "status": "complete" if result["complete"] else "incomplete",
                     "stopped": stopped, "costs": costs}


async def timeline(request) -> dict:
    """Reuse evidence-only retrieval on the complete global clock, including partial progress."""
    from ..models.video_memory_av import PlanRequest

    _, state, checkpoint = inputs.load(request)
    duration = sum(s.source.duration_seconds for s in checkpoint.segments)
    query = PlanRequest(action="plan", memory_dir=request.memory_dir,
                        expected_source_sha256=request.expected_source_sha256, question="",
                        time_ranges=[(0.0, duration)], include_environment=False)
    return await retrieval.run_plan(state, query, retrieval.new_costs())
