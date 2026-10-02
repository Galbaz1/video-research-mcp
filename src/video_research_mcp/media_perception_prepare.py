"""Ephemeral exact-source audio/frame windows for one bounded perception invocation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import math
from pathlib import Path
import time

from .audio_assets import audio_source, export_audio
from .config import get_config
from .media_frames import _source_clock, sample_frames
from .media_probe import probe_snapshot
from .media_snapshot import snapshot
from .models.media_perception import AVPerceptionRequest
from .models.scene_assets import AudioExportRequest
from .native_media_results import _discard_views
from .vision_preparation import read_payload


def _selection(request, source: dict) -> list[dict]:
    """Resolve only observed source extents and bound every window before artifact preparation."""
    video = source["selected_media_type"] == "video"
    extent = _source_clock(source)[0] if video else source["audio_end_seconds"]
    end = request.end_seconds if request.end_seconds is not None else extent
    if end is None or not math.isfinite(end):
        raise ValueError("Whole/remaining perception requires a known finite presentation end; supply an explicit end")
    if extent is not None and end > extent + 1e-6:
        raise ValueError("Perception selection ends outside the source presentation extent")
    span = end - request.start_seconds
    if not 0 < span <= 120:
        raise ValueError("Perception selection must be positive and at most120 seconds")
    count = math.ceil(span / request.window_seconds)
    if count > request.limits.max_windows:
        raise ValueError("Perception selection exceeds the requested window budget")
    windows = []
    for index in range(count):
        start = request.start_seconds + index * request.window_seconds
        windows.append({"index": index, "start_seconds": start,
                        "end_seconds": min(end, start + request.window_seconds)})
    frames = sum(min(request.max_frames_per_window, math.ceil(
        (w["end_seconds"] - w["start_seconds"]) * request.fps)) for w in windows) if video else 0
    if frames > request.limits.max_frames:
        raise ValueError("Perception frame reservation exceeds the aggregate frame budget")
    return windows


async def _source(owned, request) -> dict:
    source = await probe_snapshot(owned)
    video = source["stream_index"] is not None
    audio = any(s.get("codec_type") == "audio" for s in source["streams"])
    mode = ("video" if video else "audio") if request.media_type == "auto" else request.media_type
    if (mode == "video" and not video) or (mode == "audio" and not audio):
        raise ValueError("Selected media type has no matching source stream")
    if audio:
        source = await audio_source(owned)
    return {**source, "selected_media_type": mode, "has_video": video, "has_audio": audio}


def _bound_source(result: dict, owned) -> None:
    source = result["source"]
    if (source["sha256"], source["bytes"], source["path"]) != (owned.sha256, owned.size, str(owned.original)):
        raise ValueError("Nested preparation differs from the frozen original source")


def _part(artifact: dict, kind: str, totals: dict, limits, *, actual_seconds=None,
          original_pts=None, time_base=None) -> dict:
    """Reserve bytes before reading an exact artifact into an immutable transmitted buffer."""
    size = artifact["bytes"]
    if type(size) is not int or size <= 0 or totals["bytes"] + size > limits.max_payload_bytes:
        raise ValueError("Perception payload exceeds the aggregate byte budget")
    if 2 * (totals["bytes"] + size) > limits.max_transmitted_bytes:
        raise ValueError("Count and generation transmissions exceed the declared byte budget")
    data = read_payload(artifact)
    totals["bytes"] += size
    return {"kind": kind, "mime": "image/png" if kind == "image" else "audio/wav",
            "sha256": artifact["sha256"], "bytes": size, "actual_seconds": actual_seconds,
            "original_pts": original_pts, "time_base": time_base, "data": data}


async def _visual(owned, request, window, generated, totals) -> tuple[list, list, dict]:
    """Keep every returned frame and expose sampled-point gaps without watched intervals."""
    try:
        result = await sample_frames(str(owned.original), start_seconds=window["start_seconds"],
            end_seconds=window["end_seconds"], fps=request.fps, max_frames=request.max_frames_per_window,
            max_pixels=request.max_pixels, expected_source_sha256=owned.sha256)
    except ValueError as error:
        if str(error) != "No decoded frame matches the requested presentation range":
            raise
        return [], [], {"status": "absent", "coverage": {"sampled_points": [], "decoded_count": 0,
                       "complete": False, "stop_reason": "no_source_frame_points", "watched_intervals": []},
                       "unobserved_between_sampled_points": True, "continuous_watched_coverage": False}
    generated.append(result)
    _bound_source(result, owned)
    records, parts = [], []
    for frame in result["frames"]:
        if not 1 <= frame["width"] * frame["height"] <= request.max_pixels:
            raise ValueError("Prepared frame exceeds the requested pixel budget")
        totals["frames"] += 1
        if totals["frames"] > request.limits.max_frames or len(records) >= request.max_frames_per_window:
            raise ValueError("Prepared frames exceed the requested frame budget")
        if not window["start_seconds"] <= frame["actual_seconds"] < window["end_seconds"]:
            raise ValueError("Prepared frame lies outside its half-open source window")
        parts.append(_part(frame, "image", totals, request.limits, actual_seconds=frame["actual_seconds"],
                           original_pts=frame["original_pts"], time_base=frame["time_base"]))
        records.append({key: value for key, value in frame.items() if key != "path"})
    return records, parts, {"status": result["status"], "coverage": result["coverage"],
                           "unobserved_between_sampled_points": True, "continuous_watched_coverage": False}


async def _audio(owned, source, request, window, generated, totals) -> tuple[dict | None, list, str]:
    if not source["has_audio"]:
        return None, [], "source_has_no_audio"
    start = max(window["start_seconds"], source["first_audio_seconds"])
    end = window["end_seconds"]
    if source["audio_end_seconds"] is not None:
        end = min(end, source["audio_end_seconds"])
    if end <= start:
        return None, [], "outside_source_audio_track"
    result = await export_audio(AudioExportRequest(file_path=str(owned.original),
        expected_source_sha256=owned.sha256, start_seconds=start, end_seconds=end))
    generated.append(result)
    _bound_source(result, owned)
    selected = result["selected_window"]
    part = _part(result["artifact"], "audio", totals, request.limits,
                 actual_seconds=selected["start_seconds"], time_base="1/16000")
    metadata = {key: result[key] for key in ("requested_window", "selected_window", "source_audio_clock",
                                           "output", "clock_relationship")}
    metadata["artifact"] = {key: value for key, value in result["artifact"].items() if key != "path"}
    status = "complete_selected_audio" if (abs(selected["start_seconds"] - window["start_seconds"]) <= 1 / 16000
        and abs(selected["end_seconds"] - window["end_seconds"]) <= 1 / 16000) else "partial_source_audio_overlap"
    return metadata, [part], status


async def _windows(owned, source, request, generated) -> list[dict]:
    windows, totals = _selection(request, source), {"bytes": 0, "frames": 0}
    for window in windows:
        frames, parts, visual = [], [], {"status": "not_selected", "coverage": None,
            "unobserved_between_sampled_points": True, "continuous_watched_coverage": False}
        if source["selected_media_type"] == "video":
            frames, parts, visual = await _visual(owned, request, window, generated, totals)
        audio, audio_parts, status = await _audio(owned, source, request, window, generated, totals)
        parts.extend(audio_parts)
        if not parts:
            raise ValueError("Perception window contains no measured audio or visual payload")
        window.update(frames=frames, audio=audio, visual_sampling=visual, audio_status=status,
                      parts=parts, payload_bytes=sum(part["bytes"] for part in parts), watched_intervals=[])
    return windows


@asynccontextmanager
async def prepare_media(request: AVPerceptionRequest):
    """Retain the original revision through inference and discard all invocation-owned views."""
    request = AVPerceptionRequest.model_validate(request)
    cfg, generated = get_config(), []
    base = Path(cfg.cache_dir).expanduser().resolve() / "media" / "views"
    timeout = min(cfg.media_acquire_timeout_seconds, request.limits.timeout_seconds)
    deadline = time.monotonic() + timeout
    try:
        async with asyncio.timeout(timeout), snapshot(request.file_path, request.expected_source_sha256) as owned:
            owned.deadline = min(owned.deadline, deadline)
            source = await _source(owned, request)
            _bound_source({"source": source}, owned)
            windows = await _windows(owned, source, request, generated)

            async def verify():
                """Recheck originals and actual retained artifacts before/after provider work."""
                owned.remaining()
                await owned.verify()
                for result in generated:
                    _bound_source(result, owned)
                    artifacts = result.get("frames", []) + result.get("artifacts", [])
                    for artifact in artifacts:
                        read_payload(artifact)
                for window in windows:
                    for part in window["parts"]:
                        if type(part["data"]) is not bytes or len(part["data"]) != part["bytes"] or hashlib.sha256(part["data"]).hexdigest() != part["sha256"]:
                            raise ValueError("Immutable perception payload commitment changed")

            await verify()
            yield source, windows, verify
            await verify()
    finally:
        _discard_views(generated, base)
