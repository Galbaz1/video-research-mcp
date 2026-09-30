"""Freeze bounded local source selection without provider calls or decoding claims."""

from __future__ import annotations

import hashlib
import json
import math

from .client import _resolve_thinking_level
from .config import get_config, supports_sampling, validate_model_thinking
from .media_local_io import _copy_hash
from .models.video import VideoResult
from .models.video_windows import WindowAnalysisRequest, WindowRunLimits
from .research_jobs import account_scope
from .tools.video_core import _ANALYSIS_PREAMBLE
from .tools.video_file import LARGE_FILE_THRESHOLD, _validate_video_path
from .tools.video_url import _extract_video_id, _normalize_youtube_url


def fingerprint(value) -> str:
    """Commit finite Unicode JSON using a stable full SHA-256."""
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def runtime_settings(thinking_level: str) -> dict:
    """Bind the current model/account and actual generation settings without secrets."""
    cfg = get_config()
    thinking = _resolve_thinking_level(thinking_level)
    validate_model_thinking(cfg.default_model, thinking)
    return {
        "account_scope": account_scope(),
        "model": cfg.default_model,
        "thinking_level": thinking,
        "configured_temperature": cfg.default_temperature,
        "effective_temperature": cfg.default_temperature
        if supports_sampling(cfg.default_model)
        else None,
    }


def window_prompt(instruction: str, start_ms: int, end_ms: int) -> str:
    """Keep timestamps anchored to the original source rather than rebasing clips."""
    return (
        f"{instruction}\n\nRequested source window: [{start_ms}, {end_ms}) milliseconds. "
        "Keep output timestamps on the original source timeline. Requested sampling "
        "does not establish complete observed or factual coverage."
    )


def _windows(request: WindowAnalysisRequest, fps: float) -> list[dict]:
    return [
        {
            "index": index,
            "start_ms": start,
            "end_ms": min(start + request.window_ms, request.end_ms),
            "requested_frames": math.ceil(
                (min(start + request.window_ms, request.end_ms) - start) * fps / 1000
            ),
            "prompt": window_prompt(
                request.instruction, start, min(start + request.window_ms, request.end_ms)
            ),
        }
        for index, start in enumerate(range(request.start_ms, request.end_ms, request.window_ms))
    ]


def _source(request: WindowAnalysisRequest) -> dict:
    """Commit bounded local bytes or only a canonical unfetched YouTube locator."""
    if request.url is not None:
        return {
            "kind": "remote_url",
            "uri": _normalize_youtube_url(request.url),
            "video_id": _extract_video_id(request.url),
            "sha256": None,
            "bytes": None,
            "freshness": "unknown",
        }
    path, mime = _validate_video_path(request.file_path)
    digest, size = _copy_hash(path)
    return {
        "kind": "local_file",
        "path": str(path),
        "sha256": digest,
        "bytes": size,
        "mime_type": mime,
        "freshness": "local_snapshot",
    }


def plan_windows(request: WindowAnalysisRequest, limits: WindowRunLimits) -> dict:
    """Plan contiguous non-overlapping source windows without contacting a provider.

    Args:
        request: Strict explicit local interval and analysis settings.
        limits: Limits for the initial run, including requested frame transmissions.

    Returns:
        Source/settings commitments, fixed sampling and observable preparation scope.
    """
    request = WindowAnalysisRequest.model_validate(request)
    limits = WindowRunLimits.model_validate(limits)
    source = _source(request)
    count = (request.end_ms - request.start_ms + request.window_ms - 1) // request.window_ms
    frames_each = max(1, limits.max_frames // (2 * count))
    density = min(
        1.0, frames_each * 1000 / min(request.window_ms, request.end_ms - request.start_ms)
    )
    fps = (
        request.fps
        if request.fps is not None
        else (density if density == 1 else math.nextafter(density, 0.0))
    )
    selection = request.model_copy(
        update={"file_path": source.get("path"), "url": source.get("uri")}
    ).model_dump(mode="json")
    schema = request.output_schema or VideoResult.model_json_schema()
    plan = {
        "request": selection,
        "source": source,
        "runtime": runtime_settings(request.thinking_level),
        "response_schema": schema,
        "schema_sha256": fingerprint(schema),
        "prompt_preamble_sha256": fingerprint(
            _ANALYSIS_PREAMBLE if not request.output_schema else ""
        ),
        "fps": fps,
        "sampling_method": "explicit"
        if request.fps
        else "uniform_density_from_initial_frame_budget",
        "windows": _windows(request, fps),
        "preparation": {
            "local_read_bytes": source["bytes"] if source["kind"] == "local_file" else 0,
            "provider_route": "direct YouTube URL"
            if source["kind"] == "remote_url"
            else "File API upload/cache validation"
            if source["bytes"] >= LARGE_FILE_THRESHOLD
            else "inline original bytes",
            "generation_budget_scope": "count_tokens and generate_content transmissions only; File API preparation is separately observable and excluded",
            "provider_calls": 0,
            "uploaded_uri_freshness": "unknown",
        },
        "timestamp_origin": "original_source_milliseconds",
        "observed_coverage": "unknown",
        "duration_verified": False,
    }
    return {**plan, "plan_sha256": fingerprint(plan)}


def validate_plan(plan: dict) -> None:
    """Reject changed plan, source or effective settings before preparation/inference."""
    frozen = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if fingerprint(frozen) != plan["plan_sha256"]:
        raise ValueError("Window plan commitment changed")
    request = WindowAnalysisRequest.model_validate(plan["request"])
    WindowAnalysisRequest.model_validate({**plan["request"], "fps": plan["fps"]})
    if (
        plan["response_schema"] != (request.output_schema or VideoResult.model_json_schema())
        or fingerprint(plan["response_schema"]) != plan["schema_sha256"]
    ):
        raise ValueError("Window response schema differs from the frozen request")
    if _windows(request, plan["fps"]) != plan["windows"]:
        raise ValueError("Window selection differs from the frozen source interval")
    if runtime_settings(request.thinking_level) != plan["runtime"]:
        raise ValueError("Window account/model/settings changed")
    if _source(request) != plan["source"]:
        raise ValueError("Window original source changed or became unavailable")
