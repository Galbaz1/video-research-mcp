"""Joint AV timelines with measured source coverage and bounded untrusted inference."""

import asyncio
import hashlib
import time

from .config import get_config
from .errors import make_tool_error
from .image_manifest import json_digest
from .media_perception_provider import (MAX_ATTEMPTS, PerceptionBudget, PerceptionBudgetExceeded, infer_window,
                                        protect, provider_failure, selected_gemini)
from .models.media_perception import (AVPerceptionFailure, AVPerceptionRequest,
                                      AVPerceptionResponse, AVSourceEvidence, AVWindowAnswer)

TIME_TOLERANCE = 1e-6


def source_timeline(answer, window):
    """Validate local evidence support before mapping model offsets to source seconds."""
    result, previous = [], -1
    start, duration = window["start_seconds"], window["end_seconds"] - window["start_seconds"]
    for event in answer.events:
        if event.start_seconds < previous or event.end_seconds > duration + TIME_TOLERANCE:
            raise ValueError("Model timeline is unordered or outside its submitted window")
        previous = event.start_seconds
        absolute_start, absolute_end = start + event.start_seconds, start + event.end_seconds
        if event.modality == "spoken":
            interval = window["audio"]["selected_window"] if window["audio"] else None
            if interval is None or absolute_start < interval["start_seconds"] - TIME_TOLERANCE or absolute_end > interval["end_seconds"] + TIME_TOLERANCE:
                raise ValueError("Spoken event is outside submitted decoded audio")
        else:
            for index in event.frame_indices:
                if index >= len(window["frames"]) or not absolute_start - TIME_TOLERANCE <= window["frames"][index]["actual_seconds"] <= absolute_end + TIME_TOLERANCE:
                    raise ValueError("Visible event has no supporting submitted frame in its interval")
        value = event.model_dump(mode="json")
        value.update(start_seconds=absolute_start, end_seconds=absolute_end, window_index=window["index"])
        result.append(AVSourceEvidence.model_validate(value).model_dump(mode="json"))
    return result


def execution_report(request, budget, state, started):
    """Report observed calls and coverage without converting unknown usage into zero."""
    return {**budget.report(), "attempts": state["attempts"], "max_attempts_per_window": MAX_ATTEMPTS,
            "prepared_windows": len(state["windows"]), "completed_windows": sum(
                w["status"] == "complete" for w in state["windows"]),
            "prepared_payload_bytes": state["payload_bytes"],
            "image_transmissions": sum(c["submitted_frames"] for c in budget.calls),
            "audio_transmissions": sum(c["submitted_audio"] for c in budget.calls),
            "raw_payload_transmission_bytes": sum(c["raw_payload_bytes"] for c in budget.calls),
            "serialized_transmission_bytes": budget.transmission_bytes,
            "transmission_byte_method": "SDK_content_JSON_plus_schema_UTF8_per_count_and_generation",
            "transport_headers_and_framing_bytes": None, "wire_retries": 0,
            "elapsed_seconds": time.monotonic() - started,
            "operation_timeout_seconds": state["timeout_seconds"],
            "max_model_json_bytes_per_window": 128 * 1024,
            "model_time_validation_tolerance_seconds": TIME_TOLERANCE,
            "submission_authorized": request.authorize_submission,
            "cache_used": False, "continuous_watched_coverage": False}


async def _workflow(request, selected, budget, state):
    """Prepare all windows before submission and keep exact originals alive until joined."""
    from .media_perception_prepare import prepare_media

    async with prepare_media(request) as (source, windows, verify):
        state["source"] = source
        state["windows"] = [{**{k: v for k, v in w.items() if k != "parts"}, "status": "planned"} for w in windows]
        state["payload_bytes"] = sum(w["payload_bytes"] for w in windows)
        budget.frames = sum(len(w["frames"]) for w in windows)
        state["request_sha256"] = json_digest({"request": request.model_dump(mode="json"),
            "protocol": 1, "output_schema": AVWindowAnswer.model_json_schema(),
            "model": selected[0], "credential_commitment": hashlib.sha256(selected[1].encode()).hexdigest(),
            "temperature": selected[2], "source": source, "windows": state["windows"]})
        if request.dry_run:
            return
        if not request.authorize_submission or not selected[1]:
            raise PermissionError("Perception submission requires an explicit workflow grant and configured Gemini account")
        if 2 * len(windows) > request.limits.max_calls:
            raise PerceptionBudgetExceeded("Perception count/generation plan exceeds the provider call budget")
        for window, receipt in zip(windows, state["windows"]):
            receipt["status"] = "running"
            try:
                answer = await infer_window(request, window, selected, budget, state["attempts"], verify)
                events = source_timeline(answer, window)
                state["timeline"].extend(events)
                state["summaries"].append(answer.summary)
                state["abstentions"].extend({"window_index": window["index"], "reason": reason} for reason in answer.abstentions)
                receipt["status"] = "complete"
            except Exception:
                receipt["status"] = "failed"
                raise


async def perceive_media(request: AVPerceptionRequest) -> dict:
    """Return a dry plan or inferred joint timeline, preserving incomplete populations."""
    request = AVPerceptionRequest.model_validate(request)
    selected = selected_gemini()
    budget, started = PerceptionBudget(request.limits, selected), time.monotonic()
    state = {"source": None, "windows": [], "timeline": [], "summaries": [], "abstentions": [],
             "attempts": [], "payload_bytes": 0, "request_sha256": None, "timeout_seconds": None}
    try:
        timeout = min(request.limits.timeout_seconds, get_config().media_acquire_timeout_seconds)
        state["timeout_seconds"] = timeout
        async with asyncio.timeout(timeout):
            await _workflow(request, selected, budget, state)
        value = {"status": "planned" if request.dry_run else "complete", "source": state["source"],
                 "backend": {"name": "gemini", "model": selected[0], "temperature": selected[2],
                             "endpoint": "https://generativelanguage.googleapis.com", "delivery": "inline_sampled_frames_and_pcm_wav",
                             "quality_verified": False}, "request_sha256": state["request_sha256"],
                 "windows": state["windows"], "timeline": state["timeline"], "summaries": state["summaries"],
                 "abstentions": state["abstentions"], "execution": execution_report(request, budget, state, started),
                 "provenance": {"timeline": "model_inference", "source_clock": "decoded_source_pts",
                                "factual_correctness_verified": False, "human_review": "pending",
                                "visual_sampling_may_miss_events": True, "retained_artifact_paths": False}}
        return AVPerceptionResponse.model_validate(protect(value, selected[1])).model_dump(mode="json")
    except Exception as exc:
        if isinstance(exc, PerceptionBudgetExceeded):
            error = {"error": str(exc), "category": "EXECUTION_BUDGET_EXHAUSTED",
                     "hint": "Use the retained calls and reservations to size the exact workflow", "retryable": False}
        elif state["attempts"]:
            category, _, code = provider_failure(exc)
            error = {"error": f"Perception submission/result failed ({type(exc).__name__}); provider diagnostics withheld",
                     "category": category, "hint": "Inspect bounded attempt and usage receipts; no raw provider body is returned",
                     "retryable": False, "retry_after_seconds": None}
            if code is None and isinstance(exc, TimeoutError):
                error["category"] = "NETWORK_ERROR"
        else:
            error = make_tool_error(exc)
            error["retryable"] = False
        value = {**error, "source": state["source"], "windows": state["windows"], "timeline": state["timeline"],
                 "summaries": state["summaries"], "abstentions": state["abstentions"],
                 "execution": execution_report(request, budget, state, started), "request_sha256": state["request_sha256"]}
        return AVPerceptionFailure.model_validate(protect(value, selected[1])).model_dump(mode="json")
