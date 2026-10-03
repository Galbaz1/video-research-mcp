"""Finite file-only lossless lesson compositor, reusing observed installed native identities."""

import json
import math
from fractions import Fraction

from .education_timing import MAX_FRAMES, MAX_RGB_BYTES
from .footage_edit_native import NativeWork, input_command
from .media_clip_timing import _output_audio
from .media_probe import binary

__all__ = ["NativeWork"]


def mux_command(directory, frame_count=72):
    """Encode the exact PNG population as lossless RGB H264 and supplied audio as ALAC."""
    return [binary("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-v", "info", "-xerror", "-n",
            "-max_alloc", "67108864", "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
            "-protocol_whitelist", "file", "-format_whitelist", "image2", "-f", "image2", "-framerate", "12",
            "-i", str(directory / "frame-%03d.png"), "-protocol_whitelist", "file", "-format_whitelist", "wav",
            "-i", str(directory / "narration.wav"), "-map", "0:v:0", "-map", "1:a:0", "-sn", "-dn",
            "-map_metadata", "-1", "-map_chapters", "-1", "-c:v", "libx264rgb", "-crf", "0",
            "-preset", "veryfast", "-threads", "1", "-pix_fmt", "rgb24", "-bf", "0", "-frames:v", str(frame_count),
            "-fps_mode", "passthrough", "-enc_time_base:v", "1:12", "-video_track_timescale", "12000",
            "-c:a", "alac", "-fs", "8388608", "-movflags", "+faststart", str(directory / "video.mp4")]


def _video_clock(info, selected):
    """Inspect every education PTS under the concrete360-frame,640x360,12fps ceiling."""
    if (selected.get("width"), selected.get("height"), selected.get("codec_name")) != (640, 360, "h264"):
        raise ValueError("Lesson decoded grid/codec differs from640x360 H264")
    rows = [f for f in info["frames"] if f.get("stream_index") == selected["index"]]
    clock = Fraction(selected["time_base"])
    if clock <= 0 or not 1 <= len(rows) <= MAX_FRAMES:
        raise ValueError("Lesson decoded frame population is invalid")
    if any(type(f.get("pts")) is not int for f in rows):
        raise ValueError("Lesson decoded frame PTS must be integers")
    points = [f["pts"] for f in rows]
    times = [float(p * clock) for p in points]
    for i, (p, row) in enumerate(zip(points, rows, strict=True)):
        reported = float(row["pts_time"])
        if p * clock != Fraction(i, 12) or not math.isfinite(reported) or abs(times[i] - reported) > 5e-6:
            raise ValueError("Lesson decoded frame PTS disagrees with its exact12fps clock")
    duration = float(info["format"]["duration"])
    if not math.isfinite(duration) or not 0 < duration <= 30.001:
        raise ValueError("Lesson container duration exceeds its bounded interval")
    return {"duration_seconds": duration, "frame_count": len(points), "width": 640, "height": 360,
            "video_codec": "h264", "time_base": selected["time_base"], "decoded_frame_pts": points,
            "decoded_frame_seconds": times, "first_frame_seconds": times[0],
            "last_frame_seconds": times[-1], "frame_timing_verified": True}


def _audio_clock(info, selected):
    """Require contiguous lossless PCM clocks from zero through every decoded sample."""
    if (selected.get("codec_name"), selected.get("sample_rate"), selected.get("channels")) != ("alac", "48000", 1):
        raise ValueError("Lesson output must preserve48kHz mono audio with lossless ALAC")
    rows = [f for f in info["frames"] if f.get("stream_index") == selected["index"]]
    if not 1 <= len(rows) <= 4096:
        raise ValueError("Lesson decoded audio has no complete sample population")
    clock, count = Fraction(selected["time_base"]), 0
    for row in rows:
        samples, pts = row.get("nb_samples"), row.get("pts")
        if type(samples) is not int or not 1 <= samples <= 65536 or type(pts) is not int:
            raise ValueError("Lesson decoded audio has invalid sample counts or PTS")
        seconds = float(row["pts_time"])
        if pts * clock != Fraction(count, 48000) or not math.isfinite(seconds) or abs(seconds - count / 48000) > 5e-6:
            raise ValueError("Lesson decoded audio clocks contain a gap/overlap or inconsistent PTS")
        count += samples
    if count > 1440000:
        raise ValueError("Lesson decoded audio exceeds30 seconds")
    result = _output_audio(info["frames"], selected)
    result.update(sample_count=count, duration_seconds=count / 48000)
    return result


async def inspect_video(path, work):
    """Inspect one complete bounded probe population, without the footage256-frame guard."""
    stdout, _ = await work.run(input_command(path, probe=True) + ["-show_format", "-show_streams", "-show_frames",
        "-show_entries", "format=duration:stream=index,codec_type,codec_name,width,height,time_base,sample_rate,channels:"
        "frame=stream_index,pts,pts_time,nb_samples", "-of", "json"])
    info = json.loads(stdout)
    video = [s for s in info["streams"] if s.get("codec_type") == "video"]
    audio = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    if len(info["streams"]) != 2 or len(video) != 1 or len(audio) != 1 or video[0]["index"] == audio[0]["index"]:
        raise ValueError("Lesson output must have exactly one video and one audio stream")
    if any(f.get("stream_index") not in {video[0]["index"], audio[0]["index"]} for f in info["frames"]):
        raise ValueError("Lesson probe contains frames outside its two streams")
    return {"output": _video_clock(info, video[0]), "audio": _audio_clock(info, audio[0])}


async def extract_evidence(path, directory, work):
    """Write full RGB and PCM evidence to bounded owned files, never large stdout buffers."""
    await work.run(input_command(path) + ["-map", "0:v:0", "-an", "-pix_fmt", "rgb24", "-fps_mode", "passthrough",
        "-f", "rawvideo", "-fs", str(MAX_RGB_BYTES), "-n", str(directory / "decoded.rgb")])
    await work.run(input_command(path) + ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", "-f", "wav",
        "-fs", "8388608", "-n", str(directory / "decoded.wav")])
