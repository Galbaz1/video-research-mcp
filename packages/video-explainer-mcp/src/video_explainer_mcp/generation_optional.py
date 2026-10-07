"""Pinned S2V/HappyHorse mode contracts and bounded immutable media admission."""

import base64
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit, urlunsplit

from .file_io import open_regular
from .generation_references import inspect_image, MAX_IMAGE_BYTES
from .materials import pinned_object
from .render_storyboard_sources import confined_path

PRIMARY = {
    "wan_s2v.py": "9ee47f3457d757bfe3bf161dedaf27592dd3756764771686ffa7b504aa3142a9",
    "happyhorse.py": "05e35f8d7ac835f9b075d16bb363380eec88290d7fea3f6f4bf6ff6c8af48679",
    "retry.py": "aacfbdbbd182706f05046eadf6155aadcfefc112f80af52feedb464feb5988c6",
}
MODES = {"wan2.2-s2v": "portrait_audio", "happyhorse-1.0-t2v": "text_to_video",
         "happyhorse-1.0-i2v": "image_to_video", "happyhorse-1.0-r2v": "reference_to_video",
         "happyhorse-1.0-video-edit": "video_edit"}
ENDPOINTS = {model: "/services/aigc/video-generation/video-synthesis" for model in MODES}
ENDPOINTS["wan2.2-s2v"] = "/services/aigc/image2video/video-synthesis/"
MAX_VIDEO_BYTES = 100_000_000
IMAGE_ROLES = {"reference", "identity", "style"}


def controls(value: dict) -> dict:
    """Return exact continuation controls, including output expectations."""
    return {key: value.get(key) for key in ("model", "prompt", "negative_prompt", "duration",
            "resolution", "ratio", "seed", "prompt_extend", "watermark", "audio_setting",
            "expected_dimensions", "expected_audio", "transparent_background")}


def snapshot(project: Path, reference: dict, limit: int) -> bytes:
    """Read one bounded regular file and verify the exact caller hash."""
    with open_regular(confined_path(project, reference["source"]["path"])) as (stream, info):
        if not 0 < info.st_size <= limit:
            raise ValueError("Optional reference exceeded its media byte bound")
        body = stream.read(limit + 1)
    if len(body) > limit or hashlib.sha256(body).hexdigest() != reference["source"]["sha256"]:
        raise ValueError("Optional reference integrity failed")
    return body


def inspect_av(body: bytes, kind: str) -> dict:
    """Probe the same bounded media bytes, never a caller URL or changed path."""
    with tempfile.TemporaryDirectory(prefix=".generation-reference-") as directory:
        path = Path(directory) / "input"
        path.write_bytes(body)
        command = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                   "-show_entries", "format=format_name,duration:stream=codec_type,codec_name,width,height,avg_frame_rate,duration",
                   "-of", "json", str(path)]
        result = subprocess.run(command, capture_output=True, timeout=10, check=True)
    if result.stderr or len(result.stdout) > 16384:
        raise ValueError("Optional reference probe did not verify")
    value = json.loads(result.stdout)
    duration = float(value.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Optional reference duration is invalid")
    streams = value.get("streams", [])
    if kind == "audio":
        if (len(streams) != 1 or streams[0].get("codec_type") != "audio"
                or streams[0].get("codec_name") not in {"mp3", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"}
                or value["format"]["format_name"] not in {"wav", "mp3"} or duration >= 20):
            raise ValueError("S2V requires WAV/MP3 audio shorter than20 seconds")
        return {"kind": kind, "duration_seconds": duration, "codec": streams[0]["codec_name"]}
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    if (len(videos) != 1 or any(s.get("codec_type") not in {"video", "audio"} for s in streams)
            or len(streams) > 2 or videos[0].get("codec_name") != "h264"
            or "mov" not in value["format"]["format_name"] or not 3 <= duration <= 15):
        raise ValueError("Video edit requires whole H264 MP4/MOV of3-15 seconds; truncation refused")
    video = videos[0]
    width, height = video["width"], video["height"]
    numerator, denominator = map(int, video["avg_frame_rate"].split("/"))
    fps = numerator / denominator if denominator else 0
    if (max(width, height) > 4096 or min(width, height) < 360
            or not 0.4 <= width / height <= 2.5 or not 8 < fps <= 60):
        raise ValueError("Video edit input geometry/frame rate is unsupported")
    return {"kind": kind, "duration_seconds": duration, "width": width, "height": height,
            "fps": fps, "codec": "h264", "audio_present": len(streams) == 2}


def reference_metadata(project: Path, reference: dict, model: str) -> dict:
    """Validate role-specific formats and exact bytes for an admitted mode."""
    role = reference["role"]
    kind = "audio" if role == "driving_audio" else "video" if role == "source_video" else "image"
    limit = 14_999_999 if kind == "audio" else MAX_VIDEO_BYTES if kind == "video" else MAX_IMAGE_BYTES
    body = snapshot(project, reference, limit)
    if kind == "image":
        media = {"kind": kind, **inspect_image(body)}
        width, height = media["width"], media["height"]
        if model == "wan2.2-s2v":
            if not 400 <= width <= 7000 or not 400 <= height <= 7000:
                raise ValueError("S2V portrait dimensions are unsupported")
        elif (media["format"] == "BMP" or min(width, height) < (400 if model.endswith("-r2v") else 300)
              or not 0.4 <= width / height <= 2.5):
            raise ValueError("HappyHorse image format/geometry is unsupported")
    else:
        media = inspect_av(body, kind)
    url = reference.get("public_url")
    needs_url = model == "wan2.2-s2v" or kind == "video"
    if needs_url:
        if not url:
            raise ValueError("This media contract requires a pinned public URL")
        from .materials_remote import public_url

        parts = urlsplit(url)
        public_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment)),
                   ["help-static-aliyun-doc.aliyuncs.com", "img.alicdn.com", "dashscope-result-sh.oss-accelerate.aliyuncs.com",
                    "dashscope-result.oss-cn-beijing.aliyuncs.com", "dashscope-result-hz.oss-cn-hangzhou.aliyuncs.com"])
    elif url is not None:
        raise ValueError("HappyHorse images use pinned bytes; additional URL intent is unsupported")
    return {"role": role, "source": reference["source"], "size_bytes": len(body), **media}


def validate_controls(request, value: dict, roles: list[str]) -> None:
    """Reject unsupported control and reference-role intent for the selected mode."""
    model = value["model"]
    if value["negative_prompt"] or value.get("prompt_extend", False):
        raise ValueError("Optional models do not support negative_prompt or prompt_extend")
    if model == "wan2.2-s2v":
        if (sorted(roles) != ["driving_audio", "portrait"] or value["resolution"] not in {"480P", "720P"}
                or value["prompt"] or value["seed"] != 0 or value.get("watermark", True) is False
                or value.get("audio_setting") is not None or value["expected_audio"] != "present"):
            raise ValueError("S2V supports only portrait/audio and resolution; unsupported controls refused")
    else:
        if value["resolution"] not in {"720P", "1080P"} or not 3 <= value["duration"] <= 15:
            raise ValueError("HappyHorse duration/resolution is outside the pinned contract")
        if (not model.endswith("-i2v") and not value["prompt"].strip()) or len(re.findall(r"[\u4e00-\u9fff]", value["prompt"])) > 2500:
            raise ValueError("HappyHorse prompt is missing or would be truncated")
        if not model.endswith("-video-edit") and not isinstance(value["duration"], int):
            raise ValueError("HappyHorse generated duration must be an integer")
        if model.endswith("-t2v") and roles:
            raise ValueError("HappyHorse text mode does not accept references")
        if model.endswith("-i2v") and roles != ["first_frame"]:
            raise ValueError("HappyHorse image mode requires exactly one first_frame")
        if model.endswith("-r2v") and (not 1 <= len(roles) <= 9 or not set(roles) <= IMAGE_ROLES):
            raise ValueError("HappyHorse reference mode requires1-9 image anchors; overflow refused")
        if model.endswith("-video-edit") and (roles.count("source_video") != 1 or len(roles) > 6
                or not set(roles) <= IMAGE_ROLES | {"source_video"}):
            raise ValueError("HappyHorse edit requires one video and0-5 image anchors; overflow refused")
        if not model.endswith("-video-edit") and value.get("audio_setting") is not None:
            raise ValueError("audio_setting is supported only for video_edit")
    if model in {"wan2.2-s2v", "happyhorse-1.0-i2v", "happyhorse-1.0-video-edit"} and value["ratio"] is not None:
        raise ValueError("Input-derived modes do not support a ratio control")


def freeze_optional(project: Path, request) -> dict:
    """Reject mismatched roles/counts and controls before reserving any generation."""
    value = request.model_dump(mode="json")
    model = value["model"]
    roles = [ref["role"] for ref in value["references"]]
    validate_controls(request, value, roles)
    dimensions = value.get("expected_dimensions")
    if not dimensions:
        raise ValueError("Optional modes require declared output dimensions")
    # Primary contracts define approximate tier area, not an exact pixel grid.
    tier_area = {"480P": 640 * 480, "720P": 1280 * 720, "1080P": 1920 * 1080}[value["resolution"]]
    if abs(dimensions[0] * dimensions[1] - tier_area) > tier_area * 0.10:
        raise ValueError("Expected output area exceeds local 10% resolution-tier tolerance")
    metadata = [reference_metadata(project, ref, model) for ref in value["references"]]
    expected_seconds = float(value["duration"])
    intrinsic = next((m for m in metadata if m["kind"] in {"audio", "video"}), None)
    if intrinsic:
        expected_seconds = intrinsic["duration_seconds"]
        if abs(expected_seconds - value["duration"]) > 0.1:
            raise ValueError("Declared duration differs from whole input media; truncation refused")
    if value.get("audio_setting") == "origin" and value["expected_audio"] != ("present" if intrinsic["audio_present"] else "absent"):
        raise ValueError("Origin audio expectation differs from input video")
    if model.endswith("-r2v"):
        indices = [int(n) for n in re.findall(r"\[Image (\d+)\]", value["prompt"])]
        if set(indices) != set(range(1, len(metadata) + 1)):
            raise ValueError("Every reference must retain its ordered prompt identity")
    if model.endswith(("-t2v", "-r2v")):
        numerator, denominator = map(int, value["ratio"].split(":"))
    else:
        image = next(m for m in metadata if m["kind"] in {"image", "video"})
        numerator, denominator = image["width"], image["height"]
    if abs(dimensions[0] * denominator - dimensions[1] * numerator) > 0.02 * dimensions[1] * numerator:
        raise ValueError("Expected output aspect differs from the mode's actual aspect basis")
    settings = {"model": model, "controls": controls(value), "references": value["references"]}
    if value["continuation"] is not None and pinned_object(project, request.continuation) != settings:
        raise ValueError("Continuation differs from exact model, controls or reference identities")
    return {"mode": MODES[model], "wire_model": model, "reference_metadata": metadata,
            "expected_pixels": dimensions, "expected_seconds": expected_seconds,
            "submit_path": ENDPOINTS[model], "continuation_settings": settings,
            "dimension_basis": "caller_declared_output_with_local_10pct_tier_area_and_2pct_aspect_tolerance"}


def payload_optional(frozen: dict) -> dict:
    """Encode every admitted reference in order without slicing or normalization."""
    value = frozen["generation"]
    model = value["model"]
    project = Path(frozen["project_dir"])
    media = []
    urls = {}
    for ref, expected in zip(value["references"], frozen["reference_metadata"], strict=True):
        actual = reference_metadata(project, ref, model)
        if actual != expected:
            raise ValueError("Optional reference changed after admission")
        url = ref.get("public_url")
        if url is None:
            body = snapshot(project, ref, MAX_IMAGE_BYTES)
            url = "data:" + actual["mime_type"] + ";base64," + base64.b64encode(body).decode("ascii")
        urls[ref["role"]] = url
        media.append({"type": "video" if ref["role"] == "source_video" else
                      "first_frame" if ref["role"] == "first_frame" else "reference_image", "url": url})
    parameters = {"resolution": value["resolution"]}
    if model == "wan2.2-s2v":
        inputs = {"image_url": urls["portrait"], "audio_url": urls["driving_audio"]}
    else:
        inputs = {"prompt": value["prompt"]} if value["prompt"] else {}
        if media:
            inputs["media"] = media
        parameters.update(seed=value["seed"], watermark=value.get("watermark", True))
        if model.endswith("-video-edit"):
            parameters["audio_setting"] = value.get("audio_setting") or "auto"
        else:
            parameters["duration"] = value["duration"]
            if not model.endswith("-i2v"):
                parameters["ratio"] = value["ratio"]
    return {"model": model, "input": inputs, "parameters": parameters}


async def verify_public_references(frozen: dict, fetch) -> None:
    """Compare bounded URL bodies to local pins before the sole generation POST."""
    for ref, metadata in zip(frozen["generation"]["references"], frozen.get("reference_metadata", []), strict=True):
        if ref.get("public_url"):
            body = await fetch("GET", ref["public_url"], {}, None, metadata["size_bytes"])
            if len(body) != metadata["size_bytes"] or hashlib.sha256(body).hexdigest() != ref["source"]["sha256"]:
                raise ValueError("Public reference differs from its pinned local body")
