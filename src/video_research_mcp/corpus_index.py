"""Collection-scoped SQLite FTS5 observation index; no media or model execution."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3

from .local_path_policy import enforce_local_access_root, resolve_path
from .models.corpus import Observation

APPLICATION_ID = 0x56524331
MAX_OBSERVATIONS = 5000
MAX_INDEX_BYTES = 64 * 1024 * 1024
_SCHEMA = """
CREATE TABLE collections(name TEXT PRIMARY KEY, revision INTEGER NOT NULL);
CREATE TABLE sources(collection TEXT, video TEXT, revision TEXT, digest TEXT,
 PRIMARY KEY(collection,video));
CREATE TABLE observations(id INTEGER PRIMARY KEY, collection TEXT, observation TEXT,
 video TEXT, revision TEXT, digest TEXT, payload TEXT,
 UNIQUE(collection,observation,revision));
CREATE VIRTUAL TABLE terms USING fts5(id UNINDEXED,text);
CREATE TABLE vectors(id INTEGER PRIMARY KEY REFERENCES observations(id),model TEXT,values_json TEXT);
"""


def canonical(value) -> str:
    """Stable finite JSON for payload identity and the named context token estimate."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def local_path(value: str) -> Path:
    """Apply the existing local root policy and reject URI and symlink database targets."""
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise PermissionError("Index database may not be a symlink")
    path = enforce_local_access_root(resolve_path(value))
    if path.suffix != ".sqlite3":
        raise ValueError("index_path must end in .sqlite3")
    for suffix in ("-journal", "-wal", "-shm"):
        if Path(str(path) + suffix).is_symlink():
            raise PermissionError("Index sidecar may not be a symlink")
    if path.exists() and (not path.is_file() or path.stat().st_size > MAX_INDEX_BYTES):
        raise ValueError("Index must be a regular database of at most 64 MiB")
    return path


@contextmanager
def connect(value: str, *, mode: str = "ro"):
    """Create only an absent index; reject foreign databases before any schema mutation."""
    path = local_path(value)
    fresh = False
    if mode == "rwc" and not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        fresh = True
    mode = "rw" if mode == "rwc" else mode
    db = sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA trusted_schema=OFF")
        if fresh:
            db.executescript(_SCHEMA)
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        elif db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise ValueError("Foreign database refused; corpus application_id does not match")
        db.execute("PRAGMA foreign_keys=ON")
        yield db
    finally:
        db.close()


def revision(db, collection: str) -> int:
    """Current optimistic collection revision, zero for an absent collection."""
    row = db.execute("SELECT revision FROM collections WHERE name=?", (collection,)).fetchone()
    return row[0] if row else 0


def current_rows(db, request) -> list:
    """Filter both recorded current source identity and caller-pinned source revisions."""
    rows = db.execute("""SELECT o.*,v.model,v.values_json FROM observations o
        JOIN sources s ON s.collection=o.collection AND s.video=o.video
         AND s.revision=o.revision AND s.digest=o.digest
        LEFT JOIN vectors v ON v.id=o.id WHERE o.collection=?
        ORDER BY o.video,o.observation,o.revision""", (request.collection,)).fetchall()
    return [row for row in rows if request.source_revisions.get(row["video"]) == row["revision"]]


def _vectors(db, collection, patches) -> None:
    """Validate the whole repair before replacing any vector in the same transaction."""
    admitted, seen = [], set()
    for patch in patches:
        if patch.observation_id in seen:
            raise ValueError("Duplicate vector observation_id")
        seen.add(patch.observation_id)
        row = db.execute("""SELECT o.id,o.digest FROM observations o JOIN sources s
            ON s.collection=o.collection AND s.video=o.video AND s.revision=o.revision
            AND s.digest=o.digest WHERE o.collection=? AND o.observation=? AND o.revision=?""",
            (collection, patch.observation_id, patch.source_revision)).fetchone()
        if row is None or row["digest"] != patch.media_digest:
            raise ValueError("Vector observation is absent, stale or has a different media digest")
        admitted.append((row["id"], patch.model, canonical(patch.values)))
    db.executemany("INSERT OR REPLACE INTO vectors VALUES(?,?,?)", admitted)


def _observations(db, request) -> None:
    """Store immutable observation versions and move each supplied video to one revision."""
    sources, seen = {}, set()
    for obs in request.observations:
        identity = (obs.source_revision, obs.media_digest)
        if obs.video_id in sources and sources[obs.video_id] != identity:
            raise ValueError("Conflicting source identities in the same batch")
        sources[obs.video_id] = identity
    _advance_sources(db, request.collection, sources)
    for obs in request.observations:
        if obs.observation_id in seen:
            raise ValueError("Duplicate observation_id")
        seen.add(obs.observation_id)
        identity = (obs.source_revision, obs.media_digest)
        for ref in obs.artifact_refs:
            enforce_local_access_root(resolve_path(ref.path))
        prior = db.execute("SELECT video FROM observations WHERE collection=? AND observation=? LIMIT 1",
                           (request.collection, obs.observation_id)).fetchone()
        if prior and prior[0] != obs.video_id:
            raise ValueError("Observation identity belongs to a different video")
        payload = canonical(obs.model_dump(mode="json"))
        old = db.execute("SELECT id,payload FROM observations WHERE collection=? AND observation=? AND revision=?",
                         (request.collection, obs.observation_id, obs.source_revision)).fetchone()
        if old and old["payload"] != payload:
            raise ValueError("Immutable observation conflict; use a new source revision")
        if not old:
            row = db.execute("INSERT INTO observations(collection,observation,video,revision,digest,payload) VALUES(?,?,?,?,?,?)",
                             (request.collection, obs.observation_id, obs.video_id, *identity, payload))
            db.execute("INSERT INTO terms(id,text) VALUES(?,?)", (row.lastrowid, obs.text))
    count = db.execute("SELECT count(*) FROM observations WHERE collection=?", (request.collection,)).fetchone()[0]
    if count > MAX_OBSERVATIONS:
        raise ValueError("Collection exceeds 5000 retained observation versions")



def _advance_sources(db, collection, sources) -> None:
    """Reject reused historical revisions and same-revision media conflicts."""
    for video, identity in sources.items():
        old = db.execute("SELECT revision,digest FROM sources WHERE collection=? AND video=?",
                         (collection, video)).fetchone()
        if old and old[0] == identity[0] and old[1] != identity[1]:
            raise ValueError("Same source revision cannot name different media bytes")
        historical = db.execute("SELECT 1 FROM observations WHERE collection=? AND video=? AND revision=?",
                                (collection, video, identity[0])).fetchone()
        if old and old[0] != identity[0] and historical:
            raise ValueError("Stale source revision cannot be made current again")
        db.execute("INSERT OR REPLACE INTO sources VALUES(?,?,?,?)", (collection, video, *identity))

def mutate(request) -> dict:
    """Atomic supplied-observation indexing or vector-only repair with revision conflict checks."""
    with connect(request.index_path, mode="rwc" if request.action == "index" else "rw") as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            current = revision(db, request.collection)
            if current != request.expected_revision:
                raise ValueError(f"Index revision conflict: current {current}, expected {request.expected_revision}")
            if request.action == "index":
                _observations(db, request)
            _vectors(db, request.collection, request.vectors)
            db.execute("INSERT OR REPLACE INTO collections VALUES(?,?)", (request.collection, current + 1))
            if db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0] > MAX_INDEX_BYTES:
                raise ValueError("Index exceeds 64 MiB; transaction rolled back")
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"status": "indexed" if request.action == "index" else "repaired",
            "collection": request.collection, "index_revision": current + 1,
            "retrieval": {"vectors_updated": len(request.vectors), "media_reads": 0, "provider_calls": 0}}


def observation(row) -> dict:
    """Validate stored metadata and reapply the current access boundary to artifact paths."""
    value = Observation.model_validate_json(row["payload"]).model_dump(mode="json")
    identity = (value["observation_id"], value["source_revision"], value["video_id"], value["media_digest"])
    if identity != (row["observation"], row["revision"], row["video"], row["digest"]):
        raise ValueError("Stored observation identity differs from the admitted row")
    for ref in value["artifact_refs"]:
        enforce_local_access_root(resolve_path(ref["path"]))
    value["source_id"] = value["video_id"] + "@" + value["source_revision"]
    return value
