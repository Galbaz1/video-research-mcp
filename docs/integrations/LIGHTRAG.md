# Corpus retrieval and optional LightRAG

`corpus_retrieve` is mounted in the root [server](../../src/video_research_mcp/server.py). It retrieves evidence from a local SQLite corpus without requiring Weaviate or an embedding runtime. Optional LightRAG queries use a separately operated service. Registration alone does not establish installed runtime or programme acceptance.

Call `corpus_retrieve` with a discriminated `action`: `index`, `query`, or `repair`. Every request requires a local `.sqlite3` path and collection. Indexing supplies observations and an optimistic `expected_revision` (zero initially). Each observation contains video/observation IDs, speech/OCR/description type, finite exact endpoints, source revision, media digest, text, entities, and local artifact IDs/paths/digests. Metadata is supplied, not authenticated artifact bytes. Querying requires an explicit `source_revisions` map. Missing or stale sources are filtered; historical observations and vectors remain retained. Reusing a historical revision or changing an immutable observation fails.

Local modes are `fts`, `dense`, and `hybrid`. Dense vectors and query vectors require an explicit matching model identity; no embedding runtime executes. Model/dimension absence falls back to FTS. FTS absence permits dense fallback. Returned candidates, active mode, fallback reason, fixed cosine floor 0.25 and RRF k=60 explain selection. Ties use stable source identity. The floor is a heuristic, not held-out calibration. `repair` changes supplied current vectors and the index revision counter; observation/FTS/source/media metadata stays unchanged and no media is read or downloaded.

All results are context-only: whole chosen chunks, linked entities and source IDs. `utf8_bytes_div4_ceil_v1` estimates the entire canonical UTF-8 context JSON, rounding bytes/4 upward. It includes identities and entity metadata, but is not a provider tokenizer. Selection stays inside `token_budget`; empty selection returns `no_evidence`. No generated answer is supplied.

An explicit `graph` request supplies an HTTP literal loopback origin with port, `local/global/hybrid/mix` mode, and nonempty high/low keyword lists. The adapter POSTs `/query/data` once with `only_need_context=true`, explicit budgets and references, no reranking, environment proxy or redirects. It caps replies at 1 MiB and checks response mode. Returned chunks must exactly match registered text and artifact paths in the current collection/revisions. Graph entities require a single returned chunk ID and are labeled `external_graph_assertion`. Unsupported composite source IDs are omitted. Graph disabled imports no upstream framework and contacts no service. Service authentication, indexing, embeddings, availability and remote costs remain operator responsibilities; protected endpoints need a separately qualified operator route. Context-only does not prove absence of remote embedding/inference calls.

| Clause | R142 source checks | Remaining gate at that checkpoint |
|---|---|---|
| C1 | Fixed multi-video types, intervals, explicit absence | Installed fixed corpus |
| C2 | No shared edits; disabled graph contacts nothing | Root mount and installed core/Weaviate availability |
| C3 | No advantage claimed or held-out acquisition | Frozen held-out correctness and supported-answer comparison |
| C4 | Chunks/entities/source IDs and full-context budget | Installed graph/context fidelity |
| C5 | Exact IDs/spans and supplied artifact receipts | Retrieve and verify real frame/transcript bytes |
| C6 | FTS/dense fallback, recorded deterministic RRF | Installed recorded candidate checks |
| C7 | Atomic vector repair; unchanged source/FTS/observations | Original-media preservation receipt |
| C8 | Mandatory collection/current revision filters | Frozen corpus revision/conflict procedure |

Source ideas only; no foreign code, assets, models or runtime copied/imported:

- [direct.retrieval contract](https://github.com/smallthinkingmachines/video-context-mcp/blob/4f39f0312401bc428f07dcd69da6b757daf3e441/src/tools/search-videos.ts), MIT. [Notice/license](https://github.com/smallthinkingmachines/video-context-mcp/blob/4f39f0312401bc428f07dcd69da6b757daf3e441/LICENSE): Copyright (c) 2026 Studio1804, Small Thinking Machines, and Ricardo Ledan.
- [LightRAG query contract](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/lightrag/api/routers/query_routes.py), integration-only, MIT. [Notice/license](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/LICENSE): Copyright (c) 2025 LightRAG Team. Query schema, endpoint, data schema and handler were read in bounded pinned fragments; receipts are in the private R142 packet. Dependencies and operated services retain separate licenses.

The R142 source checkpoint used mocks; no installed, native, human or held-out evaluation ran in that stage. It establishes neither LightRAG superiority nor default adoption.
