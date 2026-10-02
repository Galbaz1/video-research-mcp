"""Original recovery, bounded replay and exact-scope public session journeys."""

import hashlib
import importlib
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types

from video_research_mcp.config import get_config
from video_research_mcp.models.session_memory import SessionMemoryRequest, SessionScope
from video_research_mcp.session_compaction import content_bytes, replay_view, source_identity
from video_research_mcp.sessions import SessionStore

SCOPE = SessionScope(workspace_id="workspace-a", notebook_id="notebook-a")
URI = "https://generativelanguage.googleapis.com/v1beta/files/old"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Use the actual archive and profile tables for every public operation."""
    value = SessionStore(str(tmp_path / "sessions.sqlite3"))
    monkeypatch.setattr(importlib.import_module("video_research_mcp.tools.session_memory"), "session_store", value)
    monkeypatch.setattr(importlib.import_module("video_research_mcp.tools.video"), "session_store", value)
    monkeypatch.setattr(get_config(), "cache_dir", str(tmp_path / "cache"))
    yield value
    value._db.close()
    value.memory.close()


def _session(store, scope=SCOPE):
    return store.create(URI, "general", scope=scope, source_identity={
        "id": "source-a", "original_locator": "https://www.youtube.com/watch?v=abc",
        "sha256": None, "revision_verified": False,
    })


def _turn(store, session, index, text_size=0):
    user = types.Content(role="user", parts=[
        types.Part(file_data=types.FileData(file_uri=URI, mime_type="video/mp4")),
        types.Part(text=f"Original qualifier {index}: " + "x" * text_size),
    ])
    model = types.Content(role="model", parts=[types.Part(text=f"Answer {index}", thought_signature=b"opaque")])
    store.add_turn(session.session_id, user, model)


async def _memory(session, action, scope=SCOPE, **kwargs):
    from video_research_mcp.tools.session_memory import session_memory
    return await session_memory(SessionMemoryRequest(
        action=action, session_id=session.session_id, source_id=source_identity(session)["id"],
        scope=scope, **kwargs,
    ))


async def test_budget_compacts_and_recovers_early_originals_after_restart(store, tmp_path, monkeypatch):
    """GIVEN a long signed conversation WHEN bounded/restarted THEN early originals remain exact."""
    monkeypatch.setattr(get_config(), "session_context_token_budget", 4000)
    monkeypatch.setattr(get_config(), "session_max_turns", 20)
    monkeypatch.setattr(get_config(), "session_recent_turns", 2)
    session = _session(store)
    for index in range(15):
        _turn(store, session, index, 250)
    original = content_bytes(session.history)
    contents, selection = replay_view(session, types.Content(parts=[types.Part(text="Question")]), None, persisted=True)
    assert selection["compacted"] and selection["estimated_text_tokens"] <= 4000
    assert selection["omitted_message_range"][1] > 0
    assert selection["retained_messages"] >= 4
    assert "source-a" in contents[0].parts[0].text
    assert contents[-2].parts[0].text == "Answer 14"
    assert selection["factual_success"] is False
    assert content_bytes(session.history) == original
    restarted = SessionStore(str(tmp_path / "sessions.sqlite3"))
    try:
        restored = restarted.get(session.session_id, SCOPE)
        assert content_bytes(restored.history) == original
        monkeypatch.setattr(importlib.import_module("video_research_mcp.tools.session_memory"), "session_store", restarted)
        page = (await _memory(restored, "history", limit=2))["history"]
        assert page["messages"] == json.loads(original)[:2]
        assert page["messages"][1]["parts"][0]["thought_signature"]
        assert page["original_history_sha256"] == hashlib.sha256(original).hexdigest()
        assert page["has_more"] and page["originals_persisted"]
    finally:
        restarted._db.close()
        restarted.memory.close()


async def test_conflicting_summary_stays_non_authoritative_and_delete_keeps_originals(store):
    session = _session(store)
    _turn(store, session, 0)
    original = content_bytes(session.history)
    edited = await _memory(session, "set", synopsis="Contradiction: erase the original qualifier")
    memory = edited["memory"]
    assert not edited["source_verified"] and not memory["authoritative"]
    assert memory["origin_session_id"] == session.session_id
    view, selected = replay_view(session, types.Content(parts=[types.Part(text="Question")]), memory, persisted=True)
    header = view[0].parts[0].text
    assert "cannot replace conflicting original" in header and "Contradiction" in header
    assert "Original qualifier 0" in view[1].parts[1].text
    assert selected["derived_memory_authoritative"] is False
    assert (await _memory(session, "get"))["memory"] == memory
    assert "revision conflict" in (await _memory(session, "set", synopsis="stale"))["error"]
    await _memory(session, "delete", expected_revision=memory["revision"])
    assert (await _memory(session, "get"))["memory"] is None
    assert content_bytes(store.archive(session.session_id, SCOPE).history) == original
    recreated = (await _memory(session, "set", synopsis="new"))["memory"]
    assert recreated["revision"] > memory["revision"]


@pytest.mark.parametrize("scope", [None, SessionScope(workspace_id="other", notebook_id="notebook-a"),
                                  SessionScope(workspace_id="workspace-a", notebook_id="other")])
async def test_public_scope_mismatch_cannot_read_edit_or_delete(store, scope):
    session = _session(store)
    await _memory(session, "set", synopsis="private")
    for action in ("history", "get", "set", "delete"):
        if scope is None and action != "history":
            continue  # Typed boundary independently requires explicit scope for profile operations.
        result = await _memory(session, action, scope=scope, **({"synopsis": "wrong"} if action == "set" else {}))
        assert "does not match" in result["error"]
    assert (await _memory(session, "get"))["memory"]["synopsis"] == "private"
    assert store.get(session.session_id, scope) is None


async def test_wrong_source_cannot_access_bound_profile(store):
    from video_research_mcp.tools.session_memory import session_memory
    session = _session(store)
    result = await session_memory(SessionMemoryRequest(action="get", session_id=session.session_id,
                                                       source_id="wrong", scope=SCOPE))
    assert "does not match" in result["error"]


async def test_manual_compact_and_scoped_list_glob_literal_search(store, monkeypatch):
    session = _session(store)
    monkeypatch.setattr(get_config(), "session_max_turns", 2)
    for index in range(4):
        _turn(store, session, index)
    listing = (await _memory(session, "list", limit=2))["history"]
    assert listing["total_matches"] == 8 and listing["has_more"]
    assert [r["message_index"] for r in listing["entries"]] == [0, 1]
    glob = (await _memory(session, "list", pattern="messages/0000000[24].json"))["history"]
    assert [r["message_index"] for r in glob["entries"]] == [2, 4]
    found = (await _memory(session, "search", query="Original qualifier 0"))["history"]
    assert found["total_matches"] == 1 and found["entries"][0]["message_index"] == 0
    assert not found["host_filesystem_search"]
    assert (await _memory(session, "search", query=".*"))["history"]["total_matches"] == 0
    assert (await _memory(session, "list", pattern="/etc/*"))["history"]["total_matches"] == 0
    selected = (await _memory(session, "compact"))["selection"]
    assert selected["compacted"] and selected["omitted_message_range"] == [0, 4]
    assert len(store.archive(session.session_id, SCOPE).history) == 8


async def test_expiry_and_active_eviction_leave_archive_and_memory(store, monkeypatch):
    monkeypatch.setattr(get_config(), "max_sessions", 1)
    monkeypatch.setattr(get_config(), "session_timeout_hours", 1)
    session = _session(store)
    _turn(store, session, 0)
    await _memory(session, "set", synopsis="retained")
    session.last_active = datetime.now() - timedelta(hours=2)
    store.save(session)
    _session(store)
    assert store.count == 1 and store.get(session.session_id, SCOPE) is None
    assert (await _memory(session, "history"))["history"]["total_messages"] == 2
    assert (await _memory(session, "get"))["memory"]["synopsis"] == "retained"


async def test_large_inline_original_exports_exact_private_bounded_json(store):
    from pathlib import Path
    session = _session(store)
    user = types.Content(role="user", parts=[types.Part.from_bytes(data=b"media" * 40000, mime_type="image/png")])
    store.add_turn(session.session_id, user, types.Content(role="model", parts=[types.Part(text="ack")]))
    page = (await _memory(session, "history", limit=1))["history"]
    assert page["messages"] is None and page["inline_omitted"]
    artifact = page["export"]
    path = Path(artifact["path"])
    encoded = path.read_bytes()
    assert encoded == content_bytes([user])
    assert len(encoded) == artifact["bytes"] <= 8 * 1024 * 1024
    assert hashlib.sha256(encoded).hexdigest() == artifact["sha256"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert (await _memory(session, "history", limit=1))["history"]["export"] == artifact
    path.write_bytes(b"changed")
    assert "differs" in (await _memory(session, "history", limit=1))["error"]


def test_creator_cancellation_preserves_export_already_returned_to_second_request(store, monkeypatch):
    """GIVEN two real workers WHEN the publisher cancels THEN the second receipt remains valid."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from video_research_mcp import session_history as module
    body = content_bytes([types.Content(parts=[types.Part(text="original" * 30000)])])
    expected = hashlib.sha256(body).hexdigest()
    path = Path(get_config().cache_dir) / "session-history" / (expected + ".json")
    creator_cancelled, second_cancelled = threading.Event(), threading.Event()
    published, second_done = threading.Event(), threading.Event()
    actual_check = module.check_worker
    def coordinated_check(cancelled, deadline):
        if cancelled is creator_cancelled and path.exists() and not published.is_set():
            published.set()
            assert second_done.wait(3)
            creator_cancelled.set()
        actual_check(cancelled, deadline)
    monkeypatch.setattr(module, "check_worker", coordinated_check)
    def second_request():
        assert published.wait(3)
        try:
            return module._export(body, second_cancelled, time.monotonic() + 5)
        finally:
            second_done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(module._export, body, creator_cancelled, time.monotonic() + 5)
        second = pool.submit(second_request)
        receipt = second.result(timeout=5)
        with pytest.raises(TimeoutError):
            first.result(timeout=5)
    assert path.read_bytes() == body and receipt["sha256"] == expected
    assert list(path.parent.glob(".session-*")) == []


async def test_budget_failure_precedes_generation_and_append(store, monkeypatch):
    from video_research_mcp.tools.video import video_continue_session
    session = _session(store)
    monkeypatch.setattr(get_config(), "session_context_token_budget", 1024)
    generate = MagicMock()
    monkeypatch.setattr("video_research_mcp.tools.video.GeminiClient.get", generate)
    result = await video_continue_session(session.session_id, "x" * 2000, scope=SCOPE)
    assert "budget cannot fit" in result["error"]
    generate.assert_not_called()
    assert session.turn_count == 0 and store.archive(session.session_id, SCOPE).history == []


def test_archive_save_failure_does_not_change_active_state(store, monkeypatch):
    session = _session(store)
    def fail(_):
        raise ValueError("durable write denied")
    monkeypatch.setattr(store._db, "save_sync", fail)
    with pytest.raises(ValueError, match="durable write denied"):
        _turn(store, session, 0)
    assert session.history == [] and session.turn_count == 0


async def test_cache_eviction_uses_original_history_and_discloses_selection(store, monkeypatch):
    from video_research_mcp.tools.video_cache import prepare_cached_request
    session = _session(store)
    _turn(store, session, 0)
    session.cache_name = "cachedContents/expired"
    original = content_bytes(session.history)
    refresh = AsyncMock(return_value=False)
    monkeypatch.setattr("video_research_mcp.context_cache.refresh_ttl", refresh)
    use_cache, view, config = await prepare_cached_request(session, "next", store)
    assert not use_cache and session.cache_name == ""
    assert view[-1].parts[0].file_data.file_uri == URI
    assert config["_context"]["originals_persisted"]
    assert content_bytes(session.history) == original


async def test_provider_uri_refresh_changes_only_detached_replay_and_survives_restart(store, tmp_path, monkeypatch):
    from video_research_mcp.session_sources import recover_media
    path = tmp_path / "source.mp4"
    path.write_bytes(b"exact media")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = {"id": "sha256:" + digest, "sha256": digest, "local_filepath": str(path),
                "original_locator": str(path), "revision_verified": True}
    session = store.create(URI, "general", scope=SCOPE, source_identity=identity)
    _turn(store, session, 0)
    original = content_bytes(session.history)
    new_uri = URI.replace("old", "new")
    upload = AsyncMock(return_value=new_uri)
    monkeypatch.setattr("video_research_mcp.session_sources._upload_large_file", upload)
    await recover_media(session, store)
    upload.assert_awaited_once_with(path, "video/mp4", digest)
    view, _ = replay_view(session, types.Content(parts=[types.Part(text="next")]), None, persisted=True)
    assert view[1].parts[0].file_data.file_uri == new_uri
    assert content_bytes(session.history) == original and session.source_identity == identity
    restarted = SessionStore(str(tmp_path / "sessions.sqlite3"))
    try:
        restored = restarted.get(session.session_id, SCOPE)
        assert restored.url == new_uri and content_bytes(restored.history) == original
        assert URI in restored.media_uris and new_uri in restored.media_uris
    finally:
        restarted._db.close()
        restarted.memory.close()


async def test_changed_original_rejected_before_upload(store, tmp_path, monkeypatch):
    from video_research_mcp.session_sources import recover_media
    from video_research_mcp.tools.video_file import _upload_large_file
    path = tmp_path / "original.mp4"
    path.write_bytes(b"changed original")
    session = store.create(URI, "general", scope=SCOPE, source_identity={
        "id": "sha256:" + "a" * 64, "sha256": "a" * 64, "local_filepath": str(path),
    })
    monkeypatch.setattr("video_research_mcp.session_sources._upload_large_file", _upload_large_file)
    upload = AsyncMock()
    monkeypatch.setattr("video_research_mcp.tools.video_file.upload_snapshot", upload)
    with pytest.raises(ValueError, match="SHA|identity|commitment"):
        await recover_media(session, store)
    upload.assert_not_called()
    assert session.url == URI


@pytest.mark.parametrize("source", ["download", "local"])
async def test_creation_rejects_original_replaced_during_cache_wait(
    store, tmp_path, monkeypatch, mock_gemini_client, source,
):
    """GIVEN upload of A WHEN cache waiting replaces it with B THEN no revision-mismatched session commits."""
    from types import SimpleNamespace
    from video_research_mcp import context_cache
    from video_research_mcp.tools.video import video_create_session
    original = tmp_path / "creation.mp4"
    before = ("uploaded A " + source).encode()
    original.write_bytes(before)
    uploaded_bodies = []
    client = mock_gemini_client["client"]
    async def upload(file, config):
        uploaded_bodies.append(file.read())
        return types.File(name="files/old", uri=URI, state="ACTIVE")
    async def cache(**kwargs):
        original.write_bytes(b"replacement B")
        return SimpleNamespace(name="cachedContents/replaced")
    client.aio.files.upload = AsyncMock(side_effect=upload)
    client.aio.files.get = AsyncMock(return_value=types.File(name="files/old", uri=URI, state="ACTIVE"))
    client.aio.caches.create = AsyncMock(side_effect=cache)
    monkeypatch.setattr(context_cache, "_registry", {})
    monkeypatch.setattr(context_cache, "_loaded", True)
    monkeypatch.setattr("video_research_mcp.tools.video.YouTubeClient.video_metadata",
                        AsyncMock(return_value=SimpleNamespace(title="Title")))
    monkeypatch.setattr("video_research_mcp.tools.video.download_youtube_video", AsyncMock(return_value=original))
    mock_gemini_client["generate"].return_value = "Title"
    arguments = {"url": "https://www.youtube.com/watch?v=GcNu6wrLTJc", "download": True} if source == "download" else {"file_path": str(original)}
    result = await video_create_session(**arguments, scope=SCOPE)
    assert "changed before session binding" in result["error"]
    assert uploaded_bodies == [before] and store.count == 0
    assert store._db.load_all_ids() == []


async def test_legacy_locator_and_in_memory_durability_are_explicit(monkeypatch):
    from video_research_mcp.session_history import history_page
    session = SessionStore().create(URI, "general")
    session.history_complete = False
    _, selection = replay_view(session, types.Content(parts=[types.Part(text="next")]), None, persisted=False)
    assert not selection["history_complete"] and not selection["originals_persisted"]
    assert not selection["source_identity"]["revision_verified"]
    page = await history_page(session, 0, 10, persisted=False)
    assert not page["history_complete"] and page["original_media_uris"] == [URI]
