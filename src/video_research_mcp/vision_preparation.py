"""Exact local image and sampled-video payloads for the concrete vision workflow."""

import hashlib
import os

from .image_edit import edit_image
from .image_manifest import read_manifest
from .media_frames import sample_frames
from .media_local_io import _open_regular
from .media_probe import probe_snapshot
from .media_snapshot import checked_path, copy_hash, snapshot
from .models.image_edit import ImageEditRequest

MAX_INLINE_BYTES = 8 * 1024 * 1024
MAX_TEMP_VIDEO_BYTES = 24 * 1024 * 1024
MAX_INLINE_IMAGES = 32


def read_payload(artifact):
    """Re-read the exact bounded regular bytes committed by local preparation."""
    path = checked_path(artifact["path"])
    with _open_regular(path) as reader:
        size = os.fstat(reader.fileno()).st_size
        if size != artifact["bytes"] or size > MAX_TEMP_VIDEO_BYTES:
            raise ValueError("Prepared payload size changed or exceeds its byte bound")
        data = reader.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
        raise ValueError("Prepared payload identity changed")
    return data


async def prepare_sources(request, profile, stack, generated):
    """Retain input order, original revisions and only this workflow's owned views."""
    prepared, payloads = [], []
    temporary = profile is not None and profile.video_delivery == "dashscope_temporary"
    for index, source in enumerate(request.sources):
        if source.kind == "video" and temporary:
            value, parts = await _temporary_video(source, profile, stack)
        elif source.kind == "video":
            value, parts = await _sampled_video(source, stack)
            generated.append(value)
        else:
            value, parts = await _image(source)
            generated.append(value)
        prepared.append(value)
        payloads.extend({**part, "source_index": index} for part in parts)
    images = [p for p in payloads if p["kind"] == "image"]
    if len(images) > MAX_INLINE_IMAGES or sum(p["bytes"] for p in images) > MAX_INLINE_BYTES:
        raise ValueError("Vision inline payload exceeds32 images or8 MiB aggregate")
    if any(4 * ((p["bytes"] + 2) // 3) > 10_000_000 for p in images):
        raise ValueError("Vision image exceeds the10MB encoded per-item bound")
    return prepared, payloads


async def _image(source):
    """Prepare the unannotated pixels whose exact transforms the model will see."""
    edit = ImageEditRequest(file_path=source.file_path,
                            expected_source_sha256=source.expected_source_sha256,
                            time_seconds=source.time_seconds, crop=source.crop, resize=source.resize)
    value = await edit_image(edit)
    clock = value.get("frame") or {}
    return value, [{**value["artifact"], **clock, "kind": "image", "mime": "image/png"}]


async def _sampled_video(source, stack):
    """Reuse original decoded clocks; sampling is not continuous watched coverage."""
    owned = await stack.enter_async_context(snapshot(source.file_path, source.expected_source_sha256))
    value = await sample_frames(str(owned.path), start_seconds=source.start_seconds,
                                end_seconds=source.end_seconds, fps=source.fps,
                                max_frames=source.max_frames, max_pixels=250000)
    value["source"]["path"] = str(owned.original)
    parts = [{**frame, "kind": "image", "mime": "image/png"} for frame in value["frames"]]
    return value, parts


async def _temporary_video(source, profile, stack):
    """Keep the exact full-video snapshot alive until submission and final readback."""
    if source.start_seconds != 0 or source.end_seconds is not None:
        raise ValueError("Temporary video upload sends the full original; use sampled_frames for intervals")
    if not source.file_path.lower().endswith(".mp4"):
        raise ValueError("Temporary full-video delivery currently requires MP4; sampled_frames supports other inspected formats")
    owned = await stack.enter_async_context(snapshot(source.file_path, source.expected_source_sha256))
    if owned.size > MAX_TEMP_VIDEO_BYTES:
        raise ValueError("Temporary video exceeds the24 MiB implementation bound")
    metadata = await probe_snapshot(owned)
    duration = metadata["duration_seconds"]
    if duration is None or duration <= 0 or duration > profile.max_video_seconds:
        raise ValueError("Temporary video duration is unknown or exceeds the configured backend cap")
    metadata["path"] = str(owned.original)
    artifact = {"path": str(owned.path), "sha256": owned.sha256,
                "bytes": owned.size, "kind": "video", "mime": "video/mp4"}
    return {"source": metadata, "coverage": {"sampled_points": [], "watched_intervals": [],
            "server_sampling": "unknown"}, "artifacts": []}, [artifact]


async def verify_prepared(prepared, payloads):
    """Check every original and actual transmitted file before and after inference."""
    for value in prepared:
        source = value["source"]
        if await copy_hash(checked_path(source["path"])) != (source["sha256"], source["bytes"]):
            raise ValueError("Vision original source changed")
        if value.get("manifest"):
            await read_manifest(value["manifest"]["path"], value["manifest"]["sha256"])
    for part in payloads:
        if await copy_hash(checked_path(part["path"])) != (part["sha256"], part["bytes"]):
            raise ValueError("Vision transmitted payload changed")
