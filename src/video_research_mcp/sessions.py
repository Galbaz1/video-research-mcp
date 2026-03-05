"""In-memory session store for multi-turn video exploration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.genai import types

from .config import get_config


@dataclass
class VideoSession:
    """Persistent conversation context for a single video."""

    session_id: str
    url: str
    mode: str
    video_title: str = ""
    cache_name: str = ""
    model: str = ""
    local_filepath: str = ""
    history: list[types.Content] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    turn_count: int = 0


class SessionStore:
    """Process-wide session registry with TTL eviction."""

    def __init__(self, db_path: str = "") -> None:
        """Initialize the store with optional SQLite persistence.

        Args:
            db_path: Path to SQLite DB file. Empty string = in-memory only.
        """
        self._sessions: dict[str, VideoSession] = {}
        self._db: SessionDB | None = None
        if db_path:
            from .persistence import SessionDB  # lazy — saves ~500ms at startup
            self._db = SessionDB(db_path)

    def create(
        self,
        url: str,
        mode: str,
        video_title: str = "",
        cache_name: str = "",
        model: str = "",
        local_filepath: str = "",
    ) -> VideoSession:
        """Create a new session, evicting expired ones first."""
        self._evict_expired()
        cfg = get_config()
        if len(self._sessions) >= cfg.max_sessions:
            oldest_id = min(self._sessions, key=lambda k: self._sessions[k].last_active)
            del self._sessions[oldest_id]

        sid = uuid.uuid4().hex[:12]
        session = VideoSession(
            session_id=sid,
            url=url,
            mode=mode,
            video_title=video_title,
            cache_name=cache_name,
            model=model,
            local_filepath=local_filepath,
        )
        self._sessions[sid] = session
        if self._db:
            self._db.save_sync(session)
        return session

    def get(self, session_id: str) -> VideoSession | None:
        """Look up a session by ID, falling back to SQLite if configured."""
        self._evict_expired()
        session = self._sessions.get(session_id)
        if session is None and self._db:
            session = self._db.load_sync(session_id)
            if session is not None:
                self._sessions[session_id] = session
        return session

    def add_turn(
        self,
        session_id: str,
        user_content: types.Content,
        model_content: types.Content,
    ) -> int:
        """Append a user+model turn pair. Returns new turn count."""
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        session.history.append(user_content)
        session.history.append(model_content)
        session.turn_count += 1
        # Bound replay context to avoid unbounded growth and token-limit failures.
        max_history_items = max(get_config().session_max_turns, 1) * 2
        if len(session.history) > max_history_items:
            session.history = session.history[-max_history_items:]
        session.last_active = datetime.now()
        if self._db:
            self._db.save_sync(session)
        return session.turn_count

    def _evict_expired(self) -> int:
        """Remove sessions that have exceeded the configured timeout. Returns count evicted."""
        timeout = timedelta(hours=get_config().session_timeout_hours)
        now = datetime.now()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_active > timeout]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    @property
    def count(self) -> int:
        """Number of active in-memory sessions."""
        return len(self._sessions)


def _make_default_store() -> SessionStore:
    """Build the module-level singleton, reading config if available."""
    try:
        cfg = get_config()
        return SessionStore(db_path=cfg.session_db_path)
    except Exception:
        return SessionStore()


# Module-level singleton
session_store = _make_default_store()
