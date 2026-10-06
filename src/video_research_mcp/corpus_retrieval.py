"""Deterministic FTS, supplied-vector cosine and RRF retrieval of exact evidence."""

import json
import math

from . import corpus_index as index
from .models.corpus import CorpusResponse
from .video_memory import text_rank

DENSE_MIN_COSINE = 0.25


def estimate_tokens(context: dict) -> int:
    """utf8_bytes_div4_ceil_v1 over the complete canonical context, including source IDs."""
    return math.ceil(len(index.canonical(context).encode("utf-8")) / 4)


def context_selection(chunks: list, entities: list, budget: int, top_k: int) -> dict:
    """Choose whole chunks then linked entities, charging all context JSON and identities."""
    context = {"chunks": [], "entities": [], "source_ids": []}
    for chunk in chunks:
        if len(context["chunks"]) == top_k:
            break
        proposed = {**context, "chunks": [*context["chunks"], chunk],
                    "source_ids": sorted(set(context["source_ids"]) | {chunk["source_id"]})}
        if estimate_tokens(proposed) <= budget:
            context = proposed
    admitted = {c["observation_id"] for c in context["chunks"]}
    for entity in entities:
        if not set(entity["observation_ids"]).issubset(admitted):
            continue
        proposed = {**context, "entities": [*context["entities"], entity]}
        if estimate_tokens(proposed) <= budget:
            context = proposed
    return context


def local_rank(db, rows, request) -> tuple[list, dict]:
    """Record candidate order, active fallback and RRF scores with stable identity ties."""
    terms = list(dict.fromkeys(text_rank.tokens(request.query)))
    match = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    ids = {row["id"]: n for n, row in enumerate(rows)}
    fts = []
    if match and request.mode != "dense":
        found = db.execute("SELECT id,bm25(terms) score FROM terms WHERE terms MATCH ? ORDER BY score,id", (match,))
        fts = [n for _, n in sorted((row[1], ids[int(row[0])]) for row in found if int(row[0]) in ids)]
    dense, compatible = [], []
    if request.query_vector is not None and request.mode != "fts":
        for n, row in enumerate(rows):
            if row["model"] != request.vector_model or not row["values_json"]:
                continue
            values = json.loads(row["values_json"])
            if len(values) != len(request.query_vector):
                continue
            if not values or not all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) <= 1e6 for v in values):
                raise ValueError("Stored vector is nonfinite or outside the admitted bounds")
            compatible.append(n)
            score = text_rank.cosine(request.query_vector, values)
            if score >= DENSE_MIN_COSINE:
                dense.append((n, score))
        dense.sort(key=lambda item: (-item[1], item[0]))
    dense_ids = [n for n, _ in dense]
    reason = None
    if request.mode == "dense" and not compatible:
        if match:
            found = db.execute("SELECT id,bm25(terms) score FROM terms WHERE terms MATCH ? ORDER BY score,id", (match,))
            fts = [n for _, n in sorted((row[1], ids[int(row[0])]) for row in found if int(row[0]) in ids)]
        reason = "no_compatible_supplied_vectors"
    if request.mode == "hybrid" and not dense_ids:
        reason = "no_compatible_supplied_vectors" if not compatible else "no_dense_matches"
    elif request.mode == "hybrid" and not fts:
        reason = "no_fts_matches"
    lists = [ranked for ranked in (fts, dense_ids) if ranked]
    fused = text_rank.rrf(lists)
    ranked = sorted(fused, key=lambda n: (-fused[n], n))
    active = "hybrid" if fts and dense_ids else "dense" if dense_ids or compatible and request.mode == "dense" else "fts"
    return ranked, {"requested_mode": request.mode, "active_mode": active, "fallback_reason": reason,
                    "candidates": {"fts": [rows[n]["observation"] for n in fts],
                                   "dense": [rows[n]["observation"] for n in dense_ids]},
                    "rrf_k": text_rank.RRF_K, "scores": {rows[n]["observation"]: fused[n] for n in ranked},
                    "dense_min_cosine": DENSE_MIN_COSINE, "provider_calls": 0}


async def query(request) -> dict:
    """Return bounded source context and explicit no-evidence without generating an answer."""
    with index.connect(request.index_path) as db:
        db.execute("BEGIN")
        current = index.revision(db, request.collection)
        rows = index.current_rows(db, request)
        if request.graph is None:
            ranked, retrieval = local_rank(db, rows, request)
            chunks = [index.observation(rows[n]) for n in ranked]
            entities = [{"name": name, "observation_ids": [chunk["observation_id"]],
                         "source_ids": [chunk["source_id"]], "basis": "supplied_observation"}
                        for chunk in chunks for name in chunk["entities"]]
    if request.graph is not None:
        from .corpus_lightrag import graph_context

        chunks, entities, retrieval = await graph_context(request, rows)
    context = context_selection(chunks, entities, request.token_budget, request.top_k)
    return CorpusResponse(status="found" if context["chunks"] else "no_evidence",
                          collection=request.collection, index_revision=current, context=context,
                          retrieval=retrieval, total_token_budget=request.token_budget,
                          estimated_tokens=estimate_tokens(context)).model_dump(mode="json")
