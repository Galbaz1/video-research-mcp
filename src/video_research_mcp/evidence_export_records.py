"""Normalize existing corpus/wiki/collection records without creating another store."""

import hashlib

from .corpus_index import canonical
from .models.evidence_export import Record


def observation(value, origin, **extra) -> Record:
    """Preserve source identity and supplied text without inventing method or truth."""
    names = ("video_id", "source_revision", "media_digest", "observation_id", "start_seconds", "end_seconds", "kind", "text", "artifact_refs")
    fields = {key: value[key] for key in names}
    citation = hashlib.sha256(canonical([value["source_id"], value["observation_id"], value["media_digest"]]).encode()).hexdigest()
    return Record(**fields, citation_id=citation, origin=origin, **extra)


async def select(source) -> tuple[list[Record], dict]:
    """Call the actual bounded canonical routes; fixture origin is always explicit."""
    if source.kind == "fixture":
        return [r.model_copy(update={"origin": "caller_fixture"}) for r in source.records], {"route": "caller_fixture", "canonical_retrieval": False}
    if source.kind == "corpus":
        from .corpus_retrieval import query

        result = await query(source.request)
        records = [observation(row, "canonical_corpus") for row in result["context"]["chunks"]]
        return records, {"route": "corpus_retrieve.query", "collection": result["collection"], "index_revision": result["index_revision"], "retrieval": result["retrieval"]}
    if source.kind == "wiki":
        from .wiki import retrieve

        result = retrieve(source.request)
        records = wiki_records(result)
        return records, {"route": "wiki_manage.ask.context", "context_sha256": result["context_sha256"], "omitted_pages": result["omitted_pages"], "retrieval": result["retrieval"]}
    from .collections_recall import read

    result = read(source.request)
    records = [collection_record(row) for row in result["records"]]
    return records, {"route": "collections_manage.recall", "workspace": result["workspace"], "active_collection": result["active_collection"], "next_offset": result["next_offset"], "LRU_bookkeeping": "canonical_recall"}


def wiki_records(result) -> list[Record]:
    """Keep link claims distinct from matching source text and stale/missing observations."""
    records = []
    for page in result["context"]:
        for link in page["evidence"]:
            records.append(Record(video_id=link["video_id"], source_revision=link["source_revision"], media_digest=link["media_digest"],
                                  observation_id=link["observation_id"], start_seconds=link["start_seconds"], end_seconds=link["end_seconds"],
                                  kind="wiki_evidence", title=page["title"], text=link["observation_text"] or "",
                                  citation_id=link["citation_id"], origin="canonical_wiki", artifact_refs=link["artifact_refs"],
                                  attribution=link["attribution"], claim=link["claim"], stance=link["stance"], source_state=link["source_state"],
                                  page_revision=page["revision"], page_sha256=page["page_sha256"],
                                  method="canonical_wiki_digest_bound_context"))
            if len(records) > 50:
                raise ValueError("Export exceeds 50 records; reduce wiki context selection")
    return records


def collection_record(row) -> Record:
    """Assets without interval/text metadata remain untimed; recall is not content proof."""
    if row["type"] == "observation":
        value = {**row, "artifact_refs": [{k: v for k, v in ref.items() if k != "availability"} for ref in row["artifact_refs"]]}
        return observation(value, "canonical_collections", source_state="current" if row["current"] else "historical")
    kind = "frame" if row["kind"] in ("thumbnail", "keyframe") else "transcript" if row["kind"] == "transcript" else "description"
    refs = [{"artifact_id": row["asset_id"], "kind": kind, "path": row["path"], "sha256": row["sha256"]}]
    return Record(video_id=row["video_id"], source_revision=row["source_revision"], media_digest=row["media_digest"],
                  kind=row["kind"], citation_id=row["asset_id"], origin="canonical_collections", artifact_refs=refs,
                  source_state=row["availability"]["state"], method="canonical_asset_metadata_no_timing_or_text")
