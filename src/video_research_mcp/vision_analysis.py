"""Complete bounded vision workflows with explicit submission and source lineage."""

import asyncio
import json
from contextlib import AsyncExitStack

from .config import get_config
from .errors import make_tool_error
from .execution_budget import ExecutionBudget
from .models.vision import VisionFailure, VisionRequest, VisionResponse
from .native_media_results import native_operation
from .vision_preparation import (MAX_INLINE_BYTES, MAX_INLINE_IMAGES, MAX_TEMP_VIDEO_BYTES,
                                 prepare_sources, verify_prepared)
from .vision_provider import (backend_binding, compatible_inference, gemini_inference,
                              schema_and_prompt, selected_backend)
from .vision_regions import regions_and_crops
from .vision_upload import upload_videos


def _payload_receipt(parts, profile, calls):
    """Expose byte commitments and routes, excluding keys and base64 previews."""
    return [{"source_index": p["source_index"], "sha256": p["sha256"], "bytes": p["bytes"],
             "kind": p["kind"], "mime": p["mime"], "actual_seconds": p.get("actual_seconds"),
             "original_pts": p.get("original_pts"), "time_base": p.get("time_base"),
             "delivery": "dashscope_temporary" if p["kind"] == "video" else "inline_prepared_pixels",
             "inference_origin": "https://generativelanguage.googleapis.com" if profile is None else profile.base_url,
             "upload_policy_origin": profile.upload_policy_url if p["kind"] == "video" else None,
             "retention_verified": False, "upload_attempted": any(
                 c["kind"] == "video_upload" and c["receipt"]["source_index"] == p["source_index"]
                 for c in calls)} for p in parts]


def _execution(request, profile, budget, calls, planned):
    """Distinguish count/generation accounting from uncounted compatible image tokens."""
    if profile is None:
        report = budget.report()
    else:
        report = {"provider_calls": len(calls), "calls": calls, "input_tokens": None,
                  "input_token_limit_verified": False, "output_limit_requested": request.limits.max_output_tokens,
                  "cost_usd": None, "charge_bound_verified": False, "wire_retries": 0,
                  "prepared_images": budget.frames, "model_inference_attempts":
                  sum(c["kind"] == "chat_completions" for c in calls)}
    return {**report, "planned_calls": planned, "max_inline_images": MAX_INLINE_IMAGES,
            "max_inline_raw_bytes": MAX_INLINE_BYTES, "max_encoded_item_bytes": 10_000_000,
            "max_temporary_video_bytes": MAX_TEMP_VIDEO_BYTES, "submission_authorized": request.authorize_submission,
            "submission_within_call_limit": planned <= request.limits.max_calls,
            "cache_used": False, "continuous_watched_coverage": False}


def _validate_operation(request, operation):
    """Require source-specific operations and avoid automatic temporary-storage activation."""
    if operation not in {"vision_chat", "ocr", "grounding"}:
        raise ValueError("Unknown vision operation")
    if operation != "vision_chat" and any(s.kind == "video" for s in request.sources):
        raise ValueError("OCR/grounding require image or precise frame sources")
    if request.export_crops and operation != "grounding":
        raise ValueError("Crop export belongs to grounding")


def _backend_unchanged(request, selected):
    """Prevent a concurrent configuration or credential change from rebinding this call."""
    if selected_backend(request) != selected:
        raise ValueError("Selected vision backend/model/credential changed during the workflow")


async def _infer(request, profile, model, credential, temperature, schema, prompt, parts, budget, calls):
    """Submit once after the preflight plan and explicit workflow grant."""
    if not request.authorize_submission:
        raise PermissionError("Vision submission requires authorize_submission for this exact workflow")
    if profile is None:
        if not credential:
            raise PermissionError("Selected Gemini credential is absent")
        answer = await gemini_inference(request, parts, schema, prompt, model, credential, temperature, budget)
        reasons = budget.calls[-1].get("finish_reasons", []) if budget.calls else []
        if budget.violation or not reasons or any(reason != "STOP" for reason in reasons):
            raise ValueError("Vision generation termination or token reservation is unverified")
        return answer, []
    uploads = []
    if any(p["kind"] == "video" for p in parts):
        parts, uploads = await upload_videos(profile, credential, parts, calls, request.authorize_submission)
    answer = await compatible_inference(request, parts, schema, prompt, model, profile, credential, calls)
    return answer, uploads


async def _workflow(request, operation, profile, model, credential, temperature, schema, prompt, budget, state):
    """Join snapshots and invocation-owned preparation before any successful return."""
    selected = profile, model, credential, temperature
    async with native_operation() as generated, AsyncExitStack() as stack:
        prepared, parts = await prepare_sources(request, profile, stack, generated)
        state["parts"] = parts
        state["payload_receipt"] = _payload_receipt(parts, profile, state["calls"])
        budget.frames = sum(p["kind"] == "image" for p in parts)
        _, digest = backend_binding(request, profile, model, credential, temperature, schema, prompt, prepared, parts)
        state["request_sha256"] = digest
        planned = 2 if profile is None else 1 + 2 * sum(p["kind"] == "video" for p in parts)
        state["planned_calls"] = planned
        answer, uploads, regions = None, [], []
        await verify_prepared(prepared, parts)
        _backend_unchanged(request, selected)
        if not request.dry_run:
            if planned > request.limits.max_calls:
                raise ValueError("Vision call plan exceeds the declared maximum")
            state["inference_started"] = True
            answer, uploads = await _infer(request, profile, model, credential, temperature, schema, prompt, parts, budget, state["calls"])
            json.dumps(answer, allow_nan=False)
            await verify_prepared(prepared, parts)
            _backend_unchanged(request, selected)
            if request.output_schema is None:
                regions = await regions_and_crops(answer, request, prepared, generated)
            await verify_prepared(prepared, parts)
            state["payload_receipt"] = _payload_receipt(parts, profile, state["calls"])
        backend = {"name": request.backend, "model": model, "endpoint":
                   "https://generativelanguage.googleapis.com" if profile is None else profile.base_url,
                   "runtime": "existing_gemini" if profile is None else "configured_compatible_endpoint", "temperature": temperature,
                   "capability_quality_verified": False, "model_weight_license_verified": False}
        result = {"status": "planned" if request.dry_run else "complete", "operation": operation,
                  "backend": backend, "request_sha256": digest, "preparations": prepared,
                  "payload_receipt": state["payload_receipt"], "model_output": answer, "regions": regions,
                  "execution": _execution(request, profile, budget, state["calls"], planned), "uploads": uploads,
                  "provenance": {"model_output": "model_inference", "ocr_text": "model_inference" if operation == "ocr" else None,
                    "source_geometry": "deterministic_preparation", "factual_correctness_verified": False,
                    "object_correctness_verified": False, "human_review": "pending"}}
        result = VisionResponse.model_validate(result).model_dump(mode="json")
    return result


async def analyze_vision(request: VisionRequest, operation: str) -> dict:
    """Return lineage and usage uncertainty for success, dry plans and failed submissions."""
    request = VisionRequest.model_validate(request)
    state = {"calls": [], "payload_receipt": [], "request_sha256": None,
             "planned_calls": 0, "inference_started": False}
    budget = ExecutionBudget(request.limits)
    profile = None
    try:
        profile, model, credential, temperature = selected_backend(request)
        _validate_operation(request, operation)
        schema, prompt = schema_and_prompt(request, operation)
        budget.generation_check = lambda: _backend_unchanged(request, (profile, model, credential, temperature))
        async with asyncio.timeout(min(get_config().media_acquire_timeout_seconds, 120)):
            return await _workflow(request, operation, profile, model, credential, temperature, schema, prompt, budget, state)
    except Exception as exc:
        if state.get("parts"):
            state["payload_receipt"] = _payload_receipt(state["parts"], profile, state["calls"])
        if state["inference_started"] and not isinstance(exc, PermissionError):
            error = make_tool_error(RuntimeError(f"Vision submission/result failed ({type(exc).__name__}); payload and provider diagnostics are withheld"))
        else:
            error = make_tool_error(exc)
        error["retryable"] = False
        uploads = [c["receipt"] for c in state["calls"] if c["kind"] == "video_upload"]
        return VisionFailure(**error, execution=_execution(request, profile, budget, state["calls"], state["planned_calls"]),
            payload_receipt=state["payload_receipt"], request_sha256=state["request_sha256"], uploads=uploads).model_dump(mode="json")
