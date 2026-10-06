"""Immutable correction lessons and fixed-rule history in the canonical corpus DB."""

from datetime import datetime, timezone
import hashlib

from .cache import invalidate_source
from .collections_store import advance, collection, expect, transaction
from .corpus_index import canonical, connect, observation, revision
from .models.corrections import CacheReceipt, CaseRecord, ReplayRecord, Response

MAX_CASES = 100
MAX_REPLAYS = 1000
MAX_PAYLOAD_BYTES = 256 * 1024
_STATES = ("pass", "fail", "error", "provider_error", "abstained")
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS correction_cases (
        collection TEXT NOT NULL REFERENCES collections(name), case_id TEXT NOT NULL,
        digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(collection,case_id))""",
    """CREATE TABLE IF NOT EXISTS correction_replays (
        collection TEXT NOT NULL, case_id TEXT NOT NULL, replay_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL, status TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY(collection,case_id,replay_id), UNIQUE(collection,case_id,ordinal),
        FOREIGN KEY(collection,case_id) REFERENCES correction_cases(collection,case_id))""",
)


def _encoded(value):
    """Bound canonical immutable payload bytes before SQLite admission."""
    payload = canonical(value.model_dump(mode="json"))
    if len(payload.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("Correction payload exceeds 256 KiB")
    return payload, hashlib.sha256(payload.encode()).hexdigest()


def _decode(row, model):
    """Check retained digest, typed content and indexed identity before returning it."""
    raw = row["payload"]
    if len(raw.encode()) > MAX_PAYLOAD_BYTES or hashlib.sha256(raw.encode()).hexdigest() != row["digest"]:
        raise ValueError("Retained correction payload bound/digest mismatch")
    value = model.model_validate_json(raw)
    if canonical(value.model_dump(mode="json")) != raw:
        raise ValueError("Retained correction canonical identity mismatch")
    case_id = value.lesson.case_id if model is CaseRecord else value.case_id
    if case_id != row["case_id"]:
        raise ValueError("Retained correction case identity mismatch")
    if model is ReplayRecord and (value.replay_id, value.ordinal, value.status) != (row["replay_id"], row["ordinal"], row["status"]):
        raise ValueError("Retained replay identity mismatch")
    return value


def _exists(db):
    """Detect absent correction schema without modifying a read-only database."""
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='correction_cases'").fetchone())


def _one(db, table, name, case_id, replay_id=None):
    """Check a retained row's byte length before acquiring its payload."""
    clause, args = "WHERE collection=? AND case_id=?", [name, case_id]
    if replay_id is not None:
        clause += " AND replay_id=?"
        args.append(replay_id)
    size = db.execute(f"SELECT length(CAST(payload AS BLOB)) FROM {table} " + clause, args).fetchone()
    if size and (size[0] is None or size[0] > MAX_PAYLOAD_BYTES):
        raise ValueError("Retained correction payload exceeds byte bound")
    return db.execute(f"SELECT * FROM {table} " + clause, args).fetchone() if size else None


def _case(db, name, case_id):
    """Read exactly one retained lesson with its original immutable digest."""
    row = _one(db, "correction_cases", name, case_id) if _exists(db) else None
    if row is None:
        raise ValueError("Correction case is absent")
    return _decode(row, CaseRecord), row["digest"]


def _resolve(db, name, refs):
    """Join explicitly named current or historical observations without media reads."""
    resolved = []
    for ref in refs:
        row = db.execute("SELECT * FROM observations WHERE collection=? AND observation=? AND revision=?", (name, ref.observation_id, ref.source_revision)).fetchone()
        if row is None or (row["video"], row["digest"]) != (ref.video_id, ref.media_digest):
            raise ValueError("Correction evidence is absent or its source identity differs")
        value = observation(row)
        if any(value[key] != getattr(ref, key) for key in ("video_id", "observation_id", "source_revision", "media_digest")):
            raise ValueError("Correction observation payload differs from its indexed identity")
        source_id = value.pop("source_id")
        resolved.append({"reference": ref.model_dump(mode="json"), "observation": value, "source_id": source_id})
    return resolved


def _denominator(db, name, case_id=None):
    """Count every durably admitted outcome, including provider errors and abstention."""
    counts = dict.fromkeys(_STATES, 0)
    if _exists(db):
        sql, args = "SELECT status,count(*) FROM correction_replays WHERE collection=?", [name]
        if case_id is not None:
            sql += " AND case_id=?"
            args.append(case_id)
        for status, count in db.execute(sql + " GROUP BY status", args):
            if status not in counts:
                raise ValueError("Retained replay status is invalid")
            counts[status] = count
    return {**counts, "total": sum(counts.values())}


def _record(db, request):
    """Keep exact reported authority and original/corrected evidence snapshots."""
    row = _one(db, "correction_cases", request.collection, request.lesson.case_id)
    if row:
        value = _decode(row, CaseRecord)
        if value.lesson != request.lesson:
            raise ValueError("Immutable correction case conflict; use a new case_id")
        return {"status": "unchanged", "cases": [value]}
    if db.execute("SELECT count(*) FROM correction_cases WHERE collection=?", (request.collection,)).fetchone()[0] >= MAX_CASES:
        raise ValueError("Collection exceeds 100 retained correction cases")
    value = CaseRecord(lesson=request.lesson, recorded_at=datetime.now(timezone.utc),
                       cache_invalidation=CacheReceipt(state="pending"),
                       original_evidence=_resolve(db, request.collection, request.lesson.original.evidence_refs),
                       corrected_evidence=_resolve(db, request.collection, request.lesson.corrected_evidence_refs))
    payload, digest = _encoded(value)
    db.execute("INSERT INTO correction_cases VALUES(?,?,?,?)", (request.collection, request.lesson.case_id, digest, payload))
    return {"status": "recorded", "cases": [value]}


def _evaluate(db, request, lesson):
    """Apply only the declared exact-text/reference rule; unsuccessful states stay distinct."""
    if request.outcome.status != "answer":
        return request.outcome.status, "reported_unsuccessful_outcome", [], None
    try:
        evidence = _resolve(db, request.collection, request.outcome.evidence_refs)
    except (ValueError, PermissionError) as error:
        return "error", "evidence_resolution_failed", [], str(error)
    actual = {canonical(ref.model_dump(mode="json")) for ref in request.outcome.evidence_refs}
    required = {canonical(ref.model_dump(mode="json")) for ref in lesson.corrected_evidence_refs}
    passed = request.outcome.answer == lesson.corrected_answer and required <= actual
    return "pass" if passed else "fail", "exact_answer_and_corrected_refs_v1", evidence, None


def _replay(db, request):
    """Append immutable post-change evidence and evaluated history, never rewrite the lesson."""
    case, digest = _case(db, request.collection, request.case_id)
    row = _one(db, "correction_replays", request.collection, request.case_id, request.replay_id)
    if row:
        value = _decode(row, ReplayRecord)
        if value.outcome != request.outcome or value.change_revision != request.change_revision:
            raise ValueError("Immutable replay conflict; use a new replay_id")
        return {"status": "unchanged", "replays": [value]}
    if _denominator(db, request.collection)["total"] >= MAX_REPLAYS:
        raise ValueError("Collection exceeds 1000 retained replay attempts")
    ordinal = db.execute("SELECT count(*) FROM correction_replays WHERE collection=? AND case_id=?", (request.collection, request.case_id)).fetchone()[0] + 1
    status, reason, evidence, error = _evaluate(db, request, case.lesson)
    value = ReplayRecord(case_id=request.case_id, replay_id=request.replay_id, ordinal=ordinal,
                         change_revision=request.change_revision, evaluated_at=datetime.now(timezone.utc),
                         outcome=request.outcome, lesson_sha256=digest, status=status, reason=reason,
                         evidence=evidence, evaluator_error=error)
    payload, sha = _encoded(value)
    db.execute("INSERT INTO correction_replays VALUES(?,?,?,?,?,?,?)", (request.collection, request.case_id, request.replay_id, ordinal, status, sha, payload))
    return {"status": "replayed", "replays": [value]}


def _bounded(request, value):
    """Validate typed output and refuse an oversized response before committing writes."""
    result = Response.model_validate(value).model_dump(mode="json")
    if len(canonical(result).encode()) > request.output_bytes:
        raise ValueError("Correction response exceeds output_bytes; transaction not admitted")
    return result


def _read(db, request):
    """Read revision, fixed evidence and paginated history in the same SQLite snapshot."""
    result = {"status": "listed" if request.action == "list" else "exported", "cases": [], "replays": []}
    if not _exists(db):
        if request.action == "export":
            raise ValueError("Correction case is absent")
        return result
    if request.action == "list":
        table, model, target = "correction_cases", CaseRecord, "cases"
        clause, args = "WHERE collection=? ORDER BY case_id", [request.collection]
    else:
        case, _ = _case(db, request.collection, request.case_id)
        result["cases"] = [case]
        table, model, target = "correction_replays", ReplayRecord, "replays"
        clause, args = "WHERE collection=? AND case_id=? ORDER BY ordinal", [request.collection, request.case_id]
    suffix = clause + " LIMIT ? OFFSET ?"
    sizes = db.execute(f"SELECT length(CAST(payload AS BLOB)) FROM {table} " + suffix, [*args, request.limit + 1, request.offset]).fetchall()
    if any(row[0] > MAX_PAYLOAD_BYTES for row in sizes) or sum(row[0] for row in sizes[:request.limit]) > request.output_bytes:
        raise ValueError("Correction page exceeds payload/output_bytes bounds")
    rows = db.execute(f"SELECT * FROM {table} " + suffix, [*args, request.limit, request.offset]).fetchall()
    result[target] = [_decode(row, model) for row in rows]
    result["next_offset"] = request.offset + request.limit if len(sizes) > request.limit else None
    return result


def execute(request) -> dict:
    """Record/replay/list/export solely within the explicit existing workspace collection."""
    if request.action in {"record", "replay"}:
        with transaction(request.index_path) as db:
            expect(db, request)
            for statement in _SCHEMA:
                db.execute(statement)
            result = _record(db, request) if request.action == "record" else _replay(db, request)
            current = revision(db, request.collection) if result["status"] == "unchanged" else advance(db, request.collection)
            result.update(workspace=request.workspace, collection=request.collection, index_revision=current,
                          denominator=_denominator(db, request.collection, getattr(request, "case_id", None)))
            result = _bounded(request, result)
            if request.action == "record":
                # Reserve bounded failure receipts before admitting any independent cache effect.
                refs = [*request.lesson.original.evidence_refs, *request.lesson.corrected_evidence_refs]
                sources = sorted({ref.media_digest for ref in refs})
                _bounded(request, {**result, "cache_errors": ["x" * 1024] * len(sources),
                                   "cache_sources": sources, "context_invalidated_entries": 6400,
                                   "cache_invalidation": CacheReceipt(state="complete", invalidated_entries=32768)})
        return _invalidate(request, result) if request.action == "record" else result
    with connect(request.index_path) as db:
        db.execute("BEGIN")
        collection(db, request, request.collection)
        result = _read(db, request)
        result.update(workspace=request.workspace, collection=request.collection,
                      index_revision=revision(db, request.collection), denominator=_denominator(db, request.collection, request.case_id))
        return _bounded(request, result)


def _invalidate(request, result):
    """After lesson commit, reconcile exact source dependencies on every idempotent record call."""
    lesson = request.lesson
    digests = sorted({ref.media_digest for ref in [*lesson.original.evidence_refs, *lesson.corrected_evidence_refs]})
    receipts = [invalidate_source(digest, strict=True) for digest in digests]
    removed = sum(receipt["invalidated_entries"] for receipt in receipts)
    contexts = sum(receipt["context_entries"] for receipt in receipts)
    errors = [receipt["error"] for receipt in receipts if receipt["error"]]
    state = ("partial" if removed or contexts else "failed") if errors else ("complete" if removed or contexts else "absent")
    return _bounded(request, {**result, "cache_sources": digests, "cache_errors": errors,
                             "context_invalidated_entries": contexts,
                             "cache_invalidation": CacheReceipt(state=state, invalidated_entries=removed)})
