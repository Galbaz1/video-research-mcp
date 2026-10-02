"""Checked media GET and metadata-only HEAD transport."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

from .url_policy import UrlPolicyError, checked_response


def _headers(response) -> dict:
    """Retain response metadata without treating headers as verified bytes."""
    length = response.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) < 0):
        raise UrlPolicyError("Invalid Content-Length header")
    return {
        "final_url": str(response.url),
        "content_type": response.headers.get("content-type", ""),
        "content_length": int(length) if length is not None else None,
    }


async def head_resource(url: str) -> dict:
    """Return checked HEAD metadata without consuming any response body."""
    async with checked_response(url, "HEAD") as response:
        return _headers(response)


async def fetch_resource(
    url: str, directory: Path, *, max_bytes: int,
    allowed_content_types: tuple[str, ...] | None = None,
) -> dict:
    """Stream checked bytes into one owned file with a full content digest."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"resource-{uuid4().hex}.bin"
    digest = hashlib.sha256()
    count = 0
    try:
        async with checked_response(url) as response:
            metadata = _headers(response)
            if allowed_content_types is not None:
                media_type = metadata["content_type"].split(";", 1)[0].strip().lower()
                if media_type not in allowed_content_types:
                    raise UrlPolicyError("Response Content-Type is not allowed for metadata retrieval")
            if metadata["content_length"] is not None and metadata["content_length"] > max_bytes:
                raise UrlPolicyError(f"Response exceeds size limit ({max_bytes} bytes)")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                async for chunk in response.aiter_bytes():
                    count += len(chunk)
                    if count > max_bytes:
                        raise UrlPolicyError(f"Response exceeds size limit ({max_bytes} bytes)")
                    digest.update(chunk)
                    output.write(chunk)
        return {**metadata, "path": path, "bytes": count, "sha256": digest.hexdigest()}
    except BaseException:
        path.unlink(missing_ok=True)
        raise
