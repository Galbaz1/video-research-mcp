"""Qualify exact rendered MP4 bytes with bounded metadata and complete decoding."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

from .file_io import open_regular
from .media_process import run_media_process
from .render_artifacts import MAX_RENDER_BYTES, file_revision, verify_output

MAX_VIDEO_BYTES = MAX_RENDER_BYTES
PROBE_TIMEOUT = 10.0
DECODE_TIMEOUT = 60.0
POLICY = "mp4-full-decode-v1"
RESOLUTIONS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}


def _snapshot(artifact: dict, target: Path) -> None:
    """Decode a private copy of the exact admitted bytes, never a mutable path."""
    digest = hashlib.sha256()
    total = 0
    with open_regular(Path(artifact["path"])) as (source, info), target.open("xb") as output:
        if not 0 < info.st_size <= MAX_VIDEO_BYTES:
            raise ValueError("Rendered MP4 must be nonempty and at most512MiB")
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            total += len(chunk)
            if total > MAX_VIDEO_BYTES:
                raise ValueError("Rendered MP4 exceeds512MiB during snapshot")
            digest.update(chunk)
            output.write(chunk)
    if total != artifact["size_bytes"] or digest.hexdigest() != artifact["sha256"]:
        raise ValueError("Rendered output changed before codec qualification")


def codec_executables() -> dict:
    """Resolve actual native binaries and retain their byte identities."""
    result = {}
    for name in ("ffprobe", "ffmpeg"):
        found = shutil.which(name)
        if not found:
            raise FileNotFoundError(f"{name} is required for render qualification")
        path = Path(found).resolve()
        result[name] = {"path": str(path), **file_revision(path, MAX_RENDER_BYTES)}
    return result


def _metadata(body: bytes, resolution: str) -> dict:
    """Require H264 MP4, finite duration and the requested full-video dimensions."""
    if len(body) > 16384:
        raise ValueError("Render metadata exceeds16KiB")
    value = json.loads(body)
    streams = value.get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise ValueError("Rendered MP4 must contain a readable primary video stream")
    video = streams[0]
    if video.get("codec_name") != "h264":
        raise ValueError("Render route requires an H264 video stream")
    dimensions = (video.get("width"), video.get("height"))
    if dimensions != RESOLUTIONS[resolution]:
        raise ValueError("Rendered dimensions differ from the requested resolution")
    duration = float(value.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or not 0 < duration <= 14400:
        raise ValueError("Rendered duration must be finite, positive and at most4hours")
    return {
        "codec": "h264",
        "width": dimensions[0],
        "height": dimensions[1],
        "duration_seconds": duration,
        "pixel_format": video.get("pix_fmt", "unknown"),
    }


async def qualify_render(artifact: dict, resolution: str) -> dict:
    """Probe and decode every frame/audio packet under fixed finite resource bounds."""
    executables = codec_executables()
    with tempfile.TemporaryDirectory(prefix="vrm-render-qualification-") as directory:
        path = Path(directory) / "output.mp4"
        _snapshot(artifact, path)
        probe = [
            executables["ffprobe"]["path"],
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "mov",
            "-select_streams",
            "v",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,pix_fmt",
            "-of",
            "json",
            str(path),
        ]
        stdout, stderr = await run_media_process(probe, PROBE_TIMEOUT)
        if stderr:
            raise ValueError("Render probe reported media errors")
        media = _metadata(stdout, resolution)
        decode = [
            executables["ffmpeg"]["path"],
            "-v",
            "error",
            "-nostdin",
            "-xerror",
            "-protocol_whitelist",
            "file,pipe",
            "-f",
            "mov",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ]
        stdout, stderr = await run_media_process(decode, DECODE_TIMEOUT)
        if stdout or stderr:
            raise ValueError("Render full decode reported media errors")
    if codec_executables() != executables or not verify_output(artifact):
        raise ValueError("Output or codec executable changed during render qualification")
    return {
        "policy": POLICY,
        "artifact_sha256": artifact["sha256"],
        "size_bytes": artifact["size_bytes"],
        "media": media,
        "full_decode": True,
        "coverage": "all video frames and audio packets",
        "executables": executables,
        "bounds": {
            "max_bytes": MAX_VIDEO_BYTES,
            "probe_seconds": PROBE_TIMEOUT,
            "decode_seconds": DECODE_TIMEOUT,
            "per_stream_output_bytes": 1024 * 1024,
        },
        "renderer_identity": "configured CLI; implementation not attested",
        "real_renderer_verified": False,
        "visual_audio_semantics": "not_verified",
    }


def qualification_valid(artifact: dict) -> bool:
    """Accept persisted decode proof only for its exact current artifact bytes."""
    proof = artifact.get("qualification", {})
    return (
        proof.get("policy") == POLICY
        and proof.get("full_decode") is True
        and proof.get("artifact_sha256") == artifact.get("sha256")
        and proof.get("size_bytes") == artifact.get("size_bytes")
    )
