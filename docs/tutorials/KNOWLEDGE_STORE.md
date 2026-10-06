# Knowledge Store

The optional knowledge store saves selected research and analysis results to
Weaviate so you can retrieve them across sessions. Start with `knowledge_schema`
to inspect the available fields, then use `knowledge_search` to retrieve objects
or `knowledge_ask` to request an answer with references to stored objects.

Storage is best-effort. A successful analysis does not prove that its result was
saved, and a stored claim does not become verified evidence by being searchable.
Use `knowledge_fetch` to inspect the original properties behind a search hit or
answer citation.

## What It Is

Setting `WEAVIATE_URL` enables the store. Tools with write-through integration
await a storage attempt before returning their result; a storage exception is
logged and does not fail the main tool call. The synchronous Weaviate operations
run in worker threads, so they do not block the event loop, but their elapsed time
can still add to the tool's response time.

Without a configured URL, store functions skip writes. Knowledge tools behave as
follows:

| Tool | Response when storage is disabled |
| --- | --- |
| `knowledge_schema` | Local schema definitions, with no connection required |
| `knowledge_search` | Empty `results` and `total_results: 0` |
| `knowledge_related` | Empty `related` list |
| `knowledge_stats` | Empty `collections` and `total_objects: 0` |
| `knowledge_fetch`, `knowledge_ingest` | `Weaviate not configured` error and setup hint |
| `knowledge_ask`, `knowledge_query` | Setup error; if the optional agents package is absent, its installation error takes precedence |

Disabling storage does not disable all additional model work. Video, content,
and research paths call the graph extractor after their primary result. The
extractor can make a further Gemini request even when Weaviate is disabled;
only its subsequent storage functions check the enabled flag.

## Architecture

| Source | Responsibility |
| --- | --- |
| [weaviate_client.py](../../src/video_research_mcp/weaviate_client.py) | Lazy sync/async connections, schema creation and evolution, shutdown |
| [weaviate_schema/](../../src/video_research_mcp/weaviate_schema/) | The 13 collection definitions, property types, indexes and references |
| [weaviate_store/](../../src/video_research_mcp/weaviate_store/) | Result-to-property mappings and non-fatal storage attempts |
| [tools/knowledge/](../../src/video_research_mcp/tools/knowledge/) | Eight tools for schema inspection, ingestion, retrieval and questions |
| [weaviate_migrate.py](../../src/video_research_mcp/weaviate_migrate.py) | Vectorizer configuration and opt-in collection migration |

`knowledge_schema` reads the repository's definitions, not the live cluster's
schema. The first synchronous connection creates missing collections, adds
missing properties to existing ones, configures optional reranking and adds
reference definitions. The async connection used by QueryAgent does not itself
bootstrap collections; run `knowledge_stats` first on a new deployment.

## Setup

Choose a vectorizer that your cluster supports. The MCP accepts `openai`,
`weaviate` and `ollama`. If `WEAVIATE_VECTORIZER` is unset, environment loading
selects `openai` when `OPENAI_API_KEY` is present and `weaviate` otherwise.
Set the variable explicitly to make deployment behavior predictable.
The client forwards configured embedding/reranker provider credentials as
headers to the chosen Weaviate host; use the intended cluster URL.

### Option A: Local Weaviate (Docker)

This example uses the OpenAI vectorizer and the documentation's pinned Weaviate
image. It requires an OpenAI key in the MCP server's environment; embedding
requests may incur provider charges. The September modernization tests did not
validate this Docker deployment or provider access.

Create `docker-compose.yml`:

```yaml
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.37.4
    ports:
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:50051:50051"
    volumes:
      - weaviate_data:/var/lib/weaviate
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      PERSISTENCE_DATA_PATH: /var/lib/weaviate
      DEFAULT_VECTORIZER_MODULE: text2vec-openai
      ENABLE_MODULES: text2vec-openai

volumes:
  weaviate_data:
```

Start the service, then configure the MCP process:

```bash
docker compose up -d
export WEAVIATE_URL="http://localhost:8080"
export WEAVIATE_VECTORIZER="openai"
# Supply OPENAI_API_KEY through your environment or secret manager.
```

The local example permits anonymous access on loopback ports. A shared deployment
needs its own authentication and network policy.

For an existing Ollama-backed deployment, select `WEAVIATE_VECTORIZER=ollama`.
The runtime defaults are `WEAVIATE_OLLAMA_API_ENDPOINT=http://host.docker.internal:11434`
and `WEAVIATE_OLLAMA_MODEL=nomic-embed-text`; the cluster must have the
`text2vec-ollama` module and be able to reach that endpoint.

### Option B: Weaviate Cloud (WCS)

Create a cluster through [Weaviate Cloud](https://console.weaviate.cloud), then
configure its URL, authentication and supported vectorizer:

```bash
export WEAVIATE_URL="https://your-cluster.weaviate.network"
export WEAVIATE_VECTORIZER="weaviate"
# Supply WEAVIATE_API_KEY through your environment or secret manager.
```

The `weaviate` setting selects `text2vec-weaviate`; it assumes that the cluster
provides that embedding service. Cluster setup, entitlement and billing remain
provider concerns. This setting does not guarantee that a local Docker image
provides a keyless embedding service.

### Verify Connection

Restart the MCP process after changing its environment. Call `knowledge_stats`
to exercise the synchronous connection and collection bootstrap. Connection
logs identify the cluster and newly created collections, for example:

```text
INFO: Connected to Weaviate at http://localhost:8080
INFO: Created Weaviate collection: ResearchFindings
```

Counts alone cannot distinguish an empty collection from a failed count request:
`knowledge_stats` logs a per-collection failure and reports zero for that
collection. To verify persistence, ingest a test record and fetch the returned
UUID. Remove or retain that record according to your cluster's data policy;
the knowledge MCP does not expose a delete tool.

## The 13 Collections

Every collection defines `created_at` and `updated_at` as dates and `source_tool`
as text. Automatic store functions populate the fields specified by their
mapping; manual ingestion inserts only the properties you supply.

The guide below identifies the content each collection holds. For the complete
current property names, types and descriptions, call:

```json
{}
```

with `knowledge_schema`, or pass a collection name to inspect one schema:

```json
{"collection": "ResearchFindings"}
```

### ResearchFindings

Research reports and individual findings from `research_deep`,
`research_document` and `research_assess_evidence`. Useful fields include
`topic`, `scope`, `claim`, `evidence_tier`, `reasoning`, `executive_summary`,
`confidence`, `open_questions`, `supporting` and `contradicting`. Reports can
link their findings through `report_uuid` and `belongs_to_report`.
The research models describe tiers as `CONFIRMED`, `STRONG INDICATOR`,
`INFERENCE`, `SPECULATION` and `UNKNOWN`. These labels and confidence values
are stored assessments, not independent checks.

### VideoAnalyses

Analyses from `video_analyze` and its batch path. Fields include `video_id`,
`source_url`, `instruction`, `title`, `summary`, `key_points`, `raw_result`,
`timestamps_json`, `topics`, `sentiment`, `local_filepath` and `screenshot_dir`.
When a content ID exists, the store derives a UUID from that ID and an instruction
hash so repeat analyses upsert. `has_metadata` can reference `VideoMetadata`.

### ContentAnalyses

Analyses from `content_analyze` and its batch path. Fields include `source`,
`instruction`, `title`, `summary`, `key_points`, `entities`, `raw_result`,
`structure_notes`, `quality_assessment` and `local_filepath`.

### VideoMetadata

YouTube metadata from `video_metadata`: title, description, channel, tags,
published date, duration, counts, category, caption availability and language.
Use `channel_title`, not `channel`. Its deterministic UUID derives from
`video_id`, allowing repeat fetches to upsert.

### SessionTranscripts

Conversation turns from `video_continue_session`, with `session_id`,
`video_title`, `turn_index`, `turn_prompt`, `turn_response` and `local_filepath`.
These records supplement the session store; they do not replace its runtime
conversation state.

### WebSearchResults

`web_search` output: `query`, `response` and `sources_json`. The source list is
stored as a JSON string.

### ResearchPlans

Plans from `research_plan`: `topic`, `scope`, `task_decomposition`, `phases_json`
and `recommended_models_json`. A stored plan describes proposed work, not
completed research.

### DeepResearchReports

Completed reports collected by `research_web_status`, and follow-up Q&A from
`research_web_followup`. Fields include `interaction_id`, `topic`, `report_text`,
`sources_json`, `source_count`, `status`, `duration_seconds`, `usage_json`,
`follow_up_ids` and `follow_ups_json`. The schema also defines references to
research findings and web searches.

### CommunityReactions

Aggregated comment analyses supplied by the comment-analysis workflow or manual
ingestion. Fields include `video_id`, `video_title`, `comment_count`, three
sentiment percentages, `themes_positive`, `themes_critical`, `consensus` and
`notable_opinions_json`. These records describe the sampled comments, not the
whole audience. The schema defines a `for_video` reference to metadata.

### ConceptKnowledge

Extracted concepts with `concept_name`, `state` (`know`, `fuzzy` or `unknown`),
`source_url`, `source_title`, `source_category`, `description` and `timestamp`.
The state is the extraction workflow's label.

### RelationshipEdges

Directed concept relationships: `from_concept`, `to_concept`,
`relationship_type`, `source_url` and `source_category`. Documented relationship
labels are `enables`, `example_of`, `builds_on`, `contradicts` and `related_to`.

### CallNotes

Meeting or call notes supplied by the relevant workflow or manual ingestion:
`video_id`, `source_url`, `title`, `summary`, `participants`, `decisions`,
`action_items`, `topics_discussed`, `duration`, `meeting_date` and `local_filepath`.
A collection definition does not make every video analysis create call notes.

### AcademicPapers

Semantic Scholar paper metadata from the paper search, detail, citation and
recommendation tools. Fields include `paper_id`, `title`, `abstract`,
`authors_json`, `year`, `venue`, `citation_count`, `fields_of_study`, `doi`,
`arxiv_id`, `tldr`, `is_open_access`, `open_access_pdf_url` and `url`.
The store upserts by a UUID derived from `paper_id` when it is available.

## Using the Knowledge Tools

Examples below are tool argument objects to pass through your MCP client.

### knowledge_schema -- collection property introspection

Call this before manual ingestion. It returns:

```json
{
  "schemas": {
    "ResearchFindings": [
      {"name": "claim", "type": "text", "description": "Individual finding or claim"}
    ]
  },
  "total_collections": 1
}
```

This abbreviated example omits the collection's other fields. Schema types
include `text`, `text[]`, `int`, `number`, `boolean` and `date`; JSON fields such
as `sources_json` are text containing serialized JSON.

### knowledge_ingest -- manual data entry

The following synthetic record illustrates the schema; it makes no research claim:

```json
{
  "collection": "ResearchFindings",
  "properties": {
    "topic": "Documentation example",
    "claim": "Illustrative entry; no finding has been verified.",
    "evidence_tier": "UNKNOWN",
    "confidence": 0.0,
    "supporting": [],
    "source_tool": "knowledge_ingest",
    "created_at": "2026-09-29T00:00:00Z"
  }
}
```

The tool rejects unknown keys before insertion, showing allowed `name:type`
pairs and a hint to call `knowledge_schema`. It does not locally validate every
value's type or fill timestamps and provenance for you; Weaviate handles value
acceptance. A successful response contains `status: "success"`, the collection
and an `object_id`. Each manual call inserts a new object; repeating it can
create duplicates.

### knowledge_fetch -- retrieve object by UUID

Pass the `object_id` from ingestion, search or an answer citation together with
its collection. The response contains `found: true` and full properties, or
`found: false` when the object does not exist. This is the way to recover fields
trimmed from a summarized search hit.

### knowledge_search -- search across collections

```json
{
  "query": "transformer architecture",
  "collections": ["ResearchFindings", "VideoAnalyses"],
  "search_type": "hybrid",
  "limit": 10,
  "alpha": 0.5
}
```

| Parameter | Behavior |
| --- | --- |
| `query` | Required nonempty text |
| `collections` | Omit to search all 13 collections |
| `search_type` | `hybrid` by default; also `semantic` or `keyword` |
| `limit` | Maximum total returned hits after merging collections; default 10, range 1–100 |
| `alpha` | Hybrid balance from 0 for keyword to 1 for vector; default 0.5 |
| `evidence_tier`, `source_tool` | Equality filters on those properties where present |
| `date_from`, `date_to` | Inclusive ISO date/time bounds on `created_at` |
| `category`, `video_id` | Equality filters where the collection has those properties |

Hybrid search calls Weaviate's BM25/vector fusion; semantic search uses
`near_text`; keyword search uses BM25. Filters are collection-aware: a filter
is skipped for a collection that lacks its property. Restrict `collections`
when a condition must apply to every hit. Invalid date strings are ignored by
the filter builder, so supply valid ISO values. `filters_applied` records the
requested non-null values, not proof that each condition applied to each hit.

The tool sorts the merged hits by available reranker score, then base score,
and truncates to `limit`. A semantic base score is `1 - distance`; other modes
use Weaviate's score. These scores describe retrieval ranking, not factual
confidence. Per-collection query failures are logged and skipped, so an empty
or partial result is not proof that the cluster contains no matching objects.

Each hit includes `collection`, `object_id`, `score`, optional `rerank_score`,
optional `summary` and `properties`. The response reports `total_results`,
`filters_applied`, `reranked` and `flash_processed` alongside the query and hits.

### knowledge_related -- find similar objects

Pass `object_id`, `collection` and optionally `limit` (default 5, range 1–50).
The tool uses near-object vector search in that collection and excludes the
source UUID from the returned `related` list.

### knowledge_stats -- object counts

Omit `collection` to count all collections, or select one. `group_by` optionally
counts values of a text property such as `evidence_tier` or `source_tool`; it is
skipped where the property does not exist. The response provides per-collection
counts and `total_objects`. Check logs when interpreting zero counts.

### knowledge_ask -- AI-generated answers (QueryAgent)

```json
{
  "query": "What findings about transformer architectures are stored?",
  "collections": ["ResearchFindings"]
}
```

Enable the `agents` extra in the environment that launches the MCP server.
The npm installer registers a version-pinned core runtime in an isolated `uvx`
environment; installing the extra in a separate environment does not add it to
that server. The example below pins the version declared by this source checkout.

For a new Claude Code user-scope registration, use:

```bash
claude mcp add --scope user video-research -- uvx 'video-research-mcp[agents]==0.8.0rc3'
```

If the server is already registered, edit its existing launch arguments instead
of adding a second entry. The research launch should contain:

```json
{
  "command": "uvx",
  "args": ["video-research-mcp[agents]==0.8.0rc3"]
}
```

Preserve the entry's environment and other settings. User-scope registration
lives in `~/.claude.json`; the npm installer's project registration uses
`.mcp.json`. Restart the MCP client after changing the launch. The current
installer updates an entry only when its recorded ownership hash still matches;
it preserves customized entries. Recheck the pinned version and enabled extras
when upgrading a customized launch. Keep any existing tracing extra if needed.

For a source checkout, run from its root:

```bash
uv sync --locked --extra dev --extra agents
uv run --locked --extra agents video-research-mcp
```

Include `--extra agents` in a registered `uv run` launch as well, so its environment
synchronization retains the dependency. See
[Connecting a source checkout](./GETTING_STARTED.md#a-source-checkout) for the
registration pattern.

`knowledge_ask` calls Weaviate's AsyncQueryAgent and returns an `answer` plus
`sources`, each containing a collection name and object UUID. Omit `collections`
to use all 13. The agent is created lazily, cached by target collections and
recreated when the async client changes.

This is a provider-backed answer request, not just object retrieval. Inspect
cited objects with `knowledge_fetch`; a stored-object citation is not necessarily
a direct citation to the primary document behind its contents. Empty answers or
source lists are possible.

### knowledge_query -- DEPRECATED

Use `knowledge_search` for new retrieval workflows. `knowledge_query` remains
available through AsyncQueryAgent's search mode and requires the agents extra.
Successful responses include `_deprecated: true` and `_deprecation_notice`;
error responses do not necessarily include those fields. No removal date is
specified in the implementation.

### How knowledge_search compares to knowledge_ask

| Reader need | Tool |
| --- | --- |
| Select a search mode, filters and a returned-hit limit | `knowledge_search` |
| Inspect ranked objects, then fetch their full properties | `knowledge_search` + `knowledge_fetch` |
| Request a synthesized answer with stored-object references | `knowledge_ask` |
| Avoid Gemini summaries during retrieval | `knowledge_search` with `FLASH_SUMMARIZE=false` in the server environment |

## Cohere Reranking

Set `COHERE_API_KEY` to auto-enable reranking, or set `RERANKER_ENABLED=false`
to disable it even when the key is present. `RERANKER_ENABLED=true` enables
configuration but does not supply credentials; the cluster still needs the
Cohere module and valid key. `RERANKER_PROVIDER` defaults to `cohere`, and the
implemented backend is Cohere.

For collections with a mapping in
[helpers.py](../../src/video_research_mcp/tools/knowledge/helpers.py), the search
requests `limit * 3` candidates per collection and asks Weaviate to rerank them.
The mapping selects representative fields such as a finding's `claim` or a
video analysis's `summary`. It currently covers 11 collections;
`DeepResearchReports` and `AcademicPapers` have no mapping and use base ranking.

`reranked: true` indicates that at least one collection query used a rerank
configuration. Check each hit's `rerank_score` to see whether it has a score.
This option sends text through Weaviate to Cohere and may incur provider charges.

## Flash Summarization

Search summarization is enabled by default. Set `FLASH_SUMMARIZE=false` in the
server environment to disable the Gemini post-processing request.

The summarizer sends up to 100 returned hits to the configured
`GEMINI_FLASH_MODEL` at low thinking depth, truncating each input property's
string representation to 300 characters. It requests relevance assessments,
one-line summaries and useful property names. The application uses the summary
and property selection; it does not use the generated relevance number to
reorder the hits or replace their base scores.

Matched hits receive a summary and trimmed properties. If no selected property
matches, all original properties remain. Unmatched hits pass through. On an
exception, the original hits are returned and a warning is logged.
`flash_processed` is true when at least one returned hit has a summary, rather
than merely because the option is enabled. Fetch the UUID for complete evidence.

## Write-Through Store Pattern

Automatic writes cover these result-producing paths; infrastructure, extraction
and other tools are not blanket-persisted.

| Tool path | Store function | Collection |
| --- | --- | --- |
| `video_analyze`, `video_batch_analyze` | `store_video_analysis` per analyzed result | VideoAnalyses |
| `video_continue_session` | `store_session_turn` | SessionTranscripts |
| `video_metadata` | `store_video_metadata` | VideoMetadata |
| `content_analyze`, `content_batch_analyze` | `store_content_analysis` per analyzed result | ContentAnalyses |
| `research_deep`, `research_document` | `store_research_finding` | ResearchFindings |
| `research_assess_evidence` | `store_evidence_assessment` | ResearchFindings |
| `research_plan` | `store_research_plan` | ResearchPlans |
| `research_web_status` on completion | `store_deep_research` | DeepResearchReports |
| `research_web_followup` | `store_deep_research_followup` | DeepResearchReports |
| `web_search` | `store_web_search` | WebSearchResults |
| Paper search/detail/citation/recommendation tools | Academic paper store functions | AcademicPapers |

Several analysis/research paths also extract concepts and relationships into
`ConceptKnowledge` and `RelationshipEdges`. Other collections have store helpers
or support manual ingestion; their presence does not imply an automatic write
from every MCP tool. Some reused store helpers label `source_tool` with their
original tool name, so that field alone does not identify the complete call path.

### The pattern

A result-producing tool calls its store helper after computing the result:

```python
from ..weaviate_store import store_video_analysis

await store_video_analysis(result, content_id, instruction, source_url)
```

The helper checks whether storage is enabled, maps fields to properties and
runs the synchronous operation with `await asyncio.to_thread(...)`. It returns
a UUID (or collection-specific result) on success and `None` on failure or when
disabled. Failures are logged as non-fatal warnings. For an implementation
example, read [video.py](../../src/video_research_mcp/weaviate_store/video.py).

### Adding a store function for a new tool

Add the helper in `weaviate_store/`, map fields to the target schema and call it
from the owning tool after generation. Test disabled behavior, successful writes
and failure handling with the existing mocks. See
[Adding a New Tool](./ADDING_A_TOOL.md) and [Writing Tests](./WRITING_TESTS.md).

## Adding a New Collection

Define a `CollectionDef` in `weaviate_schema/` and add it to `ALL_COLLECTIONS`.
Add its name to `KnowledgeCollection` in `types.py`, implement the storage mapping
and decide whether it needs a `RERANK_PROPERTY` entry. For example:

```python
MY_DATA = CollectionDef(
    name="MyData",
    description="Results from my_tool",
    properties=_common_properties() + [
        PropertyDef("summary", ["text"], "Analysis summary"),
        PropertyDef(
            "item_count", ["int"], "Number of items",
            skip_vectorization=True, index_range_filters=True,
        ),
    ],
)
```

The next synchronous connection creates a missing collection. Existing
collections receive missing properties; this is not a general schema migration.

### Property configuration

Vectorize meaningful text such as titles, summaries and claims. Set
`skip_vectorization=True` for structural fields and
`index_searchable=False` for text that should not enter the BM25 index, such as
raw JSON and IDs. Equality filters use `index_filterable` (default true);
numeric/date range queries need `index_range_filters=True`.

Changing vectorized source properties or the vectorizer can require rebuilding
a collection. `WEAVIATE_AUTO_MIGRATE` defaults to false, leaving a warning for a
mismatch. When explicitly enabled, the migration exports objects and references,
deletes and recreates the collection, then attempts to restore them. This is a
destructive operation with logged partial-failure paths, so back up the cluster
and inspect the result. It is not an atomic rollback mechanism.

## Weaviate Client Singleton

`get()` creates or returns the shared synchronous client under a thread lock;
`aget()` manages the async client for QueryAgent. `ensure_collections()` creates
and evolves schemas through the sync client. `is_available()` checks configuration
and readiness but can also initialize that client and schema.
`close()` closes the sync connection; `aclose()` closes both at server shutdown.

The sync connector selects local connection helpers for loopback or `192.168.*`
hosts, the cloud helper for other HTTPS URLs and a custom helper for remaining
URLs. The async connector uses the local helper for local hosts and the cloud
helper otherwise; custom non-cloud deployments therefore need separate
compatibility verification before using QueryAgent. Timeouts are 30 seconds for
initialization, 60 for queries and 120 for inserts.

## Reference

- [Getting Started](./GETTING_STARTED.md): server environment and startup
- [Adding a New Tool](./ADDING_A_TOOL.md): tool and storage integration
- [Writing Tests](./WRITING_TESTS.md): mocked Weaviate fixtures
- [Architecture Guide](../ARCHITECTURE.md): server structure
- [Ingest UX findings](../KNOWLEDGE_INGEST_UX_FINDINGS.md): the dated session that motivated schema discovery
