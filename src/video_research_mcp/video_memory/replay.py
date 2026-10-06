"""Finite evidence-only watch/replay through the existing bounded AV native route.

Independent implementation of QwenLM/Qwen-MM-Plugins lifecycle protocol at
07736672525443c7f8a3f6405eed37d2236f023f, Apache-2.0. Changed: explicit clip/source
commitments, no foreign prompts/SDK, no retry, no generated answers or speaker truth.
"""

import asyncio
import math
import time

from ..models.video_memory_av import PlanRequest, WINDOW_SECONDS
from ..models.video_memory_lifecycle import Segment
from . import av_build, av_store, lifecycle_inputs as inputs, retrieval


def _selection(request):
    """Select named caller clips, preserving missing/dropped reasons and global spans."""
    if request.action == "watch":
        source = request.source
        return [(source.segment_id, source, (0.0, source.duration_seconds))], [], [], None
    _, state, checkpoint = inputs.load(request, verify=False)
    available = {}
    for planned in checkpoint.segments:
        for clip in planned.source.clips:
            start = clip.window * WINDOW_SECONDS
            duration = min(WINDOW_SECONDS, planned.source.duration_seconds - start)
            source = Segment(segment_id=planned.source.segment_id, file_path=clip.path,
                             expected_source_sha256=clip.sha256, expected_source_bytes=clip.bytes,
                             duration_seconds=duration)
            key = f"{planned.source.segment_id}:{clip.window}"
            available[key] = (key, source, (planned.offset_seconds + start,
                                           planned.offset_seconds + start + duration))
    selected, missing, dropped, seen = [], [], [], set()
    for key in request.clips:
        if key in seen:
            dropped.append({"clip_id": key, "reason": "duplicate"})
        elif key not in available:
            missing.append(key)
        elif len(selected) >= request.limits.max_clips:
            dropped.append({"clip_id": key, "reason": "clip_limit"})
        else:
            selected.append(available[key])
        seen.add(key)
    return sorted(selected, key=lambda item: item[2]), missing, dropped, state


def _bounded(selected, limits, missing, dropped):
    """Enforce declared duration and inline-equivalent payload before source acquisition."""
    used, duration, payload = [], 0.0, 0
    for key, source, span in selected:
        path = av_store.local_path(source.file_path)
        if not path.is_file():
            missing.append(key)
            continue
        size = 4 * math.ceil(source.expected_source_bytes / 3) + len("data:video/mp4;base64,")
        if duration + source.duration_seconds > limits.max_duration_seconds:
            dropped.append({"clip_id": key, "reason": "duration_limit"})
        elif payload + size > limits.max_payload_bytes:
            dropped.append({"clip_id": key, "reason": "payload_limit"})
        else:
            used.append((key, source, span))
            duration += source.duration_seconds
            payload += size
    return used, payload, duration


async def _observe(request, selected, costs, deadline, observations):
    """Call only the configured existing native route; every delegation is receipted once."""
    route = request.av_route if request.action == "replay" else request.config.av_route
    for key, source, _ in selected:
        inputs.verify_source(source)
        calls = av_build.route_calls(route, source.duration_seconds)
        if len(costs) + len(calls) > route.max_calls:
            raise inputs.LifecycleFailure("Watch/replay route call ceiling reached", "reject", clip_id=key)
        responses = []
        for call in calls:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Watch/replay invocation deadline expired")
            receipt = {**call, "clip_id": key, "status": "attempted", "execution": None}
            costs.append(receipt)
            try:
                async with asyncio.timeout(remaining):
                    response = await inputs.run_route(route, source.file_path,
                                                       source.expected_source_sha256, [call])
            except Exception as error:
                receipt.update(status="failed", error_type=type(error).__name__)
                raise
            receipt.update(av_build.route_costs(response)[0])
            responses.extend(response)
        admitted, _ = inputs.admit_route(source, responses)
        inputs.verify_source(source)
        records, _ = av_build.fold(source.expected_source_sha256, source.duration_seconds, admitted)
        observations.append({"clip_id": key, "source_sha256": source.expected_source_sha256,
                             "parent_clock_basis": "caller_asserted",
                             "records": [r.model_dump(mode="json") for r in records]})
        if len(av_store.canonical(observations)) > request.limits.max_payload_bytes:
            observations.pop()
            raise inputs.LifecycleFailure("Watch/replay response payload ceiling reached", "reject", clip_id=key)


async def run(request) -> dict:
    """One bounded invocation; unavailable routes are rejected before media work starts."""
    selected, missing, dropped, state = _selection(request)
    result = {"action": request.action, "complete": False, "missing_clips": missing,
              "dropped_clips": dropped, "watched_clips": [], "observations": [],
              "costs": {"route_calls": []}, "wire_payload_bytes": None}
    route = request.av_route if request.action == "replay" else request.config.av_route
    if route is None or not route.authorize_submission:
        return result | {"status": "unavailable", "failure": "config"}
    deadline = time.monotonic() + request.limits.timeout_seconds
    selected, payload, duration = _bounded(selected, request.limits, missing, dropped)
    result.update(inline_equivalent_source_bytes=payload, selected_duration_seconds=duration)
    if not selected:
        return result | {"status": "rejected", "failure": "reject"}
    try:
        if request.action == "replay":
            inputs.load(request)
        await _observe(request, selected, result["costs"]["route_calls"], deadline, result["observations"])
    except Exception as error:
        report = getattr(error, "report", {})
        watched = [item["clip_id"] for item in result["observations"]]
        return result | {"status": "failed", "failure": report.get("failure", inputs.classify(error)),
                         "error_type": type(error).__name__, "report": report,
                         "watched_clips": watched,
                         "stopped_clips": [key for key, _, _ in selected if key not in watched]}
    result.update(watched_clips=[key for key, _, _ in selected])
    if state is not None:
        query = PlanRequest(action="plan", memory_dir=request.memory_dir,
                            expected_source_sha256=request.expected_source_sha256, question="",
                            time_ranges=[span for _, _, span in selected], include_environment=False)
        evidence = await retrieval.run_plan(state, query, retrieval.new_costs())
        if len(av_store.canonical([result["observations"], evidence])) > request.limits.max_payload_bytes:
            result["stored_evidence"] = {"status": "omitted", "reason": "response_payload_limit",
                                         "record_count": len(evidence["evidence_record_ids"])}
            return result | {"status": "partial", "failure": "reject"}
        result["stored_evidence"] = evidence
    return result | {"status": "complete" if not missing and not dropped else "partial",
                     "complete": not missing and not dropped, "failure": None}
