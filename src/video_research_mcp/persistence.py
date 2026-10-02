"""SQLite-backed complete session archives with WAL mode."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from google.genai import types

MAX_HISTORY_BYTES = 8 * 1024 * 1024

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    mode TEXT NOT NULL,
    video_title TEXT NOT NULL DEFAULT '',
    cache_name TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    local_filepath TEXT NOT NULL DEFAULT '',
    history TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_active TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    workspace_id TEXT NOT NULL DEFAULT '',
    notebook_id TEXT NOT NULL DEFAULT '',
    source_identity TEXT NOT NULL DEFAULT '{}',
    media_uris TEXT NOT NULL DEFAULT '[]',
    history_complete INTEGER NOT NULL DEFAULT 0
);
"""


class SessionDB:
    """Synchronous SQLite persistence for complete video-session history."""

    def __init__(self, db_path: str) -> None:
        """Open the archive and safely add missing columns to legacy databases."""
        path = Path(db_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Leave legacy identity unknown and formerly truncated history incomplete."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}
        additions = {
            "cache_name": "TEXT NOT NULL DEFAULT ''",
            "model": "TEXT NOT NULL DEFAULT ''",
            "local_filepath": "TEXT NOT NULL DEFAULT ''",
            "workspace_id": "TEXT NOT NULL DEFAULT ''",
            "notebook_id": "TEXT NOT NULL DEFAULT ''",
            "source_identity": "TEXT NOT NULL DEFAULT '{}'",
            "media_uris": "TEXT NOT NULL DEFAULT '[]'",
            "history_complete": "INTEGER NOT NULL DEFAULT 0",
        }
        with self._conn:
            for name, definition in additions.items():
                if name not in columns:
                    self._conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")

    def save_sync(self, session) -> None:
        """Archive a session, rejecting oversize, truncated or divergent replacements."""
        history = [_content_to_dict(content) for content in session.history]
        history_json = json.dumps(history)
        if len(history_json.encode("utf-8")) > MAX_HISTORY_BYTES:
            raise ValueError("Serialized session history exceeds the 8 MiB archive limit")
        identity_json = json.dumps(session.source_identity)
        values = (
            session.session_id, session.url, session.mode, session.video_title,
            session.cache_name, session.model, session.local_filepath, history_json,
            session.created_at.isoformat(), session.last_active.isoformat(), session.turn_count,
            session.workspace_id, session.notebook_id, identity_json,
            json.dumps(session.media_uris), int(session.history_complete),
        )
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            previous = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session.session_id,)
            ).fetchone()
            if previous is not None:
                _check_replacement(previous, session, history)
            self._conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, url, mode, video_title, cache_name, model,
                    local_filepath, history, created_at, last_active, turn_count,
                    workspace_id, notebook_id, source_identity, media_uris, history_complete)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )

    def load_sync(self, session_id: str):
        """Return the complete archived session, or None if the ID is absent."""
        from .sessions import VideoSession

        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return VideoSession(
            session_id=row["session_id"], url=row["url"], mode=row["mode"],
            video_title=row["video_title"], cache_name=row["cache_name"], model=row["model"],
            local_filepath=row["local_filepath"],
            history=[_dict_to_content(content) for content in json.loads(row["history"])],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_active=datetime.fromisoformat(row["last_active"]), turn_count=row["turn_count"],
            workspace_id=row["workspace_id"], notebook_id=row["notebook_id"],
            source_identity=json.loads(row["source_identity"]),
            media_uris=json.loads(row["media_uris"]),
            history_complete=bool(row["history_complete"]),
        )

    def load_all_ids(self) -> list[str]:
        """Return all stored session IDs."""
        return [row[0] for row in self._conn.execute("SELECT session_id FROM sessions")]

    def delete(self, session_id: str) -> bool:
        """Delete a session and return whether a row was removed."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close the archive connection."""
        self._conn.close()


def _check_replacement(previous: sqlite3.Row, session, history: list[dict]) -> None:
    """Protect original turns, source identity and scope against stale writes."""
    original = json.loads(previous["history"])
    if history[:len(original)] != original:
        raise ValueError("Session history must preserve the complete archived prefix")
    if session.turn_count < previous["turn_count"]:
        raise ValueError("Session turn count cannot decrease")
    if (session.workspace_id, session.notebook_id) != (
        previous["workspace_id"], previous["notebook_id"]
    ):
        raise ValueError("Archived session scope is immutable")
    if session.source_identity != json.loads(previous["source_identity"]):
        raise ValueError("Archived source identity is immutable")
    if not previous["history_complete"] and session.history_complete:
        raise ValueError("Legacy incomplete history cannot be relabeled complete")


def _content_to_dict(content: types.Content) -> dict:
    """Serialize all SDK content fields, including opaque thought signatures."""
    return content.model_dump(mode="json", exclude_none=True)


def _dict_to_content(d: dict) -> types.Content:
    """Deserialize a dict back into a genai Content object."""
    return types.Content.model_validate(d)
