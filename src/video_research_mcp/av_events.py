"""Four bounded AV tasks with exact submitted support and retained incomplete populations."""

import asyncio
import hashlib
import time

from .av_event_support import grounding_selection, project_records, task_prompt
from .config import get_config
from .errors import make_tool_error
from .image_manifest import json_digest
from .media_perception import execution_report
from .media_perception_provider import (PerceptionBudget, PerceptionBudgetExceeded, infer_window,
                                        protect, provider_failure, selected_gemini)
from .models.av_events import (AnalyzeMusicRequest, AVEventsFailure, AVEventsResponse, CaptionEventsRequest,
                               CaptionWindowAnswer, CountEventsRequest, CountWindowAnswer,
                               GroundEventsRequest, GroundWindowAnswer, MusicWindowAnswer)


def _provenance():
    """Separate decoded support from unverified event, identity and musical semantics."""
    return {"records": "model_inference", "source_clock": "decoded_source_pts",
            "factual_correctness_verified": False, "semantic_accuracy_verified": False,
            "human_review": "pending", "live_semantic_acceptance": "unverified",
            "visual_sampling_may_miss_events": True, "continuous_watched_coverage": False,
            "cross_window_identity_merge": False, "counts": "retained_supported_record_population",
            "count_is_physical_event_truth": False, "scores_calibrated": False,
            "music_properties_and_boundaries": "model_inferred", "retained_artifact_paths": False}


def _state(request, task, selected):
    """Keep all planned windows and server populations before any possible submission."""
    return {"operation": {"caption": "media_caption_events", "count": "media_count_events",
            "ground": "media_ground_events", "music": "media_analyze_music"}[task], "task": task,
            "source": None, "windows": [], "records": [], "summaries": [], "abstentions": [],
            "attempts": [], "payload_bytes": 0, "request_sha256": None, "timeout_seconds": None,
            "backend": {"name": "gemini", "model": selected[0], "temperature": selected[2],
                        "endpoint": "https://generativelanguage.googleapis.com",
                        "delivery": "inline_pcm_wav" if task == "music" else "inline_sampled_frames_and_pcm_wav",
                        "quality_verified": False},
            "target": getattr(request, "target", None), "query": getattr(request, "query", None)}


def _validate_music(windows):
    """Refuse missing audio or any visual payload before an audio-only music dispatch."""
    for window in windows:
        if window["audio"] is None or not any(p["kind"] == "audio" for p in window["parts"]):
            raise ValueError("Music analysis requires actual selected decoded audio in every window")
        if window["frames"] or any(p["kind"] != "audio" for p in window["parts"]):
            raise ValueError("Music analysis is audio-only; visual payload preparation was refused")


async def _infer_all(request, selected, budget, state, windows, verify, schema, prompts):
    """Join complete supported window populations; a failed window never partly commits records."""
    for window, receipt, prompt in zip(windows, state["windows"], prompts):
        receipt["status"] = "running"
        try:
            answer = await infer_window(request, window, selected, budget, state["attempts"], verify,
                                        schema=schema, task_prompt=prompt)
            records = project_records(answer, window, state["source"], state["task"])
            state["records"].extend(records)
            state["summaries"].append(answer.summary)
            state["abstentions"].extend({"window_index": window["index"], "reason": r} for r in answer.abstentions)
            receipt.update(status="complete", outcome=answer.outcome, retained_records=len(records))
        except Exception:
            receipt["status"] = "failed"
            raise


async def _workflow(request, selected, budget, state, schema):
    """Reuse measured preparation and source/buffer rechecks for the complete invocation."""
    from .media_perception_prepare import prepare_media

    async with prepare_media(request) as (source, windows, verify):
        state["source"] = source
        state["windows"] = [{**{k: v for k, v in w.items() if k != "parts"}, "status": "planned"} for w in windows]
        state["payload_bytes"] = sum(w["payload_bytes"] for w in windows)
        budget.frames = sum(len(w["frames"]) for w in windows)
        prompts = [task_prompt(request, state["task"], w) for w in windows]
        state["request_sha256"] = json_digest({"request": request.model_dump(mode="json"), "task": state["task"],
            "protocol": 1, "output_schema": schema.model_json_schema(), "task_prompts": prompts,
            "model": selected[0], "credential_commitment": hashlib.sha256(selected[1].encode()).hexdigest(),
            "temperature": selected[2], "source": source, "windows": state["windows"]})
        if source["sha256"] != request.expected_source_sha256:
            raise ValueError("Prepared AV source differs from the exact requested revision")
        if state["task"] == "music":
            _validate_music(windows)
        await verify()
        if request.dry_run:
            return
        if not request.authorize_submission or not selected[1]:
            raise PermissionError("AV event submission requires an explicit workflow grant and configured Gemini account")
        if 2 * len(windows) > request.limits.max_calls:
            raise PerceptionBudgetExceeded("AV event count/generation plan exceeds the provider call budget")
        await _infer_all(request, selected, budget, state, windows, verify, schema, prompts)


def _result(request, budget, state, started, *, failed=False):
    """Represent planned, complete and incomplete populations without inventing a final count."""
    completed = sum(w["status"] == "complete" for w in state["windows"])
    planned = request.dry_run and not failed
    matches, population = [], None
    if state["task"] == "ground":
        matches, population = grounding_selection(state["records"], request.top_k, not planned and not failed)
        if planned:
            population["available"] = None
    outcome = ("partial" if completed else "error") if failed else ("planned" if planned else
               "events" if state["records"] else "abstained" if state["abstentions"] else "empty")
    countable = state["task"] == "count"
    return {"operation": state["operation"], "task": state["task"],
            "status": ("partial" if completed else "failed") if failed else "planned" if planned else "complete",
            "outcome": outcome, "source": state["source"], "backend": state["backend"],
            "request_sha256": state["request_sha256"], "windows": state["windows"], "records": state["records"],
            "matches": matches, "grounding_population": population,
            "count": len(state["records"]) if countable and outcome in {"events", "empty"} else None,
            "count_so_far": len(state["records"]) if countable and not planned else None,
            "target": state["target"], "query": state["query"], "summaries": state["summaries"],
            "abstentions": state["abstentions"], "execution": execution_report(request, budget, state, started),
            "provenance": _provenance()}


def _error(exc, state):
    """Withhold provider/result diagnostics, preserving local refusals and classified failures."""
    if isinstance(exc, PerceptionBudgetExceeded):
        return {"error": str(exc), "category": "EXECUTION_BUDGET_EXHAUSTED", "retryable": False,
                "hint": "Use retained reservations to size the exact workflow"}
    if state["attempts"]:
        category, _, _ = provider_failure(exc)
        if isinstance(exc, TimeoutError):
            category = "NETWORK_ERROR"
        return {"error": f"AV event submission/result failed ({type(exc).__name__}); diagnostics withheld",
                "category": category, "retryable": False,
                "hint": "Inspect bounded attempts, usage and retained incomplete windows"}
    return {**make_tool_error(exc), "retryable": False}


async def _run(request, task, schema):
    """Apply one shared operation deadline and propagate cancellation through owned cleanup."""
    selected, started = selected_gemini(), time.monotonic()
    budget, state = PerceptionBudget(request.limits, selected), _state(request, task, selected)
    try:
        timeout = min(request.limits.timeout_seconds, get_config().media_acquire_timeout_seconds)
        state["timeout_seconds"] = timeout
        async with asyncio.timeout(timeout):
            await _workflow(request, selected, budget, state, schema)
        value = _result(request, budget, state, started)
        return AVEventsResponse.model_validate(protect(value, selected[1])).model_dump(mode="json")
    except Exception as exc:
        value = {**_error(exc, state), **_result(request, budget, state, started, failed=True)}
        return AVEventsFailure.model_validate(protect(value, selected[1])).model_dump(mode="json")


async def caption_events(request: CaptionEventsRequest) -> dict:
    """Describe supported audio, visual and fused occurrences with exact submitted lineage."""
    return await _run(CaptionEventsRequest.model_validate(request), "caption", CaptionWindowAnswer)


async def count_events(request: CountEventsRequest) -> dict:
    """Count admitted occurrence records while retaining incomplete and abstained populations."""
    return await _run(CountEventsRequest.model_validate(request), "count", CountWindowAnswer)


async def ground_events(request: GroundEventsRequest) -> dict:
    """Retain all supported matches and disclose the ranked top-k population separately."""
    return await _run(GroundEventsRequest.model_validate(request), "ground", GroundWindowAnswer)


async def analyze_music(request: AnalyzeMusicRequest) -> dict:
    """Analyze timed audio-only music sections without treating inferred labels as measurements."""
    return await _run(AnalyzeMusicRequest.model_validate(request), "music", MusicWindowAnswer)
