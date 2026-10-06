"""Immutable audience sample metadata in the existing canonical corpus SQLite database."""

import hashlib

from .collections_store import advance, collection, expect, transaction
from .corpus_index import MAX_INDEX_BYTES, canonical, connect, revision
from .models.audience import Sample

MAX_SAMPLE_BYTES = 512 * 1024
MAX_SAMPLES = 100
MAX_COMMENTS = 5000
_SCHEMA = """CREATE TABLE IF NOT EXISTS audience_samples (
 collection TEXT NOT NULL REFERENCES collections(name), sample TEXT NOT NULL,
 digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(collection,sample))"""


def identity(payload: str) -> str:
    """Digest exact canonical stored source strings and sampling metadata."""
    return hashlib.sha256(payload.encode()).hexdigest()


def rows(db, name: str) -> list:
    """Bound retained payload reads before loading and validate every immutable identity."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audience_samples'").fetchone():
        return []
    bounds = db.execute("SELECT sample,length(CAST(payload AS BLOB)) FROM audience_samples WHERE collection=? LIMIT 101", (name,)).fetchall()
    if len(bounds) > MAX_SAMPLES or any(r[1] > MAX_SAMPLE_BYTES for r in bounds) or sum(r[1] for r in bounds) > MAX_INDEX_BYTES:
        raise ValueError("Retained audience sample bounds exceeded")
    result = []
    for row in db.execute("SELECT sample,digest,payload FROM audience_samples WHERE collection=? ORDER BY sample", (name,)):
        if identity(row["payload"]) != row["digest"]:
            raise ValueError("Retained audience sample digest mismatch")
        sample = Sample.model_validate_json(row["payload"])
        if sample.sample_id != row["sample"] or canonical(sample.model_dump(mode="json")) != row["payload"]:
            raise ValueError("Retained audience sample identity mismatch")
        result.append((sample, row["digest"]))
    if sum(s.sample_size for s, _ in result) > MAX_COMMENTS:
        raise ValueError("Retained audience comments exceed 5000")
    return result


def import_sample(request) -> dict:
    """Atomically import a supplied sample; never rewrite an existing sample identity."""
    payload = canonical(request.sample.model_dump(mode="json"))
    if len(payload.encode()) > MAX_SAMPLE_BYTES:
        raise ValueError("Audience sample exceeds 512 KiB before admission")
    digest = identity(payload)
    with transaction(request.index_path) as db:
        catalog = expect(db, request)
        if catalog["kind"] not in ("comments", "mixed"):
            raise ValueError("Audience import requires a comments or mixed collection")
        db.execute(_SCHEMA)
        prior = rows(db, request.collection)
        old = next((d for s, d in prior if s.sample_id == request.sample.sample_id), None)
        if old is not None and old != digest:
            raise ValueError("Immutable sample conflict; use a new sample_id")
        if old is None:
            if len(prior) >= MAX_SAMPLES or sum(s.sample_size for s, _ in prior) + request.sample.sample_size > MAX_COMMENTS:
                raise ValueError("Audience retained sample/comment bound rejects admission")
            db.execute("INSERT INTO audience_samples VALUES(?,?,?,?)", (request.collection, request.sample.sample_id, digest, payload))
            value = advance(db, request.collection)
        else:
            value = revision(db, request.collection)
    return {"status": "unchanged" if old else "imported", "workspace": request.workspace,
            "collection": request.collection, "index_revision": value, "sample_id": request.sample.sample_id,
            "sample_sha256": digest, "sampling": sampling(request.sample)}


def sampling(sample) -> dict:
    """Expose the exact observed denominator separately from a supplied population size."""
    return {"sample_size": sample.sample_size, "population_size": sample.population_size,
            "sampling_method": sample.sampling_method, "source": sample.source,
            "source_url": sample.source_url, "source_revision": sample.source_revision,
            "retrieved_at": sample.retrieved_at, "platform_completeness": "not_verified"}


def load(request, sample_ids) -> tuple:
    """Read a fixed sample selection with the current collection revision in one snapshot."""
    with connect(request.index_path) as db:
        db.execute("BEGIN")
        collection(db, request, request.collection)
        available = {s.sample_id: (s, d) for s, d in rows(db, request.collection)}
        if len(set(sample_ids)) != len(sample_ids) or any(key not in available for key in sample_ids):
            raise ValueError("Requested sample identities must be unique and present")
        return revision(db, request.collection), [available[key] for key in sorted(sample_ids)]
