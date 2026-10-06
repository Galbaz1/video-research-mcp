"""Durable exact-quote comment search and deterministic audience operations."""

from .audience_metrics import analyze
from .audience_store import import_sample, load, sampling
from .corpus_index import canonical
from .models.audience import Response


def search(request) -> dict:
    """Search exact stored quotes without replacing text, inferring entities or calling APIs."""
    value, samples = load(request, request.sample_ids)
    records = []
    for sample, digest in samples:
        for comment in sorted(sample.comments, key=lambda c: (c.video_id, c.comment_id)):
            if request.query.casefold() in comment.quoted_text.casefold():
                records.append({**comment.model_dump(mode="json"), "sample_id": sample.sample_id,
                                "sample_sha256": digest, **sampling(sample)})
    page = records[request.offset:request.offset + request.limit]
    result = {"status": "found" if page else "no_evidence", "workspace": request.workspace,
              "collection": request.collection, "index_revision": value, "records": page,
              "total_matches": len(records), "next_offset": request.offset + len(page) if request.offset + len(page) < len(records) else None,
              "sampling": {"algorithm": "literal_unicode_casefold_substring_v1", "sample_ids": sorted(request.sample_ids)}}
    return bounded(result, request.output_bytes)


def bounded(result, limit: int) -> dict:
    """Validate and refuse oversized canonical UTF-8 results without silently clipping quotes."""
    output = Response.model_validate(result).model_dump(mode="json")
    if len(canonical(output).encode()) > limit:
        raise ValueError("Audience output exceeds output_bytes; narrow cohort or search page")
    return output


def execute(request) -> dict:
    """Dispatch supplied import, durable search and a fixed local analytics cohort."""
    if request.action == "import":
        return bounded(import_sample(request), 65536)
    if request.action == "search":
        return search(request)
    value, selected = load(request, [request.sample_id])
    sample, digest = selected[0]
    result = {"status": "analyzed", "workspace": request.workspace, "collection": request.collection,
              "index_revision": value, "sample_id": sample.sample_id, "sample_sha256": digest,
              "sampling": sampling(sample), "analysis": analyze(sample, digest, request)}
    return bounded(result, request.output_bytes)
