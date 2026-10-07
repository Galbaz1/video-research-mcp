"""Bounded selected HTTP and exact project-owned video qualification."""

import asyncio
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlsplit, urlunsplit

from .generation_request import RESULT_HOST
from .materials import publish
from .media_process import run_media_process
from .render_artifacts import file_revision, verify_output
from .render_storyboard_sources import confined_path
from .render_validation import _snapshot

MAX_ASSET_BYTES = 32 * 1024 * 1024
DURATION_TOLERANCE = 0.1


def http_client():
    """Load the optional transport only when a selected operation reaches HTTP."""
    import httpx

    return httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False)


async def request_bytes(method: str, url: str, headers: dict, payload, limit: int) -> bytes:
    """Make one bounded request with no redirects, proxy inheritance or retries."""
    try:
        async with asyncio.timeout(25), http_client() as client:
            async with client.stream(method, url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    raise ValueError("Selected HTTP response was not successful; no retry")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(chunk) > limit - len(body):
                        raise ValueError("Selected response exceeded its byte ceiling")
                    body.extend(chunk)
                return bytes(body)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise ValueError(f"Selected HTTP request did not verify ({type(exc).__name__})") from None


async def acquire_asset(project: Path, job_id: str, url: str) -> dict:
    """Retain exact downloaded bytes inside the approved project, without API auth."""
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Provider result URL is absent or excessive")
    parts = urlsplit(url)
    safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    from .materials_remote import public_url

    public_url(safe_url, [RESULT_HOST])
    body = await request_bytes("GET", url, {}, None, MAX_ASSET_BYTES)
    if not body:
        raise ValueError("Generated video response was empty")
    sha = hashlib.sha256(body).hexdigest()
    name = f"generation-{job_id}.mp4"
    target = confined_path(project, name)
    if target.exists():
        if file_revision(target, MAX_ASSET_BYTES) != {"sha256": sha, "size_bytes": len(body)}:
            raise ValueError("Existing generated asset differs; overwrite refused")
    else:
        with tempfile.TemporaryDirectory(prefix=".generation-download-", dir=project) as directory:
            temporary = Path(directory) / "asset.mp4"
            temporary.write_bytes(body)
            publish(project, temporary, name, sha)
    return {"path": str(target), "sha256": sha, "size_bytes": len(body),
            "download_origin": parts.hostname, "url_sha256": hashlib.sha256(url.encode()).hexdigest()}


def executable_identity() -> dict:
    """Retain actual executable stat identities without acquiring huge binary bodies."""
    identities = {}
    for name in ("ffprobe", "ffmpeg"):
        found = shutil.which(name)
        if not found:
            raise FileNotFoundError("FFmpeg and ffprobe are required for generation qualification")
        path = Path(found).resolve()
        info = path.stat()
        identities[name] = {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
                            "size_bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
    return identities


def measured_media(body: bytes, request: dict) -> dict:
    """Match exact pixel map, duration and every audio/video stream to the request."""
    if len(body) > 16384:
        raise ValueError("Generation metadata exceeded16KiB")
    value = json.loads(body)
    streams = value.get("streams", [])
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1 or len(streams) != 2:
        raise ValueError("Selected generated asset requires one video and one audio stream")
    video = videos[0]
    if (video.get("codec_name") != "h264"
            or [video.get("width"), video.get("height")] != request["expected_pixels"]
            or video.get("sample_aspect_ratio") not in {None, "1:1"}
            or any(side.get("rotation", 0) != 0 for side in video.get("side_data_list", []))):
        raise ValueError("Generated video codec/dimensions differ from selected contract")
    duration = float(value.get("format", {}).get("duration", 0))
    expected = request["generation"]["duration"]
    for actual in (duration, *(float(stream.get("duration", 0)) for stream in streams)):
        if not math.isfinite(actual) or abs(actual - expected) > DURATION_TOLERANCE:
            raise ValueError("Generated audio/video duration differs from selected request")
    return {"width": video["width"], "height": video["height"], "duration_seconds": duration,
            "video_codec": "h264", "audio_codec": audios[0].get("codec_name"),
            "audio_present": True, "stream_durations": [float(s["duration"]) for s in streams]}


async def qualify_asset(artifact: dict, request: dict) -> dict:
    """Decode the exact snapshot to EOF and compare actual video/audio measurements."""
    identity = executable_identity()
    project = Path(request["project_dir"])
    with tempfile.TemporaryDirectory(prefix=".generation-decode-", dir=project) as directory:
        path = Path(directory) / "asset.mp4"
        _snapshot(artifact, path)
        probe = [identity["ffprobe"]["path"], "-v", "error", "-protocol_whitelist", "file,pipe",
                 "-f", "mov", "-show_entries",
                 "format=duration:stream=codec_type,codec_name,width,height,duration,sample_aspect_ratio:stream_side_data=rotation",
                 "-of", "json", str(path)]
        stdout, stderr = await run_media_process(probe, 10)
        if stderr:
            raise ValueError("Generation probe reported media errors")
        media = measured_media(stdout, request)
        decode = [identity["ffmpeg"]["path"], "-v", "error", "-nostdin", "-xerror",
                  "-protocol_whitelist", "file,pipe", "-f", "mov", "-i", str(path),
                  "-map", "0:v:0", "-map", "0:a:0", "-progress", "pipe:1", "-nostats",
                  "-f", "null", "-"]
        progress, stderr = await run_media_process(decode, 60)
        values = dict(line.split("=", 1) for line in progress.decode().splitlines() if "=" in line)
        decoded = float(values.get("out_time_us", "nan")) / 1000000
        if (stderr or values.get("progress") != "end" or int(values.get("frame", "0")) <= 0
                or not math.isfinite(decoded)
                or abs(decoded - request["generation"]["duration"]) > DURATION_TOLERANCE):
            raise ValueError("Generation full decode did not reach the requested EOF")
    if executable_identity() != identity or not verify_output(artifact, MAX_ASSET_BYTES):
        raise ValueError("Generation artifact or decoder identity changed during qualification")
    return {"policy": "wan2.7-exact-video-audio-full-decode-v1", "full_decode": True,
            "artifact_sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"],
            "media": media, "decoded_seconds": decoded, "duration_tolerance_seconds": DURATION_TOLERANCE,
            "executables": identity, "executable_byte_identity": "UNQUALIFIED",
            "probe_command": probe, "decode_command": decode,
            "visual_audio_semantics": "UNQUALIFIED"}
