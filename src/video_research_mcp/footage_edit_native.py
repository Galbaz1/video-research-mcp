"""File-only footage commands with observed installed-binary identities and one deadline."""

import json
import math
import time
from fractions import Fraction
from pathlib import Path

from .media_clip_export import _encode_command, _window
from .media_clip_timing import _output_audio
from .media_image_read import decode_command
from .media_probe import FORMATS, _aspect, _geometry, binary, finite, video_stream
from .media_process import run_media_process
from .media_snapshot import copy_hash


class NativeWork:
    """Resolve operator-installed binaries once and rejoin each complete file identity."""

    def __init__(self, deadline):
        self.deadline = deadline
        self.identities = {}

    def remaining(self):
        """Use one deadline across probe, encoding, measurement and promotion."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Footage edit exceeded its complete operation deadline")
        return remaining

    async def admit(self):
        """Observe regular installed executable files without installing a runtime."""
        for name in ("ffmpeg", "ffprobe"):
            path = Path(binary(name)).resolve(strict=True)
            digest, size = await copy_hash(path)
            self.identities[name] = {"path": str(path), "sha256": digest, "bytes": size,
                                     "status": "operator_installed_file_observed"}

    async def verify(self, name=None):
        """Reject changed executable bytes or substituted installed locations."""
        for key in ([name] if name else self.identities):
            record = self.identities[key]
            if str(Path(binary(key)).resolve(strict=True)) != record["path"]:
                raise ValueError("Installed native executable location changed")
            if await copy_hash(Path(record["path"])) != (record["sha256"], record["bytes"]):
                raise ValueError("Installed native executable bytes changed")
        self.remaining()

    async def run(self, command):
        """Recheck the selected binary before and after joined bounded subprocess work."""
        name = "ffprobe" if Path(command[0]).name == "ffprobe" else "ffmpeg"
        await self.verify(name)
        command = [self.identities[name]["path"], *command[1:]]
        try:
            result = await run_media_process(command, self.remaining())
        except RuntimeError as error:
            raise RuntimeError("Footage native command failed; no artifact was accepted") from error
        await self.verify(name)
        return result


def input_command(path, *, probe=False):
    """Apply existing allocation, thread and local-protocol ceilings to actual bytes."""
    command = [binary("ffprobe" if probe else "ffmpeg")]
    command += (["-v", "error"] if probe else ["-hide_banner", "-nostdin", "-nostats", "-v", "info"])
    command += ["-max_alloc", "67108864", "-max_pixels", "8000000", "-threads", "1"]
    if not probe:
        command += ["-filter_threads", "1", "-filter_complex_threads", "1", "-xerror"]
    return command + ["-protocol_whitelist", "file", "-format_whitelist", FORMATS, "-i", str(path)]


async def probe(owned, work):
    """Parse bounded source metadata using the existing display-geometry policy."""
    command = input_command(owned.path, probe=True) + ["-show_format", "-show_streams", "-of", "json"]
    stdout, _ = await work.run(command)
    info = json.loads(stdout)
    streams = info.get("streams")
    if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
        raise ValueError("Source stream metadata is invalid")
    video = video_stream(streams)
    width, height, dw, dh, rotation = _geometry(video)
    sar, basis, verified, supported = _aspect(video)
    if not video or not supported:
        raise ValueError("Source has no supported video geometry")
    fmt = info.get("format", {})
    duration = finite(fmt.get("duration"))
    duration = duration if duration is not None else finite(video.get("duration"))
    start = finite(fmt.get("start_time"))
    start = start if start is not None else finite(video.get("start_time"))
    stream_start, stream_duration = finite(video.get("start_time")), finite(video.get("duration"))
    end = stream_start - start + stream_duration if None not in (stream_start, start, stream_duration) else duration
    return {"path": str(owned.original), "sha256": owned.sha256, "bytes": owned.size,
            "source_revision": "sha256:" + owned.sha256, "duration_seconds": duration,
            "container_start_seconds": start, "presentation_end_seconds": end,
            "stream_start_seconds": stream_start, "stream_duration_seconds": stream_duration,
            "stored_width": width, "stored_height": height, "display_width": dw, "display_height": dh,
            "sample_aspect_ratio": sar, "display_geometry_basis": basis, "pixel_aspect_verified": verified,
            "rotation_degrees": rotation, "time_base": video.get("time_base"),
            "stream_index": video["index"], "streams": streams, "chapters": [],
            "metadata_method": "bounded_local_ffprobe_exact_snapshot"}


async def decoded(path, work):
    """Read every decoded output PTS/sample clock under the existing clip ceilings."""
    stdout, _ = await work.run(input_command(path, probe=True) + ["-show_format", "-show_streams",
                                                               "-show_frames", "-of", "json"])
    info = json.loads(stdout)
    video = video_stream(info.get("streams", []))
    if not video or not 1 <= video.get("width", 0) * video.get("height", 0) <= 1_000_000:
        raise ValueError("Output has no bounded video grid")
    rows = [f for f in info.get("frames", []) if f.get("stream_index") == video["index"]]
    clock = Fraction(video["time_base"])
    if clock <= 0 or not 1 <= len(rows) <= 256:
        raise ValueError("Output decoded frame population is invalid")
    pts = [int(f["pts"]) for f in rows]
    times = [float(p * clock) for p in pts]
    duration = float(info["format"]["duration"])
    if not math.isfinite(duration) or not 0 < duration <= 61 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Output duration or decoded frame clock is invalid")
    if any(not math.isclose(t, float(f["pts_time"]), abs_tol=5e-6) for t, f in zip(times, rows)):
        raise ValueError("Output decoded PTS disagrees with the reported clock")
    audio = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    if len(info["streams"]) != 1 + len(audio) or len(audio) > 1:
        raise ValueError("Output contains unexpected extra streams")
    return {"output": {"duration_seconds": duration, "frame_count": len(pts),
                       "width": video["width"], "height": video["height"], "video_codec": video["codec_name"],
                       "time_base": video["time_base"], "decoded_frame_pts": pts,
                       "decoded_frame_seconds": times, "first_frame_seconds": times[0],
                       "last_frame_seconds": times[-1], "frame_timing_verified": True},
            "audio": _output_audio(info.get("frames", []), audio[0] if audio else None)}


def selected_command(owned, source, request, offset):
    """Keep original showinfo PTS while hashing every selected decoded RGB frame."""
    options, expression = _window(request, offset)
    return decode_command(owned, source, before_input=options) + [
        "-vf", f"select='{expression}',showinfo,format=rgb24", "-frames:v", "257",
        "-fps_mode", "passthrough", "-f", "framehash", "-hash", "sha256", "-"]


def scene_command(owned, source, request, offset, transform, audio, output, scene):
    """Adapt the existing exact-PTS clip encoder with only typed corrections and gain."""
    command = _encode_command(owned, source, request, offset, transform, audio, output)
    command.insert(1, "-xerror")
    grade = scene.grade
    if (grade.contrast, grade.gamma, grade.saturation) != (1, 1, 1):
        index = command.index("-vf") + 1
        command[index] += f",eq=contrast={grade.contrast}:gamma={grade.gamma}:saturation={grade.saturation}"
    if audio:
        index = command.index("-af") + 1
        command[index] += f",volume={scene.audio.gain_db}dB"
        command[-1:-1] = ["-ar", str(audio["sample_rate"]), "-ac", str(audio["channels"])]
    return command


def assemble_command(scenes, directory, output):
    """Concatenate exact staged local scenes with one explicit source-audio policy."""
    durations = [scene["duration_seconds"] for scene in scenes]
    if any(type(duration) not in (int, float) or not 0 < duration <= 60 for duration in durations):
        raise ValueError("Prepared scene duration must be a finite number greater than zero and at most 60 seconds")
    command = [binary("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-v", "info", "-xerror", "-n",
               "-max_alloc", "67108864", "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1"]
    for i in range(len(scenes)):
        command += ["-protocol_whitelist", "file", "-format_whitelist", FORMATS, "-i", str(directory / f"input-{i}.mp4")]
    audio = scenes[0]["audio"]["included"]
    filters, inputs = [], []
    for i, duration in enumerate(durations):
        filters.append(f"[{i}:v:0]setpts=PTS-STARTPTS[v{i}]")
        inputs.append(f"[v{i}]")
        if audio:
            filters.append(f"[{i}:a:0]atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}]")
            inputs.append(f"[a{i}]")
    filters.append("".join(inputs) + f"concat=n={len(scenes)}:v=1:a={int(audio)}[v]" + ("[a]" if audio else ""))
    command += ["-filter_complex", ";".join(filters), "-map", "[v]", "-sn", "-dn", "-map_metadata", "-1",
                "-map_chapters", "-1", "-c:v", "libx264", "-threads", "1", "-preset", "veryfast",
                "-tune", "zerolatency", "-crf", "18", "-bf", "0", "-pix_fmt", "yuv420p",
                "-fps_mode", "passthrough", "-enc_time_base:v", "1:1000000", "-video_track_timescale", "1000000"]
    command += ["-map", "[a]", "-c:a", "aac", "-b:a", "96k"] if audio else ["-an"]
    return command + ["-flush_packets", "1", "-fs", "8388608", "-movflags", "+faststart", str(output)]
