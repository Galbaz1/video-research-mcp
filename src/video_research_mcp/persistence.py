"""SQLite-backed session persistence with WAL mode."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from google.genai import types

logger = logging.getLogger(__name__)

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
    turn_count INTEGER NOT NULL DEFAULT 0
);
"""


class SessionDB:
    """Synchronous SQLite persistence for video sessions.

    Uses WAL mode for concurrent reads and fast writes (<1ms).
    All methods are synchronous -- designed for write-through from SessionStore.
    """

    def __init__(self, db_path: str) -> None:
        path = Path(db_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after the initial schema."""
        for col in ("cache_name", "model", "local_filepath"):
            try:
                self._conn.execute(
                    f"ALTER TABLE sessions ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass  # column already exists

    def save_sync(self, session) -> None:
        """Persist a VideoSession to SQLite.

        Args:
            session: VideoSession dataclass instance.
        """
        history_json = json.dumps([
            _content_to_dict(c) for c in session.history
        ])
        self._conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, url, mode, video_title, cache_name, model,
                local_filepath, history, created_at, last_active, turn_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.session_id,
                session.url,
                session.mode,
                session.video_title,
                session.cache_name,
                session.model,
                session.local_filepath,
                history_json,
                session.created_at.isoformat(),
                session.last_active.isoformat(),
                session.turn_count,
            ),
        )
        self._conn.commit()

    def load_sync(self, session_id: str):
        """Load a session from SQLite, returning a VideoSession or None.

        Args:
            session_id: The session ID to look up.

        Returns:
            VideoSession instance or None if not found.
        """
        from datetime import datetime

        from .sessions import VideoSession

        row = self._conn.execute(
            "SELECT session_id, url, mode, video_title, cache_name, model, "
            "local_filepath, history, created_at, last_active, turn_count "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None

        history_dicts = json.loads(row[7])
        history = [_dict_to_content(d) for d in history_dicts]

        return VideoSession(
            session_id=row[0],
            url=row[1],
            mode=row[2],
            video_title=row[3],
            cache_name=row[4],
            model=row[5],
            local_filepath=row[6],
            history=history,
            created_at=datetime.fromisoformat(row[8]),
            last_active=datetime.fromisoformat(row[9]),
            turn_count=row[10],
        )

    def load_all_ids(self) -> list[str]:
        """Return all stored session IDs."""
        rows = self._conn.execute(
            "SELECT session_id FROM sessions"
        ).fetchall()
        return [r[0] for r in rows]

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if a row was removed."""
        cursor = self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


def _content_to_dict(content: types.Content) -> dict:
    """Serialize all SDK content fields, including opaque thought signatures."""
    return content.model_dump(mode="json", exclude_none=True)


def _dict_to_content(d: dict) -> types.Content:
    """Deserialize a dict back into a genai Content object."""
    return types.Content.model_validate(d)
