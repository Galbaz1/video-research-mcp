"""Byte identities, aliases, unavailable sources and local invalidation contracts."""

import hashlib
import asyncio
import os
from unittest.mock import patch

import pytest

from video_research_mcp.media_identity import identify_source


@pytest.fixture(autouse=True)
def isolated_identity_cache(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))


def test_same_bytes_rename_resolves_one_revision_and_aliases(tmp_path):
    original = tmp_path / "original.mp4"
    original.write_bytes(b"owned media fixture")
    first = identify_source(str(original))
    renamed = tmp_path / "renamed.mp4"
    original.rename(renamed)
    second = identify_source(str(renamed))
    expected = hashlib.sha256(renamed.read_bytes()).hexdigest()
    assert first.digest == second.digest == expected
    assert first.revision == second.revision == "sha256:" + expected
    assert first.state == second.state == "fresh"
    assert second.aliases == tuple(sorted((str(original), str(renamed))))


def test_changed_bytes_create_revision_and_stale_prepared_binding(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"first revision")
    first = identify_source(str(path))
    path.write_bytes(b"second revision")
    current = identify_source(str(path), expected_digest=first.digest)
    assert current.digest != first.digest
    assert current.revision != first.revision
    assert current.previous_digest == first.digest
    assert current.state == "stale"


def test_changed_bytes_with_same_size_and_mtime_create_new_revision(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"version-a")
    first = identify_source(str(path))
    stat = path.stat()
    path.write_bytes(b"version-b")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = identify_source(str(path))
    assert first.digest != second.digest
    assert first.revision != second.revision
    assert second.previous_digest == first.digest


def test_local_deletion_is_explicit_and_invalidation_needs_no_provider(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"original")
    first = identify_source(str(path))
    path.unlink()
    with patch(
        "video_research_mcp.client.GeminiClient.get", side_effect=AssertionError("no provider")
    ):
        deleted = identify_source(str(path))
    assert deleted.state == "deleted"
    assert deleted.previous_digest == first.digest


@pytest.mark.parametrize(
    "source", ["https://example.com/media", "https://youtube.com/watch?v=owned-id", "missing.mp4"]
)
def test_remote_offline_or_absent_unregistered_source_is_unknown(source):
    current = identify_source(source)
    assert current.state == "unknown"


def test_bypass_checks_bytes_without_cache_reads_or_writes(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"owned")
    current = identify_source(str(path), persist=False)
    assert current.state == "fresh"
    assert not (tmp_path / "cache").exists()


def test_unverifiable_legacy_prepared_digest_never_becomes_fresh(tmp_path):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"owned")
    current = identify_source(str(path), expected_digest="truncated-id")
    assert current.state == "unknown"


async def test_context_invalidation_discards_matching_local_state_only(tmp_path):
    from video_research_mcp import context_cache as cc

    cc._registry.clear()
    cc._pending.clear()
    cc._suppressed.clear()
    cc._last_failure.clear()
    cc._loaded = True
    cc._registry[("deleted", "model")] = "cached/deleted"
    cc._registry[("keep", "model")] = "cached/keep"
    cc._suppressed.add(("deleted", "model"))
    cc._last_failure[("deleted", "model")] = "failure"
    pending = asyncio.create_task(asyncio.Event().wait())
    keep_pending = asyncio.create_task(asyncio.Event().wait())
    cc._pending[("deleted", "model")] = pending
    cc._pending[("keep", "model")] = keep_pending
    with patch(
        "video_research_mcp.client.GeminiClient.get", side_effect=AssertionError("no provider")
    ):
        removed = cc.invalidate_content("deleted")
    assert removed == 1
    assert cc.lookup("deleted", "model") is None
    assert cc.lookup("keep", "model") == "cached/keep"
    assert not cc._suppressed and not cc._last_failure
    await asyncio.sleep(0)
    assert pending.cancelled()
    assert not keep_pending.cancelled()
    assert cc._pending == {("keep", "model"): keep_pending}
    keep_pending.cancel()
    await asyncio.gather(keep_pending, return_exceptions=True)
    cc._pending.clear()
    cc._registry.clear()
    cc._loaded = False
