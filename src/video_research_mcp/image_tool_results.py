"""Verified bounded image transport for independently authored image operations."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import threading
from pathlib import Path

from mcp.types import ImageContent

from .media_acquisition import _wait_worker
from .media_local_io import _copy_hash, _open_regular
from .media_snapshot import checked_path
from .native_media_results import INLINE_IMAGE_BYTES, INLINE_TOTAL_BYTES


def _blocks(metadata: dict, include_image: bool, canceled: threading.Event) -> tuple:
    """Rehash every declared artifact, including text-only and nonimage artifacts."""
    artifacts = metadata.get("artifacts", [])
    if sum(artifact["bytes"] for artifact in artifacts) > INLINE_TOTAL_BYTES:
        raise ValueError("Image operation artifacts exceed 8 MiB")
    blocks, delivery, used = [], [], 0
    for artifact in artifacts:
        path = checked_path(artifact["path"])
        if _copy_hash(path, cancelled=canceled, max_bytes=INLINE_TOTAL_BYTES) != (
            artifact["sha256"], artifact["bytes"]
        ):
            raise ValueError("Image operation artifact changed before transport")
        mime = artifact["mime"]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"}:
            continue
        status = "text_only"
        if include_image:
            if mime in {"image/bmp", "image/gif"}:
                delivery.append({"path": str(path), "mime": mime, "status": "unsupported_native_mime"})
                continue
            status = "inline_byte_limit"
            if artifact["bytes"] <= INLINE_IMAGE_BYTES:
                status = "inline_total_limit"
                if used + artifact["bytes"] <= INLINE_TOTAL_BYTES:
                    with _open_regular(Path(path)) as stream:
                        data = stream.read(INLINE_IMAGE_BYTES + 1)
                    if len(data) != artifact["bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                        raise ValueError("Image operation artifact changed while reading transport")
                    blocks.append(ImageContent(type="image", mimeType=mime,
                                               data=base64.b64encode(data).decode()))
                    used += len(data)
                    status = "included"
        delivery.append({"path": str(path), "mime": mime, "status": status})
    return blocks, delivery


async def image_blocks(metadata: dict, include_image: bool) -> tuple:
    """Join cooperative verification before delivering native or text output."""
    canceled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(_blocks, metadata, include_image, canceled))
    return await _wait_worker(task, canceled)
