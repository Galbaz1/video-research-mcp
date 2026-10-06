"""Qualify current production output against its admitted scene clock and receipt."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .media_process import run_media_process
from .planning_sources import read_object
from .render_artifacts import verify_output
from .render_authored import PACKAGES
from .render_validation import codec_executables


def production_receipt(artifact: dict, request: dict) -> dict:
    """Bind the entry's receipt to the exact requested sources, audio and MP4."""
    path = Path(artifact["path"] + ".receipt.json")
    receipt, sha = read_object(path, path.parent)
    binding, contract = request["renderer"], request["render_contract"]
    props = contract["input_props"]
    composition = {name: props[name] for name in ("fps", "width", "height", "durationInFrames")}
    composition["id"] = "Production"
    expected = {
        "schema": "vrm-authored-storyboard-receipt/r1",
        "execution_token": request["execution_token"],
        "spec_sha256": binding["spec_sha256"],
        "project_sha256": binding["project_sha256"],
        "entry_sha256": binding["entry_sha256"],
        "input_props": props,
        "node_modules_sha256": binding["node_modules_sha256"],
        "ffprobe": binding["ffprobe"],
        "browser_sha256": binding["browser"]["sha256"],
        "package_versions": PACKAGES,
        "fast_requested": request["fast"],
        "fast_applied": request["fast"],
        "quality": {"crf": 28, "x264Preset": "veryfast"}
        if request["fast"]
        else {"crf": 18, "x264Preset": "medium"},
        "composition": composition,
        "output": {key: artifact[key] for key in ("path", "sha256", "size_bytes")},
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("Production receipt differs from the persisted request/output")
    observations = receipt.get("audio_observations")
    if not isinstance(observations, list):
        raise ValueError("Production receipt lacks measured audio extents")
    measured = {}
    for row in observations:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("path"), str)
            or row["path"] in measured
        ):
            raise ValueError("Production audio extent records must have unique paths")
        value = row.get("duration_seconds")
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Production audio extent must be positive and finite")
        measured[row["path"]] = value
    if set(measured) != set(contract["asset_pins"]):
        raise ValueError("Production audio extent population differs from selected assets")
    for scene in props["scenes"]:
        if abs(measured[scene["audio_src"]] - scene["audioDurationInFrames"] / 30) > 1 / 30:
            raise ValueError("Production audio extent differs from the admitted scene clock")
    return {
        "path": str(path),
        "sha256": sha,
        "execution_token": request["execution_token"],
        "audio_observations": observations,
    }


async def qualify_production(artifact: dict, qualification: dict, request: dict) -> dict:
    """Require the exact admitted frame count, dimensions and stereo AAC audio."""
    props = request["render_contract"]["input_props"]
    duration = qualification["media"]["duration_seconds"]
    expected_seconds = props["durationInFrames"] / props["fps"]
    if not math.isfinite(duration) or abs(duration - expected_seconds) > 1 / props["fps"]:
        raise ValueError("Production output duration differs from its admitted scene clock")
    receipt = production_receipt(artifact, request)
    executables = codec_executables()
    if executables["ffprobe"] != request["renderer"]["ffprobe"]:
        raise ValueError("Production output probe differs from its admitted executable")
    command = [
        executables["ffprobe"]["path"],
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-f",
        "mov",
        "-count_frames",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,nb_read_frames,r_frame_rate,pix_fmt,sample_rate,channels",
        "-of",
        "json",
        artifact["path"],
    ]
    stdout, stderr = await run_media_process(command, 10.0)
    if stderr or len(stdout) > 16384:
        raise ValueError("Production frame/audio probe failed")
    streams = json.loads(stdout).get("streams", [])
    video = [row for row in streams if row.get("codec_type") == "video"]
    audio = [row for row in streams if row.get("codec_type") == "audio"]
    if len(streams) != 2 or len(video) != 1 or len(audio) != 1:
        raise ValueError("Production output requires exactly one video and one audio stream")
    v, a = video[0], audio[0]
    expected_video = (
        "h264",
        props["width"],
        props["height"],
        str(props["durationInFrames"]),
        "30/1",
        "yuv420p",
    )
    actual_video = tuple(
        v.get(key)
        for key in ("codec_name", "width", "height", "nb_read_frames", "r_frame_rate", "pix_fmt")
    )
    if actual_video != expected_video:
        raise ValueError("Production output differs from its admitted composition")
    if tuple(a.get(key) for key in ("codec_name", "sample_rate", "channels")) != (
        "aac",
        "48000",
        2,
    ):
        raise ValueError("Production output requires AAC 48kHz stereo audio")
    if codec_executables() != executables or not verify_output(artifact):
        raise ValueError("Production output or codec executable changed during qualification")
    return {
        "frames": props["durationInFrames"],
        "fps": 30,
        "audio_codec": "aac",
        "audio_sample_rate": 48000,
        "audio_channels": 2,
        "receipt": receipt,
        "playback_verified": False,
        "fast_requested": request["fast"],
        "fast_applied": request["fast"],
        "capability": "admitted project scene registry and per-scene audio",
    }
