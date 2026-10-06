"""Bounded immutable wiki-history references for canonical collection cleanup."""

import hashlib
import sqlite3

from .corpus_index import MAX_INDEX_BYTES
from .media_snapshot import checked_path
from .models.wiki import Page

MAX_WIKI_REVISIONS = 1000 * 100
MAX_WIKI_PAYLOAD_BYTES = 128 * 1024


def _complete_history(db) -> None:
    """Refuse missing, gapped or orphan revisions before reclaiming linked files."""
    if db.execute("SELECT count(*) FROM wiki_concepts").fetchone()[0] > 1000:
        raise ValueError("Wiki history is incomplete or exceeds 1000 concept heads")
    incomplete = db.execute("""SELECT c.concept FROM wiki_concepts c
        LEFT JOIN wiki_revisions r ON r.concept=c.concept GROUP BY c.concept
        HAVING c.revision NOT BETWEEN 1 AND 100 OR count(r.revision)!=c.revision
            OR min(r.revision)!=1 OR max(r.revision)!=c.revision LIMIT 1""").fetchone()
    orphan = db.execute("""SELECT 1 FROM wiki_revisions r
        LEFT JOIN wiki_concepts c ON c.concept=r.concept WHERE c.concept IS NULL LIMIT 1""").fetchone()
    if incomplete or orphan:
        raise ValueError("Wiki history schema or retained revisions are incomplete; revisions must match every concept head")


def referenced_by_wiki(db, asset) -> bool:
    """Protect exact linked paths/hashes in every retained revision; refuse unsafe history.

    Args:
        db: Existing canonical SQLite connection, inside the cleanup transaction.
        asset: Existing collection asset row with its recorded path and digest.

    Returns:
        Whether retained wiki history links the exact artifact, including retired pages.

    Raises:
        ValueError: History is incomplete, malformed, altered or exceeds existing limits.
        PermissionError: A retained artifact path violates the configured local fence.
    """
    try:
        schema = dict(db.execute("SELECT name,type FROM sqlite_master WHERE name IN ('wiki_concepts','wiki_revisions')"))
        if not schema:
            return False
        if schema != {"wiki_concepts": "table", "wiki_revisions": "table"}:
            raise ValueError("Wiki history schema is incomplete or altered")
        if db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0] > MAX_INDEX_BYTES:
            raise ValueError("Canonical index exceeds 64 MiB; wiki retention scan refused")
        _complete_history(db)
        path, found = str(checked_path(asset["path"])), False
        rows = db.execute("""SELECT concept,revision,digest,length(CAST(payload AS BLOB)) AS payload_bytes,
            CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END AS payload
            FROM wiki_revisions ORDER BY concept,revision LIMIT ?""",
            (MAX_WIKI_PAYLOAD_BYTES, MAX_WIKI_REVISIONS + 1))
        for count, row in enumerate(rows, 1):
            if count > MAX_WIKI_REVISIONS:
                raise ValueError("Wiki history exceeds 1000 concepts x 100 retained revisions")
            payload = row["payload"]
            if not isinstance(payload, str) or row["payload_bytes"] > MAX_WIKI_PAYLOAD_BYTES:
                raise ValueError("Wiki revision exceeds 128 KiB or has an invalid payload type")
            if hashlib.sha256(payload.encode()).hexdigest() != row["digest"]:
                raise ValueError("Wiki revision payload digest mismatch")
            page = Page.model_validate_json(payload)
            if (page.concept_id, page.revision) != (row["concept"], row["revision"]) or page.revision > 100:
                raise ValueError("Wiki revision identity mismatch or revision limit exceeded")
            for link in page.evidence:
                for ref in link.artifact_refs:
                    if str(checked_path(ref.path)) == path:
                        if ref.sha256 != asset["digest"]:
                            raise ValueError("Wiki artifact path has a conflicting digest")
                        found = True
        return found
    except sqlite3.DatabaseError as error:
        raise ValueError("Wiki history schema cannot be safely scanned") from error
