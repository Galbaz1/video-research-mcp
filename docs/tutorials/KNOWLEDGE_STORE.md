# Knowledge Store

How the knowledge store works, how to set up Weaviate, and how to use the 7 knowledge tools for persistent semantic search across all tool results.

## What It Is

The knowledge store is an **optional Weaviate-backed persistence layer** that automatically saves results from every tool call. When enabled, each tool's output is written through to a Weaviate collection, building a searchable knowledge base over time.

Without Weaviate configured, the server works identically -- knowledge tools return empty results and write-through calls are silently skipped.

## Architecture

```
Tool call (e.g., video_analyze)
  |
  +-- Returns result to caller (always)
  |
  +-- Writes to Weaviate collection (if enabled, non-blocking, non-fatal)
       |
       +-- VideoAnalyses collection

Knowledge tools (knowledge_search, knowledge_related, knowledge_ask, etc.)
  |
  +-- Query Weaviate collections
  |
  +-- Return ranked results to caller
```

Three modules implement the knowledge store:

| Module | Responsibility |
|--------|---------------|
| `weaviate_client.py` | Singleton client, connection management, schema bootstrap |
| `weaviate_schema/` | 12 collection definitions (PropertyDef, CollectionDef dataclasses) |
| `weaviate_store/` | Write-through functions (one per collection) |

The 7 knowledge tools live in `tools/knowledge/` (split into `search.py`, `retrieval.py`, `ingest.py`, and `agent.py`).

## Setup

### Option A: Local Weaviate (Docker)

```bash
docker run -d \
  --name weaviate \
  -p 8080:8080 \
  -p 50051:50051 \
  cr.weaviate.io/semitechnologies/weaviate:latest \
  --host 0.0.0.0 \
  --port 8080 \
  --scheme http
```

Set the env var:

```bash
export WEAVIATE_URL="http://localhost:8080"
```

### Option B: Weaviate Cloud (WCS)

Create a cluster at [console.weaviate.cloud](https://console.weaviate.cloud), then:

```bash
export WEAVIATE_URL="https://your-cluster.weaviate.network"
export WEAVIATE_API_KEY="your-weaviate-api-key"
```

### Verify Connection

Start the MCP server. On first connection, it will auto-create all 12 collections if they do not exist. Check logs for:

```
INFO: Connected to Weaviate at http://localhost:8080
INFO: Created Weaviate collection: ResearchFindings
INFO: Created Weaviate collection: VideoAnalyses
...
```

## The 12 Collections

Each collection stores results from specific tools. All collections share two common properties: `created_at` (date) and `source_tool` (text).

### ResearchFindings

Stores findings from `research_deep` and `research_assess_evidence`.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| topic | text | yes | Research topic |
| scope | text | no | Research scope |
| claim | text | yes | Individual finding or claim |
| evidence_tier | text | no | CONFIRMED, STRONG INDICATOR, INFERENCE, SPECULATION, UNKNOWN |
| reasoning | text | yes | Supporting reasoning |
| executive_summary | text | yes | Report executive summary |
| confidence | number | no | Confidence score 0-1 |
| open_questions | text[] | no | Open research questions |

### VideoAnalyses

Stores results from `video_analyze` and `video_batch_analyze`.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| video_id | text | no | YouTube video ID or file hash |
| source_url | text | no | Source URL or file path |
| instruction | text | yes | Analysis instruction used |
| title | text | yes | Video title |
| summary | text | yes | Analysis summary |
| key_points | text[] | yes | Key points extracted |
| raw_result | text | no | Full JSON result |

### ContentAnalyses

Stores results from `content_analyze`.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| source | text | no | Source URL, file path, or '(text)' |
| instruction | text | yes | Analysis instruction used |
| title | text | yes | Content title |
| summary | text | yes | Analysis summary |
| key_points | text[] | yes | Key points extracted |
| entities | text[] | yes | Named entities found |
| raw_result | text | no | Full JSON result |

### VideoMetadata

Stores YouTube metadata from `video_metadata`. Uses deterministic UUIDs based on `video_id` for automatic deduplication.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| video_id | text | no | YouTube video ID |
| title | text | yes | Video title |
| description | text | yes | Video description |
| channel_title | text | yes | Channel name |
| tags | text[] | yes | Video tags |
| view_count | int | no | View count |
| like_count | int | no | Like count |
| duration | text | no | Video duration |
| published_at | text | no | Publish date |

### SessionTranscripts

Stores conversation turns from `video_continue_session`.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| session_id | text | no | Session ID |
| video_title | text | yes | Video title for this session |
| turn_index | int | no | Turn number in session |
| turn_prompt | text | yes | User prompt for this turn |
| turn_response | text | yes | Model response for this turn |

### WebSearchResults

Stores results from `web_search`.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| query | text | yes | Search query |
| response | text | yes | Search response text |
| sources_json | text | no | Grounding sources as JSON |

### ResearchPlans

Stores orchestration plans from `research_plan`.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| topic | text | yes | Research topic |
| scope | text | no | Research scope |
| task_decomposition | text[] | yes | Task breakdown |
| phases_json | text | no | Phases as JSON |

### DeepResearchReports

Stores completed long-running Deep Research reports and follow-up Q&A.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| interaction_id | text | no | Gemini Interactions API ID |
| topic | text | yes | Research question/brief |
| report_text | text | yes | Full report text |
| sources_json | text | no | Report source list as JSON |
| source_count | int | no | Number of sources |
| usage_json | text | no | Token usage details as JSON |
| follow_up_ids | text[] | no | Follow-up interaction IDs |
| follow_ups_json | text | no | Follow-up Q&A as JSON |

### CommunityReactions

Stores YouTube comment sentiment analysis from the comment-analyst agent.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| video_id | text | no | YouTube video ID |
| video_title | text | yes | Video title |
| comment_count | int | no | Number of comments analyzed |
| sentiment_positive | number | no | Positive sentiment 0-100 |
| sentiment_negative | number | no | Negative sentiment 0-100 |
| sentiment_neutral | number | no | Neutral sentiment 0-100 |
| themes_positive | text[] | yes | Positive themes from comments |
| themes_critical | text[] | yes | Critical themes from comments |
| consensus | text | yes | Community consensus assessment |

### ConceptKnowledge

Stores concepts extracted from analyses with knowledge state tracking.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| concept_name | text | yes | Name of the concept |
| state | text | no | Knowledge state: know, fuzzy, or unknown |
| source_url | text | no | URL or path of source content |
| source_title | text | yes | Title of the source content |
| source_category | text | no | Category: video, video-chat, research, analysis |
| description | text | yes | Brief description of the concept |

### RelationshipEdges

Stores directed relationships between concepts from analyses.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| from_concept | text | yes | Source concept name |
| to_concept | text | yes | Target concept name |
| relationship_type | text | no | Type: enables, example_of, builds_on, contradicts, related_to |
| source_url | text | no | URL or path of source content |
| source_category | text | no | Category: video, video-chat, research, analysis |

### CallNotes

Stores structured notes from meeting and call recordings.

| Property | Type | Vectorized | Description |
|----------|------|-----------|-------------|
| video_id | text | no | YouTube video ID or file hash |
| source_url | text | no | Source URL or file path |
| title | text | yes | Meeting/call title |
| summary | text | yes | Meeting summary |
| participants | text[] | yes | Meeting participants |
| decisions | text[] | yes | Decisions made |
| action_items | text[] | yes | Action items |
| topics_discussed | text[] | yes | Topics discussed |

## Using the Knowledge Tools

### knowledge_search -- search across collections

Supports three search modes: hybrid (default), semantic, and keyword. Optional Cohere reranking and Gemini Flash summarization enrich results when enabled.

```
Use knowledge_search with query "transformer architecture"
Use knowledge_search with query "RLHF" and search_type "semantic"
Use knowledge_search with query "batch normalization" and search_type "keyword"
```

Parameters:
- `query` (required) -- search text
- `search_type` (optional) -- `"hybrid"` (default), `"semantic"`, or `"keyword"`
- `collections` (optional) -- list of collection names to search; defaults to all 12
- `limit` (optional) -- max results per collection (default 10)
- `alpha` (optional) -- hybrid balance: 0.0 = pure keyword, 1.0 = pure vector, 0.5 = balanced (hybrid mode only)
- `evidence_tier` (optional) -- filter ResearchFindings by tier (e.g. `"CONFIRMED"`)
- `source_tool` (optional) -- filter by originating tool name
- `date_from` / `date_to` (optional) -- filter by ISO date range on `created_at`
- `category` (optional) -- filter VideoMetadata by category
- `video_id` (optional) -- filter by video_id field

Search modes:
- **hybrid** -- fuses BM25 keyword scores with vector similarity via `collection.query.hybrid()`
- **semantic** -- pure vector similarity via `collection.query.near_text()`; finds semantically similar content even without keyword overlap
- **keyword** -- pure BM25 keyword matching via `collection.query.bm25()`; precise when you know the exact terms

Results are merged across collections and sorted by rerank score (when available) then base score descending.

**Result fields** (`KnowledgeHit`):
- `collection` -- source collection name
- `object_id` -- Weaviate UUID
- `score` -- base relevance score (from search mode)
- `rerank_score` -- Cohere reranker score (null when reranking not enabled)
- `summary` -- Flash-generated relevance summary (null when summarization not enabled)
- `properties` -- object property dict (trimmed to useful properties when Flash summarization is active)

**Response fields** (`KnowledgeSearchResult`):
- `query`, `total_results`, `results` -- standard envelope
- `filters_applied` -- active filter dict (null if no filters)
- `reranked` -- true when Cohere reranking was applied
- `flash_processed` -- true when Flash summarization was applied

### knowledge_related -- find similar objects

Uses Weaviate's near-object vector search to find semantically related entries.

```
Use knowledge_related with object_id "uuid-from-search" and collection "VideoAnalyses"
```

Parameters:
- `object_id` (required) -- UUID of the source object (from a search result)
- `collection` (required) -- which collection the source belongs to
- `limit` (optional) -- max results (default 5)

The source object is automatically excluded from results.

### knowledge_stats -- object counts

```
Use knowledge_stats
Use knowledge_stats with collection "ResearchFindings"
```

Returns per-collection counts and total. Useful for monitoring knowledge base growth.

### knowledge_fetch -- retrieve object by UUID

Fetch a single object directly by its UUID. Useful for retrieving specific objects found in search results.

```
Use knowledge_fetch with object_id "uuid-from-search" and collection "ResearchFindings"
```

Parameters:
- `object_id` (required) -- Weaviate UUID of the object
- `collection` (required) -- which collection the object belongs to

Returns `found: true` with the object's properties, or `found: false` if the UUID doesn't exist.

### knowledge_ingest -- manual data entry

Insert data directly into any collection. Properties are validated against the collection schema.

```
Use knowledge_ingest with collection "ResearchFindings" and properties:
{"topic": "AI Safety", "claim": "RLHF reduces harmful outputs", "evidence_tier": "CONFIRMED", "confidence": 0.85}
```

Unknown properties are rejected with an error listing the allowed fields.

### knowledge_ask -- AI-generated answers (QueryAgent)

Ask a natural-language question and get a synthesized answer with source citations. Powered by Weaviate's QueryAgent.

```
Use knowledge_ask with query "What were the key findings about transformer architectures?"
Use knowledge_ask with query "How does RLHF work?" and collections ["ResearchFindings"]
```

Parameters:
- `query` (required) -- natural-language question
- `collections` (optional) -- list of collection names to query; defaults to all 12

Returns an AI-generated `answer` string plus a `sources` list with collection name and object UUID for each cited source.

**Requires**: `pip install video-research-mcp[agents]` (installs `weaviate-agents>=1.2.0`). Returns a clear error hint if the package is not installed.

### knowledge_query -- DEPRECATED

> **Deprecated**: Use `knowledge_search` instead. `knowledge_search` now includes Cohere reranking and Flash summarization, making `knowledge_query` redundant. `knowledge_ask` (AI-powered Q&A) is unaffected.

`knowledge_query` still functions during the deprecation period but returns a `_deprecated: true` flag in all responses. It will be removed in a future release. Migrate to `knowledge_search` for all retrieval needs.

### How knowledge_search compares to knowledge_ask

| Feature | `knowledge_search` | `knowledge_ask` |
|---------|--------------------|------------------------------------|
| Search mode | Explicit (hybrid/semantic/keyword) | Automatic (QueryAgent decides) |
| Filters | Manual (evidence_tier, date_from, etc.) | Inferred from natural language |
| Reranking | Cohere (when `COHERE_API_KEY` set) | N/A |
| Summarization | Gemini Flash (relevance scoring + trimming) | N/A |
| Output | Objects with scores + summaries | Synthesized answer + source citations |
| Dependency | `weaviate-client` only | `weaviate-agents` (optional) |
| Best for | Precise, repeatable queries with score transparency | Exploratory questions, "what do I know about X?" |

The QueryAgent instance (used by `knowledge_ask`) is lazily created on first use and cached by the frozenset of target collection names.

## Cohere Reranking

When enabled, `knowledge_search` overfetches results (3x the requested limit) and re-scores them with Cohere's reranker before returning the top results. This significantly improves relevance, especially for hybrid and keyword searches.

### Enabling reranking

Set `COHERE_API_KEY` in your environment. Reranking auto-enables when a Cohere key is present:

```bash
export COHERE_API_KEY="your-cohere-api-key"
```

To explicitly control:

```bash
export RERANKER_ENABLED=true   # force-enable (requires COHERE_API_KEY)
export RERANKER_ENABLED=false  # force-disable even with key present
```

When `COHERE_API_KEY` is set and `RERANKER_ENABLED` is not `"false"`, reranking activates automatically.

### How it works

Each collection has a designated rerank property -- the text field that best represents the semantic content of objects in that collection:

| Collection | Rerank property |
|------------|----------------|
| ResearchFindings | `claim` |
| VideoAnalyses | `summary` |
| ContentAnalyses | `summary` |
| VideoMetadata | `description` |
| SessionTranscripts | `turn_response` |
| WebSearchResults | `response` |
| ResearchPlans | `topic` |
| CommunityReactions | `consensus` |
| ConceptKnowledge | `description` |
| RelationshipEdges | `relationship_type` |
| CallNotes | `summary` |
| DeepResearchReports | `report_text` |

The overfetch pattern:
1. Request `limit * 3` results from Weaviate (with Cohere `Rerank` config attached)
2. Weaviate sends the overfetched results to Cohere for scoring
3. Results are sorted by `rerank_score` (descending), with `score` as tiebreaker
4. The `rerank_score` field appears on each `KnowledgeHit`; `reranked: true` on the response

When reranking is off, results use the base score only and `rerank_score` is null.

### Configuration reference

| Env var | Default | Effect |
|---------|---------|--------|
| `COHERE_API_KEY` | `""` | Cohere API key; presence auto-enables reranking |
| `RERANKER_ENABLED` | (auto) | `"true"` = force on, `"false"` = force off, empty = auto from key |
| `RERANKER_PROVIDER` | `"cohere"` | Reranker backend (only Cohere supported currently) |

Source: `config.py:ServerConfig.reranker_enabled`, `tools/knowledge/helpers.py:RERANK_PROPERTY`

## Flash Summarization

After search (and optional reranking), `knowledge_search` runs Gemini Flash over the results to:

1. **Score relevance** -- each hit gets a 0-1 relevance score against the query
2. **Generate summaries** -- a one-line relevance summary per hit
3. **Trim properties** -- identifies which property names are worth keeping, reducing token consumption when results are sent to Claude's context window

### Enabling Flash summarization

Enabled by default. To disable:

```bash
export FLASH_SUMMARIZE=false
```

### How it works

The summarizer (`tools/knowledge/summarize.py`) batches up to 20 hits and sends them to Gemini Flash (`gemini-3-flash-preview`) with `thinking_level="minimal"` for fast processing.

The `HitSummaryBatch` model structures Flash's output:

```python
class HitSummary(BaseModel):
    object_id: str       # Weaviate UUID
    relevance: float     # 0-1 relevance score
    summary: str         # One-line relevance summary
    useful_properties: list[str]  # Property names worth keeping

class HitSummaryBatch(BaseModel):
    summaries: list[HitSummary]
```

After Flash responds:
- Each hit's `summary` field is populated with the generated summary
- Each hit's `properties` dict is trimmed to only the properties Flash identified as useful (falls back to all properties if Flash returns an empty list)
- The response's `flash_processed: true` flag indicates summarization ran

Flash summarization is **best-effort** -- on any error, the raw hits are returned unchanged.

### Configuration reference

| Env var | Default | Effect |
|---------|---------|--------|
| `FLASH_SUMMARIZE` | `"true"` | Set to `"false"` to disable |

Source: `config.py:ServerConfig.flash_summarize`, `tools/knowledge/summarize.py`

## Write-Through Store Pattern

Every tool that produces results automatically writes them to Weaviate via functions in `weaviate_store/`. This is the biggest architectural pattern to understand when adding new tools.

### Which tools store to which collections

| Tool | Store function | Collection |
|------|---------------|------------|
| `video_analyze` | `store_video_analysis` | VideoAnalyses |
| `video_batch_analyze` | `store_video_analysis` (per file) | VideoAnalyses |
| `video_continue_session` | `store_session_turn` | SessionTranscripts |
| `video_metadata` | `store_video_metadata` | VideoMetadata |
| `content_analyze` | `store_content_analysis` | ContentAnalyses |
| `content_batch_analyze` | `store_content_analysis` (per file) | ContentAnalyses |
| `research_deep` | `store_research_finding` | ResearchFindings |
| `research_document` | `store_research_finding` | ResearchFindings |
| `research_plan` | `store_research_plan` | ResearchPlans |
| `research_assess_evidence` | `store_evidence_assessment` | ResearchFindings |
| `research_web_status` | `store_deep_research` | DeepResearchReports |
| `research_web_followup` | `store_deep_research_followup` | DeepResearchReports |
| `web_search` | `store_web_search` | WebSearchResults |

### The pattern

```python
# In a tool function, after computing the result:
from ..weaviate_store import store_video_analysis
await store_video_analysis(result, content_id, instruction, source_url)
```

Each store function follows the same structure:

```python
async def store_video_analysis(result, content_id, instruction, source_url=""):
    """Store a video analysis result. Returns UUID or None."""
    if not _is_enabled():          # Guard: skip if Weaviate not configured
        return None
    try:
        def _insert():
            client = WeaviateClient.get()
            collection = client.collections.get("VideoAnalyses")
            return str(collection.data.insert(properties={
                "created_at": _now(),
                "source_tool": "video_analyze",
                "video_id": content_id,
                "source_url": source_url,
                "instruction": instruction,
                "title": result.get("title", ""),
                "summary": result.get("summary", ""),
                "key_points": result.get("key_points", []),
                "raw_result": json.dumps(result),
            }))
        return await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.warning("Weaviate store failed (non-fatal): %s", exc)
        return None                # Never fail the tool call
```

Key design decisions:

1. **Non-fatal** -- store failures are logged as warnings, never propagated to the caller
2. **Non-blocking** -- runs in a thread via `asyncio.to_thread` since the Weaviate client is synchronous
3. **Guard check** -- `_is_enabled()` returns False if `WEAVIATE_URL` is not set
4. **Timestamp** -- `_now()` returns UTC datetime (Weaviate accepts datetime objects directly)

### Adding a store function for a new tool

1. Add the function to the appropriate module in `weaviate_store/` (or create one)
2. Map result fields to collection properties
3. Call it from your tool after computing the result

If your tool needs a new collection, define it in `weaviate_schema/` (see next section).

## Adding a New Collection

1. Define the collection in a module under `weaviate_schema/`:

```python
MY_DATA = CollectionDef(
    name="MyData",
    description="Results from my_tool",
    properties=_common_properties() + [
        PropertyDef("field_a", ["text"], "Description of field A"),
        PropertyDef("field_b", ["int"], "Description of field B",
                    skip_vectorization=True, index_range_filters=True),
        PropertyDef("raw_json", ["text"], "JSON blob",
                    skip_vectorization=True, index_searchable=False),
    ],
)
```

2. Add it to the `ALL_COLLECTIONS` list:

```python
ALL_COLLECTIONS: list[CollectionDef] = [
    # ... existing collections
    MY_DATA,
]
```

3. Add the collection name to `KnowledgeCollection` in `types.py`:

```python
KnowledgeCollection = Literal[
    "ResearchFindings", "VideoAnalyses", "ContentAnalyses",
    "VideoMetadata", "SessionTranscripts", "WebSearchResults", "ResearchPlans",
    "MyData",  # new
]
```

4. Write a store function in `weaviate_store/` (see pattern above).

5. The collection is created automatically on first server start (idempotent).

### Property configuration

- `data_type` -- Weaviate types: `["text"]`, `["text[]"]`, `["int"]`, `["number"]`, `["date"]`, `["boolean"]`
- `skip_vectorization=True` -- exclude from vector embedding (use for IDs, counts, JSON blobs)
- `index_range_filters=True` -- enable B-tree index for range queries (`>`, `<`, `between`) on int/number/date fields
- `index_searchable=False` -- disable BM25 keyword index on non-searchable text (JSON blobs, IDs, metadata)
- `index_filterable=True` (default) -- roaring-bitmap index for equality/contains filters

Guidelines:
- Properties that carry semantic meaning (titles, summaries, claims) should be vectorized (default) and BM25-searchable (default)
- Properties that are structural (UUIDs, timestamps, raw JSON) should skip vectorization and disable BM25
- Numeric/date fields used in range filters should set `index_range_filters=True`

## Weaviate Client Singleton

`WeaviateClient` in `weaviate_client.py` mirrors the `GeminiClient` pattern:

- **`get()`** -- returns (or creates) the shared client; thread-safe
- **`ensure_collections()`** -- idempotent schema creation on first connect
- **`is_available()`** -- checks if configured and reachable
- **`close()` / `aclose()`** -- cleanup (called in server lifespan shutdown)

Connection is automatic based on URL scheme:
- `http://localhost:*` -- connects via `weaviate.connect_to_local`
- `https://*.weaviate.network` -- connects via `weaviate.connect_to_weaviate_cloud`
- Other URLs -- connects via `weaviate.connect_to_custom`

All connections include `Timeout(init=30, query=60, insert=120)` for production reliability.

## Reference

- [Getting Started](./GETTING_STARTED.md) -- env var setup
- [Adding a New Tool](./ADDING_A_TOOL.md) -- integrating write-through in new tools
- [Writing Tests](./WRITING_TESTS.md) -- `mock_weaviate_client` fixture
- [Architecture Guide](../ARCHITECTURE.md) -- overall server design
- Source: `src/video_research_mcp/weaviate_schema/` -- collection definitions
- Source: `src/video_research_mcp/weaviate_store/` -- write-through functions
- Source: `src/video_research_mcp/weaviate_client.py` -- client singleton
- Source: `src/video_research_mcp/tools/knowledge/` -- query tools (7 tools across 4 modules)
