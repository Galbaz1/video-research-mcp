"""Finite FFmpeg aspect/caption recipes and strict full-output qualification."""

import json
import math
from pathlib import Path

from .media_process import run_media_process
from .render_storyboard_sources import file_pin

DIMENSIONS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}


async def backend(executables: dict, work: Path) -> None:
    """Check drawtext and the selected private font before any variant render."""
    command = [executables["ffmpeg"]["path"], "-v", "error", "-nostdin", "-xerror", "-f", "lavfi", "-i",
               "color=size=32x32:rate=1", "-vf", "drawtext=fontfile=font.ttf:text=Test:fontsize=12",
               "-frames:v", "1", "-f", "null", "-"]
    stdout, stderr = await run_media_process(command, 5, cwd=work)
    if stdout or stderr:
        raise ValueError("Caption font/drawtext backend is unsupported")


def recipe(context: dict, aspect: str, layout: dict, binary: str) -> list[str]:
    """Keep complete scene frame/sample spans; contain/pad without crop or reorder."""
    width, height = DIMENSIONS[aspect]
    graph = [f"[0:v]trim=start_frame={context['start_frame']}:end_frame={context['end_frame']},setpts=PTS-STARTPTS,"
             f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"]
    for i, cue in enumerate(context["cues"]):
        start, end = (cue[k] / cue["sample_rate"] for k in ("start_sample", "end_sample"))
        graph[0] += (f",drawtext=fontfile=font.ttf:textfile=cue-{i}.txt:expansion=none:fontsize={layout['font_size']}:"
                     f"fontcolor=white:x=(w-text_w)/2:y=h-{layout['margin']}-text_h:fix_bounds=1:"
                     f"enable='gte(t,{start})*lt(t,{end})'")
    graph[0] += ",format=yuv420p[v]"
    graph.append(f"[1:a]atrim=start_sample={context['start_sample']}:end_sample={context['end_sample']},"
                 f"asetpts=PTS-STARTPTS,aresample=48000,apad=whole_dur={context['duration']},"
                 f"atrim=duration={context['duration']}[a]")
    return [binary, "-v", "error", "-nostdin", "-xerror", "-n", "-protocol_whitelist", "file,pipe", "-f", "mov", "-i", "source.mp4",
            "-protocol_whitelist", "file,pipe", "-f", "wav", "-i", "audio.wav", "-filter_complex", ";".join(graph),
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-threads", "2",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", str(context["duration"]), "-fs", str(64 * 1024 * 1024),
            f"variant-{aspect.replace(':', '-')}.mp4"]


async def qualify(path: Path, aspect: str, context: dict, executables: dict) -> dict:
    """Require exact frame count, dimensions, AAC audio duration and full decode."""
    pin = file_pin(path, 64 * 1024 * 1024)
    command = [executables["ffprobe"]["path"], "-v", "error", "-protocol_whitelist", "file,pipe", "-f", "mov", "-count_frames",
               "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,nb_read_frames,r_frame_rate,duration,sample_rate,channels",
               "-of", "json", str(path)]
    stdout, stderr = await run_media_process(command, 10)
    if stderr or len(stdout) > 16384:
        raise ValueError("Variant metadata probe failed")
    value = json.loads(stdout)
    streams = value.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(streams) != 2 or len(video) != 1 or len(audio) != 1:
        raise ValueError("Variant requires one video and one audio stream")
    v, a = video[0], audio[0]
    if tuple(v.get(k) for k in ("codec_name", "width", "height", "nb_read_frames", "r_frame_rate")) != (
        "h264", *DIMENSIONS[aspect], str(context["end_frame"] - context["start_frame"]), "30/1"):
        raise ValueError("Variant dimensions/frame order/duration differ")
    if (a.get("codec_name"), a.get("sample_rate"), a.get("channels")) != ("aac", "48000", 2):
        raise ValueError("Variant audio codec/rate/channels differ")
    for duration in (value.get("format", {}).get("duration"), a.get("duration")):
        seconds = float(duration or 0)
        if not math.isfinite(seconds) or abs(seconds - context["duration"]) > 1 / 30:
            raise ValueError("Variant audio/video duration differs from source scene clock")
    command = [executables["ffmpeg"]["path"], "-v", "error", "-nostdin", "-xerror", "-protocol_whitelist", "file,pipe", "-f", "mov",
               "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"]
    stdout, stderr = await run_media_process(command, 20)
    if stdout or stderr or file_pin(path, 64 * 1024 * 1024) != pin:
        raise ValueError("Variant full decode or stable readback failed")
    return {**pin, "full_decode": True, "width": v["width"], "height": v["height"],
            "frames": context["end_frame"] - context["start_frame"], "duration_seconds": context["duration"],
            "caption_pixels_verified": False, "spoken_semantics": "not_verified"}
