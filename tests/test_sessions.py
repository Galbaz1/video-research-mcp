"""Tests for the in-memory session store."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import video_research_mcp.config as cfg_mod
from video_research_mcp.sessions import SessionStore

from google.genai import types


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    cfg_mod._config = None
    yield
    cfg_mod._config = None


class TestSessionStore:
    def test_create_session(self):
        store = SessionStore()
        session = store.create("https://youtube.com/watch?v=abc", "general")
        assert session.session_id
        assert session.url == "https://youtube.com/watch?v=abc"
        assert session.turn_count == 0

    def test_get_session(self):
        store = SessionStore()
        session = store.create("https://youtube.com/watch?v=abc", "general")
        found = store.get(session.session_id)
        assert found is not None
        assert found.session_id == session.session_id

    def test_get_missing_session(self):
        store = SessionStore()
        assert store.get("nonexistent") is None

    def test_add_turn(self):
        store = SessionStore()
        session = store.create("https://youtube.com/watch?v=abc", "general")
        user = types.Content(role="user", parts=[types.Part(text="hello")])
        model = types.Content(role="model", parts=[types.Part(text="hi")])
        count = store.add_turn(session.session_id, user, model)
        assert count == 1
        assert len(session.history) == 2

    def test_eviction_by_max(self):
        store = SessionStore()
        store._sessions.clear()
        # Override max via config
        cfg_mod._config = cfg_mod.ServerConfig(
            gemini_api_key="test", max_sessions=2, session_timeout_hours=24
        )
        store.create("url1", "general")
        store.create("url2", "general")
        store.create("url3", "general")  # Should evict oldest
        assert store.count <= 2

    def test_expired_sessions_evicted(self):
        store = SessionStore()
        store._sessions.clear()
        cfg_mod._config = cfg_mod.ServerConfig(
            gemini_api_key="test", max_sessions=50, session_timeout_hours=1
        )
        session = store.create("url1", "general")
        # Manually expire
        session.last_active = datetime.now() - timedelta(hours=2)
        store._evict_expired()
        assert store.get(session.session_id) is None

    def test_original_history_survives_max_turn_window(self):
        store = SessionStore()
        cfg_mod._config = cfg_mod.ServerConfig(
            gemini_api_key="test",
            max_sessions=50,
            session_timeout_hours=24,
            session_max_turns=2,
        )
        session = store.create("https://youtube.com/watch?v=abc", "general")
        for i in range(3):
            user = types.Content(role="user", parts=[types.Part(text=f"u{i}")])
            model = types.Content(role="model", parts=[types.Part(text=f"m{i}")])
            store.add_turn(session.session_id, user, model)

        assert session.turn_count == 3
        assert len(session.history) == 6
        latest_text = [p.text for c in session.history for p in c.parts if p.text]
        assert latest_text == ["u0", "m0", "u1", "m1", "u2", "m2"]


class TestSessionStorePersistence:
    """Session store with SQLite persistence."""

    def test_persist_and_recover(self, tmp_path):
        """GIVEN persistence enabled WHEN session created THEN recoverable from new store."""
        db_path = str(tmp_path / "sessions.db")
        store1 = SessionStore(db_path=db_path)
        session = store1.create(
            "https://youtube.com/watch?v=test", "general", "Test", local_filepath="/tmp/test.mp4"
        )

        # New store with same DB should recover the session
        store2 = SessionStore(db_path=db_path)
        recovered = store2.get(session.session_id)
        assert recovered is not None
        assert recovered.url == "https://youtube.com/watch?v=test"
        assert recovered.local_filepath == "/tmp/test.mp4"

    def test_no_persistence_by_default(self):
        """GIVEN no db_path WHEN store created THEN _db is None."""
        store = SessionStore()
        assert store._db is None

    def test_add_turn_persists(self, tmp_path):
        """GIVEN persistence enabled WHEN turn added THEN persisted."""
        db_path = str(tmp_path / "sessions.db")
        store = SessionStore(db_path=db_path)
        session = store.create(
            "https://youtube.com/watch?v=test", "general"
        )
        user = types.Content(role="user", parts=[types.Part(text="Q")])
        model = types.Content(role="model", parts=[types.Part(text="A")])
        store.add_turn(session.session_id, user, model)

        # Recover from fresh store
        store2 = SessionStore(db_path=db_path)
        recovered = store2.get(session.session_id)
        assert recovered.turn_count == 1
        assert len(recovered.history) == 2
