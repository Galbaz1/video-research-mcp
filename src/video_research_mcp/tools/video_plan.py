"""Local dry planning and bounded inline-video preparation without provider calls."""

from __future__ import annotations

import hashlib

from google.genai import types

from ..config import get_config
from ..models.execution import ExecutionLimits
from ..media_identity import identify_source
from ..models.video import VideoResult
from ..video_window_metadata import window_description
from .video_core import _ANALYSIS_PREAMBLE
from .video_file import LARGE_FILE_THRESHOLD, _validate_video_path
from .video_url import _extract_video_id, _normalize_youtube_url, _video_content


def _plan_source(url: str | None, file_path: str | None) -> tuple[dict, list]:
    """Read a bounded original byte snapshot or identify an unfetched URL."""
    if url:
        _extract_video_id(url)
        source = {
            "kind": "remote_url",
            "uri": _normalize_youtube_url(url),
            "bytes": None,
            "sha256": None,
            "freshness": "unknown",
        }
        local = []
    else:
        path, mime = _validate_video_path(file_path)
        size = path.stat().st_size
        identity = identify_source(str(path), persist=False)
        if identity.state != "fresh":
            raise ValueError("Local source identity is unavailable for planning")
        digest = identity.digest
        source = {
            "kind": "local_file",
            "path": str(path),
            "bytes": size,
            "mime_type": mime,
            "sha256": digest,
            "freshness": "local_snapshot",
        }
        local = [{"path": str(path), "operation": "read original bytes", "bytes": size}]
    return source, local


def plan_video(
    *,
    url: str | None,
    file_path: str | None,
    instruction: str,
    limits: ExecutionLimits | None,
    strict_contract: bool,
    output_schema: dict | None = None,
    thinking_level: str = "high",
    video_metadata: types.VideoMetadata | None = None,
) -> dict:
    """Enumerate source reads/sends and unknowns without clients, uploads or inference."""
    cfg = get_config()
    source, local = _plan_source(url, file_path)
    blocked = []
    if limits and strict_contract:
        blocked.append(
            "Bounded execution supports the single analysis pipeline; strict artifacts require a separate plan"
        )
    if limits and source["kind"] == "local_file" and source["bytes"] >= LARGE_FILE_THRESHOLD:
        blocked.append("Bounded inline execution requires a file below the File API threshold")
    if limits and (
        limits.max_calls < 2
        or limits.max_windows < 2
        or limits.max_frames < 2 * limits.requested_frames
    ):
        blocked.append(
            "Execution budget exhausted before launch: counting and generation require two media transmissions"
        )
    schema = output_schema or VideoResult.model_json_schema()
    prompt = (
        instruction if output_schema else f"{_ANALYSIS_PREAMBLE}\n\nUser instruction: {instruction}"
    )
    return {
        "dry_run": True,
        "local_reads": local,
        "remote_payloads": [
            {
                "recipient": "configured Gemini account",
                "source": source,
                "prompt": prompt,
                "prompt_utf8_bytes": len(prompt.encode()),
                "response_schema": schema,
                "thinking_level": thinking_level,
                "video_metadata": video_metadata.model_dump(mode="json", exclude_none=True)
                if video_metadata is not None else None,
            }
        ],
        "models": [cfg.default_model] if limits else [cfg.default_model, cfg.flash_model],
        "limits": limits.model_dump() if limits else None,
        "requested_frames": limits.requested_frames if limits else None,
        "requested_windows": 1 if limits else None,
        "estimated_tokens": None,
        "estimated_cost_usd": None,
        "estimate_method": "unknown until explicit execution counts the prepared provider input",
        "optional_operations": []
        if limits
        else [
            "metadata optimizer for URLs",
            "context prewarm",
            "configured knowledge storage",
            "File API for large local files",
        ],
        "bounded_operations": ["count_tokens", "generate_content with metered retries"]
        if limits
        else None,
        "sampling_bound_scope": "requested static positions per transmission; observed decoding remains unknown",
        "network_calls": 0,
        "provider_calls": 0,
        "launch_blockers": blocked,
        "observed_coverage": "unknown",
        "analysis_window": window_description(video_metadata) if video_metadata is not None else None,
        "charge_bound_verified": False,
    }


def bounded_contents(plan: dict, instruction: str, limits: ExecutionLimits) -> types.Content:
    """Prepare only inline bytes or a URL; no File API or metadata enrichment."""
    if plan["launch_blockers"]:
        raise ValueError("; ".join(plan["launch_blockers"]))
    source = plan["remote_payloads"][0]["source"]
    if source["kind"] == "local_file":
        path, mime = _validate_video_path(source["path"])
        with path.open("rb") as stream:
            data = stream.read(LARGE_FILE_THRESHOLD)
        if (
            len(data) >= LARGE_FILE_THRESHOLD
            or hashlib.sha256(data).hexdigest() != source["sha256"]
        ):
            raise ValueError("Local source changed after planning or exceeds inline budget")
        media = types.Part(inline_data=types.Blob(data=data, mime_type=mime))
        contents = types.Content(parts=[media, types.Part(text=instruction)])
    else:
        contents = _video_content(source["uri"], instruction)
        media = contents.parts[0]
    media.media_processing = types.MediaProcessing.STATIC
    media.video_metadata = types.VideoMetadata(
        fps=limits.fps,
        start_offset=f"{limits.start_ms // 1000}.{limits.start_ms % 1000:03d}s",
        end_offset=f"{limits.end_ms // 1000}.{limits.end_ms % 1000:03d}s",
    )
    return contents
