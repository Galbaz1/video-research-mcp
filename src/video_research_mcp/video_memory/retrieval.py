"""Evidence-only hybrid retrieval, explicit plans and text embeddings for AV memories.

Adapted from QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f
``src/capabilities/omni-memory/qwen_mm_plugins_omni_memory/mem_core.py`` (``search``,
``search_episodic``, ``search_semantic``, ``run_plan``, ``recall_scene_env``),
``tools/plan_and_search.py`` and ``omni_core.py`` (``embed_texts``, ``get_embed_client``),
Apache-2.0. Changed: embeddings use only the existing ``GeminiClient`` google-genai
client after explicit authorization and every attempted endpoint call is reported;
empty searches return ``not_found`` instead of a broad fallback; plans never answer
and never mutate usage counters.
"""

import math
import re

from ..client import GeminiClient
from ..models.video_memory_av import (
    EmbeddingIndex, EmbeddingOptions, Fact, MemoryRecord, MemoryState, PlanRequest, SearchRequest,
)
from . import text_rank
from .av_build import ProviderFailure
from .av_store import decode_vector, encode_vector

EMBED_ENDPOINT = "google-genai:aio.models.embed_content"
EMBED_BATCH = 50
_QUERY_NAME = re.compile(r"\b[A-Z][a-z]{2,}\b")


def new_costs() -> dict:
    """Actual endpoint attempts and separately planned, unexecuted calls."""
    return {"endpoint_calls": [], "planned_calls": []}


def _usage(response) -> dict | None:
    meta = getattr(response, "metadata", None)
    counts = [e.statistics.token_count for e in response.embeddings or []
              if e.statistics is not None and e.statistics.token_count is not None]
    usage = {"billable_character_count": getattr(meta, "billable_character_count", None),
             "token_counts": counts or None}
    return usage if any(v is not None for v in usage.values()) else None


async def embed_texts(options: EmbeddingOptions, texts: list[str], purpose: str, costs: dict) -> list:
    """Embed texts via ``client.aio.models.embed_content``, recording every attempt first."""
    from google.genai import types

    client = GeminiClient.get()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        call = {"endpoint": EMBED_ENDPOINT, "model": options.model, "purpose": purpose,
                "input_count": len(batch), "input_chars": sum(map(len, batch)),
                "status": "attempted", "usage": None}
        costs["endpoint_calls"].append(call)
        try:
            response = await client.aio.models.embed_content(
                model=options.model,
                contents=[types.Content(role="user", parts=[types.Part(text=t)]) for t in batch],
                config=types.EmbedContentConfig(output_dimensionality=options.output_dimensionality))
        except Exception as exc:
            call["status"] = f"failed:{type(exc).__name__}"
            raise
        values = [list(e.values or []) for e in response.embeddings or []]
        call.update(status="completed", usage=_usage(response))
        if len(values) != len(batch):
            call["status"] = "completed_count_mismatch"
            raise ValueError("Embedding endpoint returned a different number of vectors")
        vectors.extend(values)
    return vectors


def fact_text(fact: Fact) -> str:
    """Name-independent fact text used for both keyword and dense indexing."""
    return f"{fact.subject_id} {fact.key.replace('_', ' ')} {fact.value}"


async def index_memory(state: MemoryState, options: EmbeddingOptions, costs: dict) -> int | None:
    """Embed records and active facts lacking vectors; None means the calls were only planned."""
    index = state.embeddings
    if index and (index.model != options.model or options.output_dimensionality not in (None, index.dimension)):
        raise ValueError("Embedding model/dimension differs from the stored index; use a new memory")
    stored = dict(index.vectors) if index else {}
    items = [(r.record_id, r.text) for r in state.records]
    items += [(f.fact_id, fact_text(f)) for f in state.facts if f.status == "active"]
    missing = [(item_id, text) for item_id, text in items if item_id not in stored]
    calls = math.ceil(len(missing) / EMBED_BATCH)
    if calls > options.max_calls:
        raise ValueError(f"Indexing needs {calls} embedding calls; embedding.max_calls is {options.max_calls}")
    if not options.authorize_provider_calls:
        costs["planned_calls"].append({"endpoint": EMBED_ENDPOINT, "model": options.model, "purpose": "index",
                                       "calls": calls, "inputs": len(missing),
                                       "input_chars": sum(len(t) for _, t in missing)})
        return None
    try:
        vectors = await embed_texts(options, [t for _, t in missing], "index", costs) if missing else []
    except Exception as exc:
        raise ProviderFailure(f"Embedding indexing failed: {type(exc).__name__}", {"costs": costs}) from exc
    dims = {len(v) for v in vectors} | ({index.dimension} if index else set())
    if len(dims) > 1 or (options.output_dimensionality and dims - {options.output_dimensionality}):
        raise ProviderFailure("Embedding dimensions are inconsistent; nothing was written", {"costs": costs})
    try:
        stored.update({item_id: encode_vector(v) for (item_id, _), v in zip(missing, vectors)})
        if stored:
            state.embeddings = EmbeddingIndex(endpoint=EMBED_ENDPOINT, model=options.model,
                                              dimension=dims.pop(), vectors=stored)
    except ValueError as exc:
        raise ProviderFailure(f"Embedding reply was not admitted; nothing was written: {exc}",
                              {"costs": costs}) from exc
    return len(missing)


async def query_vector(state: MemoryState, options: EmbeddingOptions | None, query: str,
                       costs: dict) -> tuple[list[float] | None, str | None]:
    """Dense query vector, or None with the exact reason retrieval stays keyword-only."""
    index = state.embeddings
    if options is None:
        return None, "no_embedding_model"
    if index is None or not index.vectors:
        return None, "no_vectors"
    if options.model != index.model or options.output_dimensionality not in (None, index.dimension):
        return None, "model_mismatch"
    if not options.authorize_provider_calls:
        costs["planned_calls"].append({"endpoint": EMBED_ENDPOINT, "model": options.model,
                                       "purpose": "query", "inputs": 1, "input_chars": len(query)})
        return None, "not_authorized"
    if sum(1 for c in costs["endpoint_calls"] if c["purpose"] == "query") >= options.max_calls:
        return None, "call_limit_reached"
    try:
        vector = (await embed_texts(options, [query], "query", costs))[0]
    except Exception as exc:
        return None, f"endpoint_failed:{type(exc).__name__}"
    if not vector or not all(math.isfinite(v) for v in vector) or not any(vector):
        return None, "invalid_query_vector"
    if len(vector) != index.dimension:
        return None, "dimension_mismatch"
    return vector, None


def rank(entries: list[tuple[str, str, str]], query: str, qvec, vectors: dict, k: int,
         boost_query: str = "") -> list[dict]:
    """RRF of BM25 (with a person boost field) and dense cosine over (id, text, boost)."""
    sparse = text_rank.bm25_rank([e[1] for e in entries], query, [e[2] for e in entries], boost_query)
    lists, dense = ([sparse] if sparse else []), []
    if qvec is not None:
        scored = [(i, text_rank.cosine(qvec, decode_vector(vectors[e[0]])))
                  for i, e in enumerate(entries) if e[0] in vectors]
        dense = [i for i, _ in sorted(scored, key=lambda pair: (-pair[1], pair[0]))]
        lists.append(dense)
    fused = text_rank.rrf(lists)
    keyword_rank, dense_rank = {i: r for r, i in enumerate(sparse)}, {i: r for r, i in enumerate(dense)}
    return [{"id": entries[i][0], "score": fused[i], "keyword_rank": keyword_rank.get(i),
             "dense_rank": dense_rank.get(i)} for i in sorted(fused, key=lambda i: (-fused[i], i))[:k]]


def matched_people(state: MemoryState, query: str) -> list[dict]:
    """Persons whose resolved or suggested names sound like a capitalized query word."""
    words = _QUERY_NAME.findall(query)
    found = []
    for person in state.persons:
        heard = [(person.name, "resolved_name")] if person.name else []
        heard += [(s.name, "suggestion") for s in state.suggestions if s.person_id == person.person_id]
        hit = next(((n, via) for n, via in heard for w in words if text_rank.phonetic_match(n, w)), None)
        if hit:
            found.append({"person_id": person.person_id, "heard_as": hit[0], "via": hit[1]})
    return found


def record_view(state: MemoryState, record: MemoryRecord, hit: dict | None = None) -> dict:
    """Stored record plus read-time person name; names are never written into records."""
    names = {p.person_id: p.name for p in state.persons}
    view = record.model_dump(mode="json") | {"person_name": names.get(record.person_id)}
    return view | ({"rank": {k: hit[k] for k in ("score", "keyword_rank", "dense_rank")}} if hit else {})


async def _record_search(state, records, query, options, top_k, costs) -> tuple[list, dict, list]:
    people = matched_people(state, query)
    qvec, reason = await query_vector(state, options, query, costs)
    vectors = state.embeddings.vectors if state.embeddings else {}
    entries = [(r.record_id, r.text, r.person_id or "") for r in records]
    hits = rank(entries, query, qvec, vectors, top_k, " ".join(p["person_id"] for p in people))
    by_id = {r.record_id: r for r in records}
    mode = {"mode": "hybrid" if qvec is not None else "keyword_only", "dense_unavailable_reason": reason}
    return [record_view(state, by_id[h["id"]], h) for h in hits], mode, people


async def _fact_search(state: MemoryState, request: SearchRequest, costs: dict) -> tuple[list, dict]:
    names = {p.person_id: p.name for p in state.persons}
    facts = [f for f in state.facts if request.include_superseded or f.status == "active"]
    if request.subject_id:
        facts = [f for f in facts if f.subject_id == request.subject_id]
    if request.key_prefix:
        prefix = request.key_prefix.lower()
        facts = [f for f in facts if f"{f.subject_id}/{f.key}".lower().startswith(prefix)
                 or f"{names.get(f.subject_id) or ''}/{f.key}".lower().startswith(prefix)]
    if request.query is None:
        chosen = sorted(facts, key=lambda f: (f.subject_id, f.key, f.fact_id))[: request.top_k]
        return [f.model_dump(mode="json") for f in chosen], {"mode": "filter", "dense_unavailable_reason": None}
    qvec, reason = await query_vector(state, request.embedding, request.query, costs)
    vectors = state.embeddings.vectors if state.embeddings else {}
    entries = [(f.fact_id, f"{names.get(f.subject_id) or ''} {fact_text(f)}", "") for f in facts]
    by_id = {f.fact_id: f for f in facts}
    hits = rank(entries, request.query, qvec, vectors, request.top_k)
    mode = {"mode": "hybrid" if qvec is not None else "keyword_only", "dense_unavailable_reason": reason}
    return [by_id[h["id"]].model_dump(mode="json") | {"rank": h} for h in hits], mode


async def search(state: MemoryState, request: SearchRequest, costs: dict) -> dict:
    """Search one container; an empty result is reported, never replaced."""
    people: list = []
    if request.scope == "facts":
        results, retrieval = await _fact_search(state, request, costs)
    else:
        records = [r for r in state.records if request.scope == "memory" or r.kind == "utterance"]
        results, retrieval, people = await _record_search(
            state, records, request.query, request.embedding, request.top_k, costs)
    return {"status": "found" if results else "not_found", "scope": request.scope, "query": request.query,
            "results": results, "matched_people": people, "retrieval": retrieval}


def _environment_step(state: MemoryState, queries: list[str], k: int) -> dict:
    environment = sorted((r for r in state.records if r.kind == "environment"),
                         key=lambda r: (r.start_seconds, r.record_id))
    hits = rank([(r.record_id, r.text, "") for r in environment], " ".join(queries), None, {}, k)
    by_id = {r.record_id: r for r in environment}
    chosen = [record_view(state, by_id[h["id"]], h) for h in hits]
    match = "keyword" if chosen else "unranked_recall"
    chosen = chosen or [record_view(state, r) for r in environment[:k]]
    return {"step": "environment", "input": None, "status": "found" if chosen else "not_found",
            "match": match, "records": chosen}


def _fact_keys(state: MemoryState) -> dict[str, Fact]:
    """Exact active keys by person ID, plus resolved-name aliases such as ``Alice/role``."""
    names = {p.person_id: p.name for p in state.persons if p.name}
    keyed: dict[str, Fact] = {}
    for fact in (f for f in state.facts if f.status == "active"):
        keyed[f"{fact.subject_id}/{fact.key}"] = fact
        if fact.subject_id in names:
            keyed.setdefault(f"{names[fact.subject_id]}/{fact.key}", fact)
    return keyed


async def run_plan(state: MemoryState, request: PlanRequest, costs: dict) -> dict:
    """Execute every caller-named step and return evidence records only."""
    persons = {p.person_id: p for p in state.persons}
    steps: list[dict] = [{"step": "person", "input": pid, "status": "found" if pid in persons else "not_found",
                          "person": persons[pid].model_dump(mode="json") if pid in persons else None}
                         for pid in request.people]
    keyed = _fact_keys(state)
    steps += [{"step": "fact_key", "input": key, "status": "found" if key in keyed else "not_found",
               "facts": [keyed[key].model_dump(mode="json")] if key in keyed else []} for key in request.fact_keys]
    question = request.question.strip()
    queries = list(dict.fromkeys([*request.queries, *([question] if question else [])]))
    modes = []
    for query in queries:
        found, retrieval, people = await _record_search(state, state.records, query, request.embedding,
                                                        request.top_k, costs)
        modes.append(retrieval)
        steps.append({"step": "query", "input": query, "status": "found" if found else "not_found",
                      "records": found, "matched_people": people, "retrieval": retrieval})
    for start, end in request.time_ranges:
        inside = sorted((r for r in state.records if r.end_seconds >= start and r.start_seconds <= end),
                        key=lambda r: (r.start_seconds, r.record_id))
        steps.append({"step": "time_range", "input": [start, end], "status": "found" if inside else "not_found",
                      "records": [record_view(state, r) for r in inside]})
    if request.include_environment:
        steps.append(_environment_step(state, queries, request.top_k))
    query_windows = [rec["window"] for s in steps if s["step"] == "query" for rec in s["records"]]
    evidence = sorted({rec["record_id"] for s in steps for rec in s.get("records", [])})
    return {"question": request.question, "plan_used": request.model_dump(mode="json", exclude={"embedding"}),
            "steps": steps, "evidence_record_ids": evidence,
            "suggested_windows": list(dict.fromkeys(query_windows))[:3], "retrieval": modes}
