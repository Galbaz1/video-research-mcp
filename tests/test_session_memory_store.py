"""Actual SQLite controls for complete archives and scoped learned memory."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime

import pytest
from google.genai import types

from video_research_mcp.persistence import MAX_HISTORY_BYTES, SessionDB, _content_to_dict
from video_research_mcp.session_memory_store import MAX_SYNOPSIS_BYTES, SourceMemoryDB
from video_research_mcp.sessions import VideoSession

SCOPE = ("workspace-a", "notebook-a", "source-a")
IDENTITY = {
    "id": "source-a", "original_locator": "https://example.test/original.mp4",
    "sha256": "a" * 64, "source_type": "video", "local_filepath": "/owned/video.mp4",
}


def _history() -> list[types.Content]:
    return [
        types.Content(role="user", parts=[
            types.Part(file_data=types.FileData(
                file_uri="gs://provider/first.mp4", mime_type="video/mp4",
            ), video_metadata=types.VideoMetadata(start_offset="1s", end_offset="3s")),
            types.Part(inline_data=types.Blob(data=b"\xff\x00\x01media", mime_type="image/png")),
            types.Part(text="Original evidence and source-a"),
        ]),
        types.Content(role="model", parts=[
            types.Part(text="Reasoning", thought=True),
            types.Part(text="Original answer", thought_signature=b"\xff\x00opaque-signature"),
        ]),
    ]


def _session() -> VideoSession:
    return VideoSession(
        session_id="session-a", url="gs://provider/first.mp4", mode="general",
        history=_history(), turn_count=1, created_at=datetime(2026, 1, 1),
        last_active=datetime(2026, 1, 2), workspace_id=SCOPE[0], notebook_id=SCOPE[1],
        source_identity=IDENTITY.copy(), media_uris=["gs://provider/first.mp4"],
    )


def _put(db: SourceMemoryDB, scope=SCOPE, synopsis="Synopsis", revision=0) -> dict:
    return db.put(
        scope, synopsis, "source-revision", "b" * 64, revision,
        origin_session_id="session-a",
    )


def test_legacy_migration_preserves_signed_media_and_discloses_unknown_history(tmp_path):
    """GIVEN an old SQLite row WHEN migrated THEN exact SDK history survives."""
    path = tmp_path / "legacy.sqlite3"
    original = _history()
    history_json = json.dumps([_content_to_dict(content) for content in original])
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, url TEXT NOT NULL, mode TEXT NOT NULL,
            video_title TEXT NOT NULL DEFAULT '', history TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL, last_active TEXT NOT NULL,
            turn_count INTEGER NOT NULL DEFAULT 0
        )""")
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy", "gs://legacy/current.mp4", "general", "Title", history_json,
             "2026-01-01T00:00:00", "2026-01-02T00:00:00", 20),
        )
    db = SessionDB(str(path))
    loaded = db.load_sync("legacy")
    assert loaded.history == original
    assert loaded.history[0].parts[1].inline_data.data == b"\xff\x00\x01media"
    assert loaded.history[1].parts[1].thought_signature == b"\xff\x00opaque-signature"
    assert loaded.source_identity == {}
    assert (loaded.workspace_id, loaded.notebook_id, loaded.media_uris) == ("", "", [])
    assert loaded.history_complete is False
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT history FROM sessions").fetchone()[0] == history_json
    with pytest.raises(ValueError, match="cannot be relabeled"):
        db.save_sync(replace(loaded, history_complete=True))
    db.save_sync(loaded)
    db.close()


def test_new_archive_restart_roundtrips_identity_and_provider_aliases(tmp_path):
    """GIVEN an archived source WHEN restarted THEN source and raw SDK parts match."""
    path = tmp_path / "archive.sqlite3"
    session = _session()
    db = SessionDB(str(path))
    db.save_sync(session)
    refreshed = replace(
        session, url="gs://provider/refreshed.mp4",
        media_uris=[*session.media_uris, "gs://provider/refreshed.mp4"],
    )
    db.save_sync(refreshed)
    db.close()
    restarted = SessionDB(str(path))
    loaded = restarted.load_sync(session.session_id)
    assert loaded == refreshed
    assert loaded.history_complete is True
    assert loaded.history[0].parts[0].file_data.file_uri == "gs://provider/first.mp4"
    assert loaded.source_identity["original_locator"] == IDENTITY["original_locator"]
    restarted.close()


def test_archive_size_failure_leaves_existing_row_exactly_unchanged(tmp_path):
    """GIVEN a valid archive WHEN an oversize write fails THEN it stays recoverable."""
    path = tmp_path / "archive.sqlite3"
    db = SessionDB(str(path))
    session = _session()
    db.save_sync(session)
    with sqlite3.connect(path) as conn:
        before = conn.execute("SELECT * FROM sessions").fetchone()
    oversize = replace(session, history=[*session.history, types.Content(
        role="user", parts=[types.Part(text="x" * MAX_HISTORY_BYTES)],
    )], turn_count=2)
    with pytest.raises(ValueError, match="8 MiB"):
        db.save_sync(oversize)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM sessions").fetchone() == before
    assert db.load_sync(session.session_id) == session
    db.save_sync(replace(session, cache_name="refreshed-cache"))
    assert db.load_sync(session.session_id).cache_name == "refreshed-cache"
    db.close()


def test_two_archive_instances_reject_divergent_or_shortened_history(tmp_path):
    """GIVEN stale readers WHEN one appends THEN another cannot erase its raw turns."""
    path = tmp_path / "archive.sqlite3"
    first, second = SessionDB(str(path)), SessionDB(str(path))
    session = _session()
    first.save_sync(session)
    stale = second.load_sync(session.session_id)
    added = [types.Content(role="user", parts=[types.Part(text="Next original")])]
    current = replace(session, history=[*session.history, *added], turn_count=2)
    first.save_sync(current)
    with pytest.raises(ValueError, match="archived prefix"):
        second.save_sync(replace(stale, history=[*stale.history, types.Content(
            role="user", parts=[types.Part(text="Conflicting stale append")],
        )], turn_count=2))
    with pytest.raises(ValueError, match="archived prefix"):
        second.save_sync(stale)
    assert second.load_sync(session.session_id) == current
    first.close()
    second.close()


def test_equal_history_metadata_refresh_cannot_roll_back_turn_counter(tmp_path):
    db = SessionDB(str(tmp_path / "archive.sqlite3"))
    session = _session()
    db.save_sync(session)
    with pytest.raises(ValueError, match="cannot decrease"):
        db.save_sync(replace(session, turn_count=0))
    assert db.load_sync(session.session_id) == session
    db.close()


@pytest.mark.parametrize("changes", [
    {"workspace_id": "other-workspace"}, {"notebook_id": "other-notebook"},
    {"source_identity": {**IDENTITY, "sha256": "c" * 64}},
])
def test_archive_source_and_scope_are_immutable(tmp_path, changes):
    db = SessionDB(str(tmp_path / "archive.sqlite3"))
    session = _session()
    db.save_sync(session)
    with pytest.raises(ValueError, match="immutable"):
        db.save_sync(replace(session, **changes))
    assert db.load_sync(session.session_id) == session
    db.close()


def test_two_memory_instances_reject_stale_updates_and_deletion(tmp_path):
    """GIVEN two actual connections WHEN one updates THEN stale CAS cannot mutate."""
    path = tmp_path / "memory.sqlite3"
    first, second = SourceMemoryDB(str(path)), SourceMemoryDB(str(path))
    initial = _put(first)
    stale = second.get(SCOPE)
    current = _put(first, synopsis="Edited synopsis", revision=initial["revision"])
    assert current["revision"] == 2
    with pytest.raises(ValueError, match="revision conflict"):
        _put(second, synopsis="Stale write", revision=stale["revision"])
    with pytest.raises(ValueError, match="revision conflict"):
        second.delete(SCOPE, stale["revision"])
    assert second.get(SCOPE) == current
    assert current["authoritative"] is current["source_verified"] is False
    assert current["origin_session_id"] == "session-a"
    first.close()
    second.close()
    restarted = SourceMemoryDB(str(path))
    assert restarted.get(SCOPE) == current
    restarted.close()


def test_memory_scope_isolates_identical_source_ids(tmp_path):
    """GIVEN one source in three profiles WHEN edited THEN only its exact scope changes."""
    db = SourceMemoryDB(str(tmp_path / "memory.sqlite3"))
    scopes = [SCOPE, (SCOPE[0], "notebook-b", SCOPE[2]), ("workspace-b", SCOPE[1], SCOPE[2])]
    records = [_put(db, scope, f"Profile {index}") for index, scope in enumerate(scopes)]
    changed = _put(db, scopes[1], "Edited second profile", revision=1)
    assert db.get(scopes[0]) == records[0]
    assert db.get(scopes[1]) == changed
    assert db.get(scopes[2]) == records[2]
    assert db.get(("workspace-b", "notebook-b", SCOPE[2])) is None
    db.close()


@pytest.mark.parametrize("scope", [(), ("", "n", "s"), ("w", "", "s"), ("w", "n", " ")])
def test_memory_rejects_unscoped_operations_without_fallback(tmp_path, scope):
    db = SourceMemoryDB(str(tmp_path / "memory.sqlite3"))
    existing = _put(db)
    for operation in (
        lambda: db.get(scope), lambda: _put(db, scope), lambda: db.delete(scope, 0),
    ):
        with pytest.raises(ValueError, match="scope"):
            operation()
    assert db.get(SCOPE) == existing
    db.close()


def test_delete_clears_contents_and_recreate_keeps_monotone_revision(tmp_path):
    """GIVEN a deleted record WHEN recreated THEN pre-delete revision tokens stay stale."""
    path = tmp_path / "memory.sqlite3"
    db = SourceMemoryDB(str(path))
    original = _put(db)
    assert db.delete(SCOPE, original["revision"]) is True
    assert db.get(SCOPE) is None
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT synopsis, source_revision, history_sha256, origin_session_id, revision "
            "FROM source_memory"
        ).fetchone()
    assert row == (None, None, None, None, 2)
    db.close()
    restarted = SourceMemoryDB(str(path))
    assert restarted.get(SCOPE) is None
    recreated = _put(restarted, synopsis="Recreated synopsis", revision=0)
    assert recreated["revision"] == 3
    with pytest.raises(ValueError, match="revision conflict"):
        restarted.delete(SCOPE, original["revision"])
    with pytest.raises(ValueError, match="revision conflict"):
        _put(restarted, synopsis="Stale pre-delete edit", revision=original["revision"])
    assert restarted.get(SCOPE) == recreated
    restarted.close()


def test_delete_absent_memory_is_exactly_noop(tmp_path):
    db = SourceMemoryDB(str(tmp_path / "memory.sqlite3"))
    assert db.delete(SCOPE, 0) is False
    with pytest.raises(ValueError, match="revision conflict"):
        db.delete(SCOPE, 1)
    assert db.get(SCOPE) is None
    db.close()


def test_memory_mutations_leave_original_session_history_and_media_untouched(tmp_path):
    """GIVEN shared SQLite WHEN learned memory changes THEN archival evidence stays exact."""
    path = tmp_path / "shared.sqlite3"
    archive, memory = SessionDB(str(path)), SourceMemoryDB(str(path))
    session = _session()
    archive.save_sync(session)
    with sqlite3.connect(path) as conn:
        before = conn.execute("SELECT * FROM sessions").fetchone()
    initial = _put(memory)
    changed = _put(memory, synopsis="Edited learned claim", revision=initial["revision"])
    memory.delete(SCOPE, changed["revision"])
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT * FROM sessions").fetchone() == before
    assert archive.load_sync(session.session_id) == session
    archive.close()
    memory.close()


def test_synopsis_limit_counts_utf8_bytes_and_failure_does_not_mutate(tmp_path):
    db = SourceMemoryDB(str(tmp_path / "memory.sqlite3"))
    exact = "é" * (MAX_SYNOPSIS_BYTES // 2)
    initial = _put(db, synopsis=exact)
    assert db.get(SCOPE)["synopsis"] == exact
    with pytest.raises(ValueError, match="32 KiB"):
        _put(db, synopsis=exact + "é", revision=initial["revision"])
    assert db.get(SCOPE) == initial
    db.close()


def test_origin_session_pointer_is_required(tmp_path):
    db = SourceMemoryDB(str(tmp_path / "memory.sqlite3"))
    with pytest.raises(ValueError, match="Origin session ID"):
        db.put(SCOPE, "Synopsis", "source-revision", "b" * 64, 0, origin_session_id="")
    assert db.get(SCOPE) is None
    db.close()
