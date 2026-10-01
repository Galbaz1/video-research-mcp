"""Source-scoped learned memory with SQLite revision checks and deletion tombstones."""

from __future__ import annotations

import sqlite3
from pathlib import Path

MAX_SYNOPSIS_BYTES = 32 * 1024

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_memory (
    workspace_id TEXT NOT NULL,
    notebook_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    synopsis TEXT,
    source_revision TEXT,
    history_sha256 TEXT,
    origin_session_id TEXT,
    revision INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (workspace_id, notebook_id, source_id)
);
"""


class SourceMemoryDB:
    """Editable, non-authoritative memory isolated by workspace, notebook and source."""

    def __init__(self, db_path: str) -> None:
        """Open a separate learned-memory table without altering session archives."""
        path = Path(db_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def get(self, scope: tuple[str, str, str]) -> dict | None:
        """Return active memory for the exact required scope, or None."""
        _check_scope(scope)
        row = self._conn.execute(
            """SELECT * FROM source_memory
               WHERE workspace_id = ? AND notebook_id = ? AND source_id = ? AND deleted = 0""",
            scope,
        ).fetchone()
        return _record(row) if row is not None else None

    def put(
        self, scope: tuple[str, str, str], synopsis: str, source_revision: str,
        history_sha256: str, expected_revision: int, *, origin_session_id: str,
    ) -> dict:
        """Create or replace scoped memory only at its current revision."""
        _check_scope(scope)
        _check_revision(expected_revision)
        if not isinstance(origin_session_id, str) or not origin_session_id.strip():
            raise ValueError("Origin session ID is required for raw-history recovery")
        if len(synopsis.encode("utf-8")) > MAX_SYNOPSIS_BYTES:
            raise ValueError("Learned-memory synopsis exceeds the 32 KiB limit")
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                """SELECT revision, deleted FROM source_memory
                   WHERE workspace_id = ? AND notebook_id = ? AND source_id = ?""",
                scope,
            ).fetchone()
            current_revision = 0 if row is None or row["deleted"] else row["revision"]
            if expected_revision != current_revision:
                raise ValueError("Learned-memory revision conflict")
            revision = 1 if row is None else row["revision"] + 1
            self._conn.execute(
                """INSERT OR REPLACE INTO source_memory
                   (workspace_id, notebook_id, source_id, synopsis,
                    source_revision, history_sha256, origin_session_id, revision, deleted)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (*scope, synopsis, source_revision, history_sha256, origin_session_id, revision),
            )
            result = self._conn.execute(
                """SELECT * FROM source_memory
                   WHERE workspace_id = ? AND notebook_id = ? AND source_id = ?""",
                scope,
            ).fetchone()
        return _record(result)

    def delete(self, scope: tuple[str, str, str], expected_revision: int) -> bool:
        """Clear current memory while retaining a revision-only tombstone."""
        _check_scope(scope)
        _check_revision(expected_revision)
        with self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                """SELECT revision, deleted FROM source_memory
                   WHERE workspace_id = ? AND notebook_id = ? AND source_id = ?""",
                scope,
            ).fetchone()
            current_revision = 0 if row is None or row["deleted"] else row["revision"]
            if expected_revision != current_revision:
                raise ValueError("Learned-memory revision conflict")
            if current_revision == 0:
                return False
            self._conn.execute(
                """UPDATE source_memory
                   SET synopsis = NULL, source_revision = NULL, history_sha256 = NULL,
                       origin_session_id = NULL, revision = revision + 1, deleted = 1
                   WHERE workspace_id = ? AND notebook_id = ? AND source_id = ?""",
                scope,
            )
        return True

    def close(self) -> None:
        """Close the learned-memory connection."""
        self._conn.close()


def _check_scope(scope: tuple[str, str, str]) -> None:
    """Reject missing profiles rather than falling back to shared memory."""
    if not isinstance(scope, tuple) or len(scope) != 3:
        raise ValueError("Workspace, notebook and source scope are all required")
    if any(not isinstance(value, str) or not value.strip() for value in scope):
        raise ValueError("Workspace, notebook and source scope must be nonempty strings")


def _check_revision(revision: int) -> None:
    """Require an exact nonnegative revision token; zero means absent."""
    if type(revision) is not int or revision < 0:
        raise ValueError("Expected revision must be a nonnegative integer")


def _record(row: sqlite3.Row) -> dict:
    """Return mutable memory without granting source-evidence authority."""
    return {
        name: row[name] for name in (
            "workspace_id", "notebook_id", "source_id", "synopsis", "source_revision",
            "history_sha256", "origin_session_id", "revision",
        )
    } | {"authoritative": False, "source_verified": False}
