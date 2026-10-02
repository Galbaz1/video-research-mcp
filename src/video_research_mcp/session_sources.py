"""Original source bindings and account-scoped provider resource recovery."""

import asyncio
import hashlib
import time
from dataclasses import replace
from pathlib import Path

from .config import get_config
from .image_preprocessing import check_worker, image_worker
from .media_local_io import _copy_hash
from .media_snapshot import checked_path
from .tools.video_file import _upload_large_file, _video_mime_type


def _source_hash(path, cancelled, deadline):
    """Join a bounded original read when a downloaded source has no returned digest."""
    check_worker(cancelled, deadline)
    digest = _copy_hash(checked_path(str(path)), cancelled=cancelled)[0]
    check_worker(cancelled, deadline)
    return digest


async def local_digest(path: Path) -> str:
    """Commit bounded original bytes with a joined worker and caller deadline."""
    timeout = get_config().media_acquire_timeout_seconds
    async with asyncio.timeout(timeout):
        return await image_worker(_source_hash, path, deadline=time.monotonic() + timeout)


async def bind_source(original: str, local_path: str, digest: str) -> dict:
    """Verify the uploaded revision still exists before binding its original origin."""
    if local_path:
        actual = await local_digest(Path(local_path))
        if digest and actual != digest:
            raise ValueError("Original source bytes changed before session binding; no session was created")
        digest = actual
    return {
        "id": "sha256:" + digest if digest else "locator:" + hashlib.sha256(original.encode()).hexdigest(),
        "original_locator": original, "local_filepath": local_path,
        "sha256": digest or None, "revision_verified": bool(digest),
        "source_type": "local_bytes" if digest else "remote_locator",
    }


async def recover_media(session, store) -> None:
    """Reconcile exact original bytes through the existing no-duplicate upload contract."""
    identity = session.source_identity
    if not identity.get("sha256"):
        return
    path = Path(identity["local_filepath"])
    uri = await _upload_large_file(path, _video_mime_type(path), identity["sha256"])
    if uri == session.url:
        return
    staged = replace(session, url=uri, cache_name="", model="",
                     media_uris=list(dict.fromkeys([*session.media_uris, session.url, uri])))
    store.save(staged)
    session.url, session.cache_name, session.model = uri, "", ""
    session.media_uris = staged.media_uris
