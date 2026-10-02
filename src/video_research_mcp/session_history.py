"""Paged exact SDK originals with bounded private exports for large inline media."""

import asyncio
import fnmatch
import hashlib
import os
import tempfile
import time
from pathlib import Path

from .config import get_config
from .image_preprocessing import check_worker, image_worker
from .media_local_io import _copy_hash
from .media_snapshot import checked_path
from .session_compaction import ARCHIVE_LIMIT, archive_bytes, history_sha256, source_identity

INLINE_LIMIT = 128 * 1024


def _export(body, cancelled, deadline):
    """Write or revalidate one content-addressed export without overwriting existing data."""
    check_worker(cancelled, deadline)
    digest = hashlib.sha256(body).hexdigest()
    directory = checked_path(str(Path(get_config().cache_dir) / "session-history"))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (digest + ".json")
    fd, staging = tempfile.mkstemp(prefix=".session-", dir=directory)
    staging = Path(staging)
    try:
        with os.fdopen(fd, "wb") as writer:
            writer.write(body)
            writer.flush()
            os.fsync(writer.fileno())
        if _copy_hash(staging, cancelled=cancelled, max_bytes=ARCHIVE_LIMIT) != (digest, len(body)):
            raise ValueError("Staged original-history export differs from its commitment")
        check_worker(cancelled, deadline)
        try:
            os.link(staging, path)
        except FileExistsError:
            pass
        check_worker(cancelled, deadline)
        if _copy_hash(path, cancelled=cancelled, max_bytes=ARCHIVE_LIMIT) != (digest, len(body)):
            raise ValueError("Original-history export differs from its content commitment")
        return {"path": str(path), "sha256": digest, "bytes": len(body), "format": "genai-content-json"}
    finally:
        staging.unlink(missing_ok=True)


async def history_page(session, offset: int, limit: int, *, persisted: bool) -> dict:
    """Recover exact paged originals without activating an expired session or contacting providers."""
    selected = session.history[offset:offset + limit]
    encoded = archive_bytes(selected)
    export = None
    if len(encoded) > INLINE_LIMIT:
        timeout = get_config().media_acquire_timeout_seconds
        async with asyncio.timeout(timeout):
            export = await image_worker(_export, encoded, deadline=time.monotonic() + timeout)
    return {
        "session_id": session.session_id, "source_identity": source_identity(session),
        "original_history_sha256": history_sha256(session), "history_complete": session.history_complete,
        "originals_persisted": persisted, "total_messages": len(session.history),
        "offset": offset, "returned_messages": len(selected), "next_offset": offset + len(selected),
        "has_more": offset + len(selected) < len(session.history),
        "messages": [c.model_dump(mode="json", exclude_none=True) for c in selected] if export is None else None,
        "export": export, "inline_omitted": export is not None,
        "original_media_uris": session.media_uris, "current_media_uri": session.url,
        "authoritative_media_evidence": False,
    }


def history_index(session, request) -> dict:
    """List/glob logical message files or search literal original text within one bound archive."""
    matches, total = [], 0
    for index, content in enumerate(session.history):
        name = f"messages/{index:08d}.json"
        if not fnmatch.fnmatchcase(name, request.pattern):
            continue
        texts = [part.text for part in content.parts or [] if part.text]
        if request.action == "search" and not any(request.query in text for text in texts):
            continue
        if request.offset <= total < request.offset + request.limit:
            matches.append({"name": name, "message_index": index, "role": content.role,
                            "text_parts": len(texts),
                            "media_parts": sum(bool(p.file_data or p.inline_data) for p in content.parts or []),
                            "refetch": {"action": "history", "offset": index, "limit": 1}})
        total += 1
    return {"session_id": session.session_id, "source_identity": source_identity(session),
            "original_history_sha256": history_sha256(session),
            "history_complete": session.history_complete, "total_matches": total,
            "entries": matches, "next_offset": request.offset + len(matches),
            "has_more": request.offset + len(matches) < total,
            "search_method": "literal original text" if request.action == "search" else "glob of logical message names",
            "host_filesystem_search": False, "authoritative_media_evidence": False}
