"""Independent context adapter for HKUDS/LightRAG@453dce83, MIT; no upstream imports."""

import asyncio
import json
from urllib.parse import urlsplit

from . import corpus_index as index

MAX_RESPONSE_BYTES = 1024 * 1024


def endpoint(value: str) -> str:
    """Permit only an explicit HTTP literal loopback origin, with no credentials or redirect."""
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.port is None):
        raise ValueError("LightRAG endpoint must be an HTTP literal loopback origin with an explicit port")
    return value.rstrip("/") + "/query/data"


def admit_context(value: dict, rows) -> tuple[list, list, int]:
    """Admit only exact registered chunks and graph entities linked by a returned chunk ID."""
    if not isinstance(value, dict) or value.get("status") != "success" or not isinstance(value.get("data"), dict):
        raise ValueError("LightRAG did not return a successful structured context")
    data = value["data"]
    if any(not isinstance(data.get(key), list) or len(data[key]) > 500 for key in ("chunks", "entities", "references")):
        raise ValueError("LightRAG context lists are absent, invalid or exceed 500 entries")
    observations = [index.observation(row) for row in rows]
    refs = {r["reference_id"]: r["file_path"] for r in data["references"]}
    chunks, links, rejected = [], {}, 0
    seen = set()
    for chunk in data["chunks"]:
        path = refs.get(chunk.get("reference_id"))
        matches = [o for o in observations if o["text"] == chunk.get("content")
                   and path == chunk.get("file_path") and path in {r["path"] for r in o["artifact_refs"]}]
        if not matches or not isinstance(chunk.get("chunk_id"), str):
            rejected += 1
            continue
        links[chunk["chunk_id"]] = matches
        for obs in matches:
            if obs["observation_id"] not in seen:
                chunks.append(obs)
                seen.add(obs["observation_id"])
    entities = []
    for item in data["entities"]:
        linked = links.get(item.get("source_id"), [])
        if linked and isinstance(item.get("entity_name"), str) and isinstance(item.get("description"), str):
            entities.append({"name": item["entity_name"], "description": item["description"],
                             "observation_ids": [o["observation_id"] for o in linked],
                             "source_ids": sorted({o["source_id"] for o in linked}),
                             "basis": "external_graph_assertion"})
    return chunks, entities, rejected


async def graph_context(request, rows) -> tuple[list, list, dict]:
    """POST the pinned context-only contract once; fail closed on service or provenance errors."""
    import httpx

    route = request.graph
    url = endpoint(route.endpoint)
    body = {"query": request.query, "mode": route.mode, "only_need_context": True,
            "only_need_prompt": False, "top_k": request.top_k, "chunk_top_k": request.top_k,
            "max_total_tokens": request.token_budget, "max_entity_tokens": request.token_budget,
            "max_relation_tokens": request.token_budget, "include_references": True,
            "hl_keywords": route.hl_keywords, "ll_keywords": route.ll_keywords, "enable_rerank": False}
    async with asyncio.timeout(20), httpx.AsyncClient(
        trust_env=False, follow_redirects=False, timeout=20
    ) as client:
        async with client.stream("POST", url, json=body) as response:
            response.raise_for_status()
            if 300 <= response.status_code < 400:
                raise ValueError("LightRAG redirects are refused")
            raw = bytearray()
            async for part in response.aiter_bytes():
                if len(raw) + len(part) > MAX_RESPONSE_BYTES:
                    raise ValueError("LightRAG context exceeds 1 MiB")
                raw.extend(part)
    value = json.loads(raw)
    if value.get("metadata", {}).get("query_mode") != route.mode:
        raise ValueError("LightRAG response mode does not match the requested mode")
    chunks, entities, rejected = admit_context(value, rows)
    return chunks, entities, {"requested_mode": route.mode, "active_mode": "lightrag_" + route.mode,
                              "rejected_chunks": rejected, "service_calls": 1,
                              "remote_inference_and_account_cost": "UNKNOWN"}
