"""Finite file-only lossless lesson compositor, reusing observed installed native identities."""

import json

from .footage_edit_native import NativeWork, decoded, input_command
from .media_probe import binary

__all__ = ["NativeWork"]


def mux_command(directory):
    """Encode the exact PNG population as lossless RGB H264 and supplied audio as ALAC."""
    return [binary("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-v", "info", "-xerror", "-n",
            "-max_alloc", "67108864", "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
            "-protocol_whitelist", "file", "-format_whitelist", "image2", "-f", "image2", "-framerate", "12",
            "-i", str(directory / "frame-%03d.png"), "-protocol_whitelist", "file", "-format_whitelist", "wav",
            "-i", str(directory / "narration.wav"), "-map", "0:v:0", "-map", "1:a:0", "-sn", "-dn",
            "-map_metadata", "-1", "-map_chapters", "-1", "-c:v", "libx264rgb", "-crf", "0",
            "-preset", "veryfast", "-threads", "1", "-pix_fmt", "rgb24", "-bf", "0", "-frames:v", "72",
            "-fps_mode", "passthrough", "-enc_time_base:v", "1:12", "-video_track_timescale", "12000",
            "-c:a", "alac", "-fs", "8388608", "-movflags", "+faststart", str(directory / "video.mp4")]


async def inspect_video(path, work):
    """Require actual decoded clocks plus the exact lossless audio stream format."""
    measured = await decoded(path, work)
    stdout, _ = await work.run(input_command(path, probe=True) + ["-show_streams", "-show_frames", "-of", "json"])
    info = json.loads(stdout)
    streams = info["streams"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(streams) != 2 or len(audio) != 1:
        raise ValueError("Lesson output must have exactly one video and one audio stream")
    selected = audio[0]
    if (selected.get("codec_name"), int(selected.get("sample_rate", 0)), selected.get("channels")) != ("alac", 48000, 1):
        raise ValueError("Lesson output must preserve48kHz mono audio with lossless ALAC")
    counts = [f["nb_samples"] for f in info["frames"] if f.get("stream_index") == selected["index"]]
    if not counts or any(type(n) is not int or not 1 <= n <= 65536 for n in counts):
        raise ValueError("Lesson decoded audio has no complete sample population")
    measured["audio"].update(sample_count=sum(counts), duration_seconds=sum(counts) / 48000)
    return measured


async def extract_evidence(path, directory, work):
    """Write full RGB and PCM evidence to bounded owned files, never large stdout buffers."""
    await work.run(input_command(path) + ["-map", "0:v:0", "-an", "-pix_fmt", "rgb24", "-fps_mode", "passthrough",
        "-frames:v", "91", "-f", "rawvideo", "-fs", "67108864", "-n", str(directory / "decoded.rgb")])
    await work.run(input_command(path) + ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", "-f", "wav",
        "-fs", "8388608", "-n", str(directory / "decoded.wav")])
