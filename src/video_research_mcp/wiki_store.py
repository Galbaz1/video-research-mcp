"""Immutable wiki revisions and source links inside the canonical corpus SQLite index."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib

from .corpus_index import MAX_INDEX_BYTES, canonical, connect, revision
from .media_snapshot import checked_path
from .models.corpus import Observation
from .models.wiki import LinkedEvidence, Page

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS wiki_concepts (concept TEXT PRIMARY KEY, kind TEXT NOT NULL, revision INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS wiki_revisions (concept TEXT REFERENCES wiki_concepts(concept), revision INTEGER, digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(concept,revision))",
    "CREATE TRIGGER IF NOT EXISTS wiki_history_no_update BEFORE UPDATE ON wiki_revisions BEGIN SELECT RAISE(ABORT,'Wiki history is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS wiki_history_no_delete BEFORE DELETE ON wiki_revisions BEGIN SELECT RAISE(ABORT,'Wiki history is immutable'); END",
    "CREATE VIRTUAL TABLE IF NOT EXISTS wiki_terms USING fts5(concept UNINDEXED,title,body,claims,tags)",
)


@contextmanager
def database(path: str, *, write: bool = False):
    """Reuse the canonical application ID, filesystem fence and SQLite transaction."""
    checked_path(path)
    with connect(path, mode="rw" if write else "ro") as db:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            if write:
                for statement in _SCHEMA:
                    db.execute(statement)
            yield db
            if write:
                size = db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]
                if size > MAX_INDEX_BYTES:
                    raise ValueError("Canonical index exceeds 64 MiB")
            db.commit()
        except Exception:
            db.rollback()
            raise


def initialized(db) -> bool:
    """An existing corpus may have no wiki pages yet."""
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='wiki_concepts'").fetchone())


def load(db, concept: str, version: int | None = None) -> dict | None:
    """Validate immutable payload integrity before returning any page revision."""
    if not initialized(db):
        return None
    row = db.execute("SELECT r.* FROM wiki_revisions r JOIN wiki_concepts c ON c.concept=r.concept WHERE r.concept=? AND r.revision=coalesce(?,c.revision)", (concept, version)).fetchone()
    if row is None:
        return None
    if hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]:
        raise ValueError("Wiki revision payload digest mismatch")
    value = Page.model_validate_json(row["payload"]).model_dump(mode="json")
    if (value["concept_id"], value["revision"]) != (row["concept"], row["revision"]):
        raise ValueError("Wiki revision identity mismatch")
    return {**value, "page_sha256": row["digest"]}


def _bind(db, link, linked_at: str) -> dict:
    """Bind caller attribution to exact canonical observation bytes and source intervals."""
    row = db.execute("SELECT * FROM observations WHERE collection=? AND observation=? AND revision=?", (link.collection, link.observation_id, link.source_revision)).fetchone()
    if row is None:
        raise ValueError("Evidence observation version is absent")
    obs = Observation.model_validate_json(row["payload"])
    if (row["video"], row["observation"], row["revision"], row["digest"]) != (obs.video_id, obs.observation_id, obs.source_revision, obs.media_digest):
        raise ValueError("Canonical observation metadata disagrees with payload")
    if (obs.video_id, obs.source_revision, obs.media_digest) != (link.video_id, link.source_revision, link.media_digest):
        raise ValueError("Evidence source identity or digest mismatch")
    for ref in obs.artifact_refs:
        checked_path(ref.path)
    value = {**link.model_dump(mode="json"), "source_id": obs.video_id + "@" + obs.source_revision,
             "start_seconds": obs.start_seconds, "end_seconds": obs.end_seconds, "linked_at": linked_at,
             "corpus_revision": revision(db, link.collection),
             "observation_sha256": hashlib.sha256(row["payload"].encode()).hexdigest(),
             "artifact_refs": [ref.model_dump(mode="json") for ref in obs.artifact_refs]}
    return LinkedEvidence.model_validate(value).model_dump(mode="json")


def save(db, value: dict) -> dict:
    """Atomically append history and replace only the current page's FTS projection."""
    page = Page.model_validate(value)
    if page.revision > 100:
        raise ValueError("Concept exceeds 100 retained revisions")
    payload = canonical(page.model_dump(mode="json"))
    if len(payload.encode()) > 131072:
        raise ValueError("Page revision exceeds 128 KiB")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db.execute("INSERT INTO wiki_concepts VALUES(?,?,?) ON CONFLICT(concept) DO UPDATE SET revision=excluded.revision", (page.concept_id, page.kind, page.revision))
    db.execute("INSERT INTO wiki_revisions VALUES(?,?,?,?)", (page.concept_id, page.revision, digest, payload))
    db.execute("DELETE FROM wiki_terms WHERE concept=?", (page.concept_id,))
    if not page.retired:
        db.execute("INSERT INTO wiki_terms VALUES(?,?,?,?,?)", (page.concept_id, page.title, page.body,
                   " ".join(item.claim for item in page.evidence), " ".join(page.tags)))
    return {**page.model_dump(mode="json"), "page_sha256": digest}


def write(request) -> dict:
    """Append contributions to the explicit identity; never infer entity equivalence."""
    with database(request.index_path, write=True) as db:
        old = load(db, request.concept_id)
        current = old["revision"] if old else 0
        if current != request.expected_revision:
            raise ValueError(f"Wiki revision conflict: current {current}, expected {request.expected_revision}")
        if old and old["kind"] != request.kind:
            raise ValueError("Canonical concept kind cannot change")
        if not old and db.execute("SELECT count(*) FROM wiki_concepts").fetchone()[0] >= 1000:
            raise ValueError("Wiki exceeds 1000 retained canonical identities")
        links = {item["evidence_id"]: item for item in old["evidence"]} if old else {}
        seen = set()
        stamp = datetime.now(timezone.utc).isoformat()
        for link in request.evidence:
            if link.evidence_id in seen:
                raise ValueError("Duplicate evidence_id in update")
            seen.add(link.evidence_id)
            prior = links.get(link.evidence_id)
            if prior:
                if any(prior[key] != value for key, value in link.model_dump(mode="json").items()):
                    raise ValueError("Immutable evidence contribution conflict; use a new evidence_id")
            else:
                links[link.evidence_id] = _bind(db, link, stamp)
        page = save(db, {"concept_id": request.concept_id, "kind": request.kind, "title": request.title,
                        "revision": current + 1, "body": request.body, "tags": sorted(set(request.tags)),
                        "evidence": sorted(links.values(), key=lambda item: item["evidence_id"]), "updated_at": stamp})
    return {"status": "written", "pages": [page]}


def remove_source(request) -> dict:
    """Version every affected current page atomically; retain prior history and corpus sources."""
    with database(request.index_path, write=True) as db:
        affected = []
        for row in db.execute("SELECT concept FROM wiki_concepts ORDER BY concept LIMIT 1001"):
            page = load(db, row[0])
            if any(link["video_id"] == request.video_id for link in page["evidence"]):
                affected.append(page)
        if len(affected) > 100:
            raise ValueError("Source removal exceeds 100 affected pages")
        if set(request.expected_revisions) != {p["concept_id"] for p in affected}:
            raise ValueError("Source removal requires exactly all affected concept revision pins")
        for page in affected:
            if request.expected_revisions[page["concept_id"]] != page["revision"]:
                raise ValueError("Wiki revision conflict during source removal")
        result = []
        for page in affected:
            page.pop("page_sha256")
            page["evidence"] = [link for link in page["evidence"] if link["video_id"] != request.video_id]
            page.update(revision=page["revision"] + 1, body="", retired=not page["evidence"], updated_at=datetime.now(timezone.utc).isoformat())
            result.append(save(db, page))
    return {"status": "removed", "pages": result, "modified_pages": len(result)}
