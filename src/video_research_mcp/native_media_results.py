"""Bounded native-image transport with identical source/artifact metadata in text mode."""

import asyncio
import base64
import hashlib
import json
import re
import shutil
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.types import CallToolResult, ImageContent, TextContent

from .config import get_config
from .errors import make_tool_error
from .media_acquisition import _wait_worker
from .media_image_read import MAX_ARTIFACT_BYTES
from .media_local_io import _copy_hash, _open_regular
from .models.native_media import NativeMediaResult

INLINE_IMAGE_BYTES = 1024 * 1024
INLINE_TOTAL_BYTES = 8 * 1024 * 1024


def _native_blocks(result: NativeMediaResult, include_image: bool, canceled: threading.Event) -> list[ImageContent]:
    """Recheck each emitted PNG and bound total decoded binary payload bytes."""
    artifacts = [result.artifact] if result.artifact else result.frames
    if sum(artifact.bytes for artifact in artifacts) > MAX_ARTIFACT_BYTES:
        raise ValueError("Native artifacts exceed the aggregate artifact byte budget")
    blocks, used = [], 0
    for artifact in artifacts:
        if canceled.is_set():
            raise TimeoutError("Native image transport canceled")
        verified = _copy_hash(Path(artifact.path), cancelled=canceled, max_bytes=MAX_ARTIFACT_BYTES)
        if verified != (artifact.sha256, artifact.bytes):
            raise ValueError("Extracted media artifact changed before native transport")
        if not include_image:
            continue
        if artifact.bytes > INLINE_IMAGE_BYTES:
            artifact.native_image_status = "inline_byte_limit"
            continue
        if used + artifact.bytes > INLINE_TOTAL_BYTES:
            artifact.native_image_status = "inline_total_limit"
            continue
        with _open_regular(Path(artifact.path)) as stream:
            data = stream.read(INLINE_IMAGE_BYTES + 1)
        if len(data) != artifact.bytes or hashlib.sha256(data).hexdigest() != artifact.sha256:
            raise ValueError("Extracted media artifact changed before native transport")
        used += len(data)
        artifact.native_image_status = "included"
        blocks.append(ImageContent(type="image", mimeType="image/png", data=base64.b64encode(data).decode()))
    if blocks:
        result.native_image_status = "included" if len(blocks) == len(artifacts) else "partial"
    elif include_image and artifacts:
        result.native_image_status = artifacts[0].native_image_status
    result.limits.update({"inline_image_bytes": INLINE_IMAGE_BYTES, "inline_total_bytes": INLINE_TOTAL_BYTES})
    return blocks


async def native_result(metadata: dict, include_image: bool) -> CallToolResult:
    """Validate local output and emit native PNG blocks or the same text identities."""
    result = NativeMediaResult.model_validate(metadata)
    canceled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(_native_blocks, result, include_image, canceled))
    blocks = await _wait_worker(task, canceled)
    value = result.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(value)), *blocks],
        structured_content=value,
    )


def _discard_views(results: list[dict], base: Path) -> None:
    """Delete only internally produced UUID view slots from this public invocation."""
    directories = set()
    for result in results:
        artifacts = (result.get("frames", []) + result.get("artifacts", [])
                     + ([result["artifact"]] if result.get("artifact") else []))
        directories.update(Path(artifact["path"]).parent for artifact in artifacts)
    for directory in directories:
        if directory.parent != base or not re.fullmatch(r"[0-9a-f]{32}", directory.name):
            raise PermissionError("Native cleanup rejected an unowned artifact location")
        if any(parent.is_symlink() for parent in directory.parents):
            raise PermissionError("Native cleanup rejected a substituted parent directory")
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)


@asynccontextmanager
async def native_operation():
    """Join a public operation's stages and remove generated views on failure/cancel."""
    results = []
    cfg = get_config()
    base = Path(cfg.cache_dir).expanduser().resolve() / "media" / "views"
    try:
        async with asyncio.timeout(cfg.media_acquire_timeout_seconds):
            yield results
    except BaseException:
        _discard_views(results, base)
        raise


def native_error(exc: Exception) -> CallToolResult:
    """Return a redacted typed error without a partial native payload."""
    value = make_tool_error(exc)
    if isinstance(exc, ImportError):
        value.update(category="DEPENDENCY_MISSING", hint=value["error"], retryable=False)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(value))],
        structured_content=value,
        is_error=True,
    )
