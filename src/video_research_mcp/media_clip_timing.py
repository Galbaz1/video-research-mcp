"""Bounded decoded source/output clock verification for short source clips."""

from __future__ import annotations

import json
import math
import re
from fractions import Fraction

from .media_frames import _actual_seconds, _pts
from .media_probe import FORMATS, binary
from .media_process import run_media_process

MAX_CLIP_FRAMES = 256


def source_frames(stderr: bytes, source: dict, start: float, end: float) -> list[dict]:
    """Require a bounded strictly ordered set of original PTS inside the half-open window."""
    clock, points = _pts(stderr, source["time_base"])
    if not 1 <= len(points) <= MAX_CLIP_FRAMES:
        raise ValueError("Clip must contain between 1 and 256 decoded source frames")
    result = [{"original_pts": pts, "time_base": clock,
               "actual_seconds": _actual_seconds(pts, clock, source)} for pts in points.values()]
    times = [item["actual_seconds"] for item in result]
    if any(not start - 1e-9 <= value < end for value in times):
        raise ValueError("Decoded clip frame is outside the requested half-open interval")
    if any(b <= a or b - a < 1 / 30 - 1e-6 for a, b in zip(times, times[1:])):
        raise ValueError("Decoded clip frame clock is unordered or exceeds 30 FPS")
    return result


def source_audio(stderr: bytes, offset: float, start: float, end: float) -> dict:
    """Read exact named audio filter frames after trim, before resetting their timestamps."""
    frames, identities = [], set()
    pattern = r"(\[Parsed_ashowinfo_\d+ @ (?:0x)?[0-9a-fA-F]+\])\s+(.*)"
    for line in stderr.decode("utf-8", errors="replace").split("\n"):
        match = re.fullmatch(pattern, line)
        if not match:
            continue
        identities.add(match[1])
        values = dict(re.findall(r"\b(n|pts|pts_time|rate|nb_samples):\s*([^\s]+)", match[2]))
        if set(values) != {"n", "pts", "pts_time", "rate", "nb_samples"}:
            raise ValueError("Decoded audio frame has incomplete timing fields")
        n, pts, rate, samples = (int(values[k]) for k in ("n", "pts", "rate", "nb_samples"))
        seconds = pts / rate if rate > 0 else math.nan
        if n != len(frames) or not 1 <= rate <= 48000 or not 1 <= samples <= 65536:
            raise ValueError("Decoded audio clock/count exceeds the clip contract")
        if not math.isclose(seconds, float(values["pts_time"]), rel_tol=5e-6, abs_tol=5e-6):
            raise ValueError("Decoded audio PTS clock is inconsistent")
        frames.append({"pts": pts, "seconds": seconds - offset,
                       "end_seconds": seconds - offset + samples / rate,
                       "sample_rate": rate, "nb_samples": samples})
    if len(identities) != 1 or not 1 <= len(frames) <= 4096:
        raise ValueError("Decoded source audio timing is absent, ambiguous or over budget")
    if any(f["seconds"] < start - 1e-6 or f["end_seconds"] > end + 1e-6 for f in frames):
        raise ValueError("Decoded source audio is outside the requested interval")
    if any(b["seconds"] < a["end_seconds"] - 1e-6 for a, b in zip(frames, frames[1:])):
        raise ValueError("Decoded source audio frames have overlapping or unordered clocks")
    return audio_summary(frames, "decoded_filter_pts_sample_rate")


def audio_summary(frames: list[dict], method: str) -> dict:
    """Retain observed endpoint clocks and the final decoded sample duration."""
    first, last = frames[0], frames[-1]
    return {"first_seconds": first["seconds"], "last_seconds": last["seconds"],
            "end_seconds": last["end_seconds"], "first_pts": first["pts"],
            "last_pts": last["pts"], "sample_rate": last["sample_rate"],
            "last_frame_samples": last["nb_samples"], "decoded_frame_count": len(frames),
            "method": method}


async def decoded_output(path, owned) -> dict:
    """Decode the byte-bounded encoded artifact, retaining actual frame/sample clocks."""
    command = [binary("ffprobe"), "-v", "error", "-max_alloc", "67108864", "-max_pixels", "1000000",
               "-threads", "1", "-protocol_whitelist", "file", "-format_whitelist", FORMATS,
               "-show_format", "-show_streams", "-show_frames", "-show_entries",
               "format=duration:stream=index,codec_type,codec_name,width,height,time_base,sample_rate:"
               "frame=media_type,stream_index,pts,pts_time,nb_samples", "-of", "json", str(path)]
    stdout, _ = await run_media_process(command, owned.remaining())
    info = json.loads(stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video or not 1 <= video.get("width", 0) * video.get("height", 0) <= 1_000_000:
        raise ValueError("Encoded clip has no bounded video stream")
    rows = [f for f in info.get("frames", []) if f.get("stream_index") == video["index"]]
    clock = Fraction(video["time_base"])
    if not 1 <= len(rows) <= MAX_CLIP_FRAMES or clock <= 0:
        raise ValueError("Encoded clip has an invalid decoded frame count or time base")
    points = [int(frame["pts"]) for frame in rows]
    times = [float(value * clock) for value in points]
    if any(not math.isclose(t, float(f["pts_time"]), abs_tol=5e-6) for t, f in zip(times, rows)):
        raise ValueError("Encoded clip frame PTS and reported clock are inconsistent")
    duration = float(info["format"]["duration"])
    if not math.isfinite(duration) or not 0 < duration <= 61 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Encoded clip duration/clock is outside the bounded contract")
    output = {"duration_seconds": duration, "frame_count": len(points), "width": video["width"],
              "height": video["height"], "first_frame_seconds": times[0], "last_frame_seconds": times[-1],
              "decoded_frame_seconds": times, "decoded_frame_pts": points,
              "time_base": video["time_base"], "video_codec": video["codec_name"], "frame_timing_verified": True}
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return {"output": output, "audio": _output_audio(info.get("frames", []), audio)}


def _output_audio(rows: list[dict], stream: dict | None) -> dict | None:
    """Use decoded samples rather than container audio-duration metadata."""
    if stream is None:
        return None
    clock, rate = Fraction(stream["time_base"]), int(stream["sample_rate"])
    selected = [f for f in rows if f.get("stream_index") == stream["index"]]
    if not 1 <= len(selected) <= 4096 or not 1 <= rate <= 48000 or clock <= 0:
        raise ValueError("Encoded audio decoded sample count/rate is invalid")
    frames = []
    for f in selected:
        pts, samples = int(f["pts"]), int(f["nb_samples"])
        seconds = float(pts * clock)
        if not math.isclose(seconds, float(f["pts_time"]), abs_tol=5e-6) or not 1 <= samples <= 65536:
            raise ValueError("Encoded audio has inconsistent decoded PTS/sample count")
        frames.append({"pts": pts, "seconds": seconds, "end_seconds": seconds + samples / rate,
                       "sample_rate": rate, "nb_samples": samples})
    if any(b["seconds"] < a["end_seconds"] - 1e-6 for a, b in zip(frames, frames[1:])):
        raise ValueError("Encoded audio has overlapping or unordered clocks")
    return {**audio_summary(frames, "decoded_output_pts_and_samples"), "time_base": stream["time_base"]}


def verify_output(measured: dict, frames: list[dict], start: float, width: int, height: int) -> None:
    """Reject early size-limit completion, frame drops, timestamp shifts and dimension changes."""
    output = measured["output"]
    expected = [f["actual_seconds"] - start for f in frames]
    tolerance = max(float(Fraction(output["time_base"])), 1e-6)
    if output["frame_count"] != len(expected):
        raise ValueError("Encoded clip is truncated or dropped selected source frames")
    if any(abs(actual - target) > tolerance for actual, target in zip(output["decoded_frame_seconds"], expected)):
        raise ValueError("Encoded clip timing does not match selected original source PTS")
    if (output["width"], output["height"]) != (width, height):
        raise ValueError("Encoded clip display dimensions differ from the requested transform")
