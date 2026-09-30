"""Tests for SQLite session persistence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from google.genai import types

import video_research_mcp.config as cfg_mod
from video_research_mcp.persistence import (
    SessionDB,
    _content_to_dict,
    _dict_to_content,
)
from video_research_mcp.sessions import VideoSession


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "test_sessions.db")


@pytest.fixture()
def db(db_path):
    d = SessionDB(db_path)
    yield d
    d.close()


def _make_session(
    sid="abc123",
    url="https://youtube.com/watch?v=test",
    turn_count=0,
    history=None,
):
    return VideoSession(
        session_id=sid,
        url=url,
        mode="general",
        video_title="Test Video",
        history=history or [],
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        last_active=datetime(2025, 1, 1, 12, 30, 0),
        turn_count=turn_count,
    )


class TestSessionDB:
    def test_roundtrip_save_load(self, db):
        """GIVEN a session WHEN saved and loaded THEN fields match."""
        session = _make_session()
        db.save_sync(session)
        loaded = db.load_sync("abc123")
        assert loaded is not None
        assert loaded.session_id == "abc123"
        assert loaded.url == "https://youtube.com/watch?v=test"
        assert loaded.video_title == "Test Video"
        assert loaded.turn_count == 0

    def test_load_missing_returns_none(self, db):
        """GIVEN no session stored WHEN loading THEN returns None."""
        assert db.load_sync("nonexistent") is None

    def test_overwrite_existing(self, db):
        """GIVEN a stored session WHEN saved again with changes THEN updated."""
        session = _make_session(turn_count=0)
        db.save_sync(session)
        session.turn_count = 5
        db.save_sync(session)
        loaded = db.load_sync("abc123")
        assert loaded.turn_count == 5

    def test_history_serialization(self, db):
        """GIVEN a session with history WHEN roundtripped THEN history preserved."""
        history = [
            types.Content(role="user", parts=[types.Part(text="Hello")]),
            types.Content(role="model", parts=[types.Part(text="Hi there")]),
        ]
        session = _make_session(history=history, turn_count=1)
        db.save_sync(session)
        loaded = db.load_sync("abc123")
        assert len(loaded.history) == 2
        assert loaded.history[0].role == "user"
        assert loaded.history[0].parts[0].text == "Hello"
        assert loaded.history[1].role == "model"
        assert loaded.history[1].parts[0].text == "Hi there"

    def test_load_all_ids(self, db):
        """GIVEN multiple sessions WHEN load_all_ids THEN returns all IDs."""
        db.save_sync(_make_session(sid="aaa"))
        db.save_sync(_make_session(sid="bbb"))
        ids = db.load_all_ids()
        assert set(ids) == {"aaa", "bbb"}

    def test_delete(self, db):
        """GIVEN a stored session WHEN deleted THEN no longer loadable."""
        db.save_sync(_make_session())
        assert db.delete("abc123") is True
        assert db.load_sync("abc123") is None

    def test_delete_missing_returns_false(self, db):
        """GIVEN no session WHEN delete called THEN returns False."""
        assert db.delete("nonexistent") is False

    def test_creates_parent_dirs(self, tmp_path):
        """GIVEN a nested path WHEN creating DB THEN parent dirs created."""
        nested = str(tmp_path / "deep" / "nested" / "sessions.db")
        d = SessionDB(nested)
        d.save_sync(_make_session())
        d.close()
        assert Path(nested).exists()


class TestContentSerialization:
    def test_text_content_roundtrip(self):
        content = types.Content(
            role="user", parts=[types.Part(text="test")]
        )
        d = _content_to_dict(content)
        result = _dict_to_content(d)
        assert result.role == "user"
        assert result.parts[0].text == "test"

    def test_file_data_roundtrip(self):
        content = types.Content(
            role="user",
            parts=[
                types.Part(
                    file_data=types.FileData(
                        file_uri="gs://bucket/file"
                    )
                )
            ],
        )
        d = _content_to_dict(content)
        result = _dict_to_content(d)
        assert result.parts[0].file_data.file_uri == "gs://bucket/file"

    def test_thought_signature_and_metadata_roundtrip(self, db):
        """GIVEN signed model content WHEN SQLite roundtrips THEN signatures survive."""
        content = types.Content(role="model", parts=[
            types.Part(text="Thought summary", thought=True),
            types.Part(text="Answer", thought_signature=b"\xff\x00signature"),
        ])
        db.save_sync(_make_session(history=[content]))
        loaded = db.load_sync("abc123")

        assert loaded.history[0] == content
        assert loaded.history[0].parts[1].thought_signature == b"\xff\x00signature"
