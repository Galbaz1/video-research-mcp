"""Actual decoded PTS evidence from bounded source-relative local video windows."""

from __future__ import annotations

import math
import re
from fractions import Fraction
from pathlib import Path

from .media_image_read import (
    MAX_ARTIFACT_BYTES, MAX_FRAME_PIXELS, MAX_OUTPUT_PIXELS, coverage, decode_command,
    geometry, limits, png_artifact, validate_pixels,
)
from .media_probe import probe_snapshot
from .media_process import run_media_process
from .media_snapshot import snapshot


def _seconds(value: float, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return float(value)


def _source_clock(source: dict) -> tuple[float, float]:
    duration = source.get("presentation_end_seconds", source["duration_seconds"])
    start = source["container_start_seconds"]
    if duration is None or duration <= 0 or start is None or source["time_base"] is None:
        raise ValueError("Video duration or presentation clock is unavailable")
    if source["stream_index"] is None:
        raise ValueError("Source has no supported video stream")
    return duration, start


def _showinfo_records(stderr: bytes) -> list[tuple[str, str]]:
    """Ignore metadata lookalikes; accept only whole named filter logger records."""
    records = []
    for line in stderr.decode("utf-8", errors="replace").split("\n"):
        match = re.fullmatch(r"(\[Parsed_showinfo_\d+ @ (?:0x)?[0-9a-fA-F]+\])\s+(.*)", line)
        if match:
            records.append((match[1], match[2]))
    return records


def _pts(stderr: bytes, expected_time_base: str) -> tuple[str, dict[int, int]]:
    """Bind one genuine decoder clock to inspected source time units and unique PTS."""
    records = _showinfo_records(stderr)
    clocks = [(identity, match[1]) for identity, text in records
              if (match := re.fullmatch(r"config in time_base:\s*(\d+/\d+),.*", text))]
    if not clocks:
        raise ValueError("Decoded presentation time base could not be verified")
    if len(clocks) != 1 or len({identity for identity, _ in records}) != 1:
        raise ValueError("Ambiguous decoded showinfo filter or presentation clock")
    time_base = clocks[0][1]
    if Fraction(time_base) <= 0 or Fraction(time_base) != Fraction(expected_time_base):
        raise ValueError("Decoded presentation time base differs from the inspected source clock")
    points = {}
    for _, text in records:
        if not text.startswith("n:"):
            continue
        match = re.match(r"n:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*([-+\d.eE]+)(?:\s|$)", text)
        if not match:
            raise ValueError("Decoded showinfo frame has a missing or invalid PTS")
        index, pts, reported = int(match[1]), int(match[2]), float(match[3])
        if index != len(points):
            raise ValueError("Ambiguous or noncontiguous decoded showinfo frame index")
        actual = float(pts * Fraction(time_base))
        if not math.isfinite(reported) or not math.isclose(reported, actual, rel_tol=5e-6, abs_tol=5e-6):
            raise ValueError("Decoded showinfo PTS and reported clock are inconsistent")
        points[index] = pts
    return time_base, points


def _actual_seconds(pts: int, time_base: str, source: dict) -> float:
    """Reject decoder points inconsistent with the inspected source presentation extent."""
    actual = float(pts * Fraction(time_base)) - source["container_start_seconds"]
    duration, _ = _source_clock(source)
    if not math.isfinite(actual) or not 0 <= actual < duration:
        raise ValueError("Decoded presentation timestamp is outside the source extent")
    return actual


def _render_count(width: int, height: int, maximum: int) -> tuple[int, str | None]:
    """Reserve a conservative PNG byte ceiling before producing multiple artifacts."""
    pixels = width * height
    pixel_count = MAX_OUTPUT_PIXELS // pixels
    byte_count = MAX_ARTIFACT_BYTES // (4 * pixels + 65536)
    count = min(maximum, pixel_count, byte_count)
    if count < 1:
        raise ValueError("Output resolution exceeds the aggregate artifact budget")
    reason = "artifact_byte_reservation" if byte_count < maximum else None
    if pixel_count < min(maximum, byte_count):
        reason = "aggregate_pixel_budget"
    return count, reason


async def _render(owned, source, expression, maximum, max_pixels, crop_box, *, before_input=None):
    width, height, transform = geometry(source, max_pixels, crop_box)
    count, reason = _render_count(width, height, maximum)
    command = decode_command(owned, source, before_input=before_input)
    command.extend(["-vf", f"select='{expression}',showinfo,{transform}", "-frames:v", str(count),
                    "-fps_mode", "passthrough", "-threads", "1",
                    str(owned.directory / "frame%03d.png")])
    _, stderr = await run_media_process(command, owned.remaining())
    time_base, pts = _pts(stderr, source["time_base"])
    files = sorted(owned.directory.glob("frame*.png"))
    if not files:
        raise ValueError("No decoded frame matches the requested presentation range")
    frames = []
    for index, path in enumerate(files):
        if index not in pts:
            raise ValueError("Emitted frame has no verified decoded presentation timestamp")
        artifact = await png_artifact(path)
        actual = _actual_seconds(pts[index], time_base, source)
        frames.append({**artifact, "actual_seconds": actual, "original_pts": pts[index],
                       "time_base": time_base, "crop_box": list(crop_box) if crop_box else None})
    if sum(f["bytes"] for f in frames) > MAX_ARTIFACT_BYTES:
        raise ValueError("Native frames exceed the aggregate artifact byte budget")
    return frames, count, reason, len(pts) > len(files)


async def frame_at(file_path: str, *, time_seconds: float, max_pixels: int = MAX_FRAME_PIXELS,
                   crop_box=None, selection: str = "precise",
                   expected_source_sha256: str | None = None) -> dict:
    """Return first decoded frame at/after a point, or an explicit keyframe approximation."""
    requested = _seconds(time_seconds, "time_seconds")
    validate_pixels(max_pixels)
    if selection not in {"precise", "keyframe", "keyframes"}:
        raise ValueError("selection must be precise or keyframe")
    async with snapshot(file_path, expected_source_sha256) as owned:
        source = await probe_snapshot(owned)
        duration, start = _source_clock(source)
        if requested >= duration:
            raise ValueError("time_seconds is outside the source duration")
        approximate = selection != "precise"
        expression = "1" if approximate else f"gte(t,{requested + start:.12f})"
        options = ["-ss", str(requested), "-noaccurate_seek", "-skip_frame", "nokey"] if approximate else None
        frames, _, _, _ = await _render(owned, source, expression, 2 if approximate else 1,
                                        max_pixels, crop_box, before_input=options)
        candidates = [f["actual_seconds"] for f in frames]
        frame = min(frames, key=lambda f: (abs(f["actual_seconds"] - requested), f["actual_seconds"]))
        if not approximate and frame["actual_seconds"] + 1e-9 < requested:
            raise ValueError("Decoded frame precedes the requested precise presentation point")
        for candidate in frames:
            if candidate is not frame:
                Path(candidate["path"]).unlink()
        method = "nearest_of_first_two_keyframes_after_index_seek" if approximate else "first_decoded_at_or_after"
        frame.update(requested_seconds=requested, delta_seconds=frame["actual_seconds"] - requested,
                     approximate=approximate, selection_method=method)
        return {"source": source, "frames": [frame], "coverage": coverage([frame]),
                "status": "complete", "limits": {**limits(), "keyframe_candidates_seconds": candidates if approximate else [],
                "keyframe_global_nearest_verified": False if approximate else None}}


async def sample_frames(file_path: str, *, start_seconds: float = 0, end_seconds: float | None = None,
                        fps: float = 1, max_frames: int = 48, max_pixels: int = MAX_FRAME_PIXELS,
                        crop_box=None, selection: str = "uniform") -> dict:
    """Sample a half-open source window without synthesizing frame timestamps or deduplication."""
    start = _seconds(start_seconds, "start_seconds")
    end = _seconds(end_seconds, "end_seconds") if end_seconds is not None else None
    if end is not None and end <= start:
        raise ValueError("end_seconds must be greater than start_seconds")
    if type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 30:
        raise ValueError("fps must be finite and between 0 and 30")
    if type(max_frames) is not int or not 1 <= max_frames <= 48:
        raise ValueError("max_frames must be between 1 and 48")
    validate_pixels(max_pixels)
    if selection not in {"uniform", "scene", "keyframe", "keyframes"}:
        raise ValueError("selection must be uniform, scene or keyframe")
    async with snapshot(file_path) as owned:
        source = await probe_snapshot(owned)
        duration, offset = _source_clock(source)
        end = duration if end is None else end
        if start >= duration or end > duration:
            raise ValueError("Requested window is outside the source duration")
        window = {"start_seconds": start, "end_seconds": end}
        expression = f"gte(t,{start + offset:.12f})*lt(t,{end + offset:.12f})"
        interval = f"(isnan(prev_selected_t)+gte(t-prev_selected_t,{1 / fps - 1e-9:.12f}))"
        if selection == "scene":
            expression += "*(isnan(prev_selected_t)+gt(scene,0.3))"
        elif selection in {"keyframe", "keyframes"}:
            expression += "*eq(key,1)"
        frames, count, reserved_reason, _ = await _render(
            owned, source, expression + "*" + interval, max_frames, max_pixels, crop_box)
        for frame in frames:
            if not start - 1e-9 <= frame["actual_seconds"] < end:
                raise ValueError("Decoded frame is outside the requested source window")
            frame.update(requested_seconds=None, delta_seconds=None, approximate=False,
                         selection_method={"uniform": "actual_pts_minimum_spacing", "scene": "scene_threshold_0.3",
                                           "keyframe": "decoded_keyframes", "keyframes": "decoded_keyframes"}[selection])
        stop = (reserved_reason or "frame_budget") if len(frames) == count else None
        return {"source": source, "frames": frames, "coverage": coverage(frames, window, stop),
                "status": "partial" if stop else "complete", "limits": {**limits(),
                "requested_fps": fps, "requested_max_frames": max_frames, "effective_frame_limit": count,
                "deduplicated_frames": 0, "sampling_grid": "first_then_actual_pts_minimum_spacing"}}
