# Architecture Guide

Technical reference for the `video-research-mcp` codebase. Covers the system design, component interactions, and conventions that govern every module.

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Composite Server Pattern](#2-composite-server-pattern)
3. [GeminiClient Pipeline](#3-geminiclient-pipeline)
4. [Tool Conventions](#4-tool-conventions)
5. [Tool Reference (28 tools)](#5-tool-reference-28-tools)
6. [Singletons](#6-singletons)
7. [Weaviate Integration](#7-weaviate-integration)
8. [Session Management](#8-session-management)
9. [Caching](#9-caching)
10. [Configuration](#10-configuration)
11. [URL Validation](#11-url-validation)
12. [Error Handling](#12-error-handling)
13. [Prompt Templates](#13-prompt-templates)
14. [Tracing](#14-tracing)
15. [Knowledge Search Pipeline](#15-knowledge-search-pipeline)
16. [Companion Packages](#16-companion-packages)

---

## 1. System Overview

`video-research-mcp` is an MCP (Model Context Protocol) server that exposes 28 tools for video analysis, deep research, content extraction, web search, and knowledge management. It communicates over **stdio transport** using **FastMCP** (`fastmcp>=3.0.2`) and is powered by **Gemini 3.1 Pro** via the `google-genai` SDK.

### Core Dependencies

| Package | Purpose |
|---------|---------|
| `fastmcp>=3.0.2` | MCP server framework — v3.x preserves tool callability |
| `google-genai>=1.57` | Gemini API client — 1.56 added ThinkingConfig; 1.57 added Gemini 3 model support |
| `google-api-python-client>=2.100` | YouTube Data API v3 |
| `pydantic>=2.0` | Schema validation, structured output models |
| `weaviate-client>=4.19.2` | Vector database for knowledge persistence |
| `weaviate-agents>=1.2.0` | *(optional)* QueryAgent for AI-powered knowledge Q&A |

**Dev dependencies**: `pytest>=8.0`, `pytest-asyncio>=1.0`, `ruff>=0.9`

### Build & Runtime

- **Build backend**: hatchling
- **Python**: >= 3.11
- **Entry point**: `video-research-mcp` console script -> `server.py:main()`
- **Lint**: ruff (line-length=100, target py311)
- **Tests**: pytest with `asyncio_mode=auto`

### Source Layout

```
src/video_research_mcp/
  server.py              Root FastMCP app, mounts 7 sub-servers
  client.py              GeminiClient singleton (client pool)
  config.py              ServerConfig from env vars, runtime update
  context_cache.py       Context cache registry with disk persistence, prewarm tracking
  dotenv.py              Auto-loads ~/.config/video-research-mcp/.env
  sessions.py            In-memory SessionStore with TTL eviction
  persistence.py         SQLite-backed session persistence (WAL mode)
  cache.py               File-based JSON analysis cache
  errors.py              Structured error handling (ToolError, categorize_error)
  types.py               Shared Literal types + Annotated aliases
  youtube.py             YouTubeClient singleton (Data API v3)
  retry.py               Exponential backoff for transient Gemini errors
  tracing.py             Optional MLflow integration (@trace decorator, autolog)
  weaviate_client.py     WeaviateClient singleton
  weaviate_schema/       12 collection definitions (package, 6 modules)
    __init__.py          Re-exports ALL_COLLECTIONS + types
    base.py              CollectionDef, PropertyDef, ReferenceDef, _common_properties
    collections.py       7 core collections (Findings, Analyses, Metadata, etc.)
    community.py         CommunityReactions collection
    concepts.py          ConceptKnowledge, RelationshipEdges collections
    calls.py             CallNotes collection
    deep_research.py     DeepResearchReports collection
  weaviate_store/        Write-through store functions (package, 9 modules)
    __init__.py          Re-exports all store_* functions
    _base.py             Shared guard (_is_enabled) and helpers
    video.py             store_video_analysis, store_video_metadata
    research.py          store_research_finding, store_evidence_assessment, store_research_plan
    content.py           store_content_analysis
    session.py           store_session_turn
    search.py            store_web_search
    community.py         store_community_reaction
    concepts.py          store_concept_knowledge, store_relationship_edges
    calls.py             store_call_notes
    deep_research.py     store_deep_research, store_deep_research_followup
  models/
    video.py             VideoResult, SessionInfo, SessionResponse
    video_batch.py       BatchVideoItem, BatchVideoResult
    research.py          Finding, ResearchReport, ResearchPlan, EvidenceAssessment
    research_document.py DocumentSource, DocumentMap, DocumentFinding, CrossReferenceMap, DocumentResearchReport (+ 4 more)
    content.py           ContentResult
    content_batch.py     BatchContentItem, BatchContentResult
    youtube.py           VideoMetadata, PlaylistInfo
    knowledge.py         KnowledgeHit, KnowledgeSearchResult, HitSummary, HitSummaryBatch (+ 6 more)
  prompts/
    research.py          Deep research system prompt + phase templates
    research_document.py DOCUMENT_RESEARCH_SYSTEM + 4 phase prompts (map, evidence, cross-ref, synthesis)
    content.py           STRUCTURED_EXTRACT template
  tools/
    video.py             video_server (4 tools)
    video_batch.py       Batch video analysis tool (split from video.py)
    video_cache.py       Cache bridge helpers for video tools
    video_core.py        Shared analysis pipeline (cache + Gemini + cache save)
    video_url.py         YouTube URL validation + Content builder
    video_file.py        Local video file handling, File API upload
    youtube.py           youtube_server (3 tools)
    research.py          research_server (3 core tools + deferred registrations)
    research_document.py research_document tool + 4-phase orchestration (split from research.py)
    research_web.py      Deep Research Agent tools (`research_web*`)
    research_document_file.py Document File API upload + URL download helpers
    content.py           content_server (3 tools)
    content_batch.py     content_batch_analyze tool (split from content.py)
    search.py            search_server (1 tool)
    infra.py             infra_server (2 tools)
    knowledge_filters.py Collection-aware Weaviate filter builder
    knowledge/           knowledge_server (8 tools: search, retrieval, ingest, schema, QueryAgent)
      __init__.py        Server + tool imports
      search.py          knowledge_search with reranking + Flash summarization
      schema.py          knowledge_schema (offline collection property introspection)
      helpers.py         RERANK_PROPERTY mapping, ALLOWED_PROPERTIES, serialize
      summarize.py       Flash post-processor (HitSummary/HitSummaryBatch)
      agent.py           knowledge_ask, knowledge_query (QueryAgent)
      ingest.py          knowledge_ingest, knowledge_fetch, knowledge_stats
```

**Tool count**: 4 + 3 + 8 + 3 + 1 + 2 + 7 = **28 tools** across 7 sub-servers.

---

## 2. Composite Server Pattern

The server uses FastMCP's **mount** pattern to compose a root server from independent sub-servers. Each sub-server owns a domain and registers its own tools.

### Root Server (`server.py`)

```python
app = FastMCP("video-research", instructions="...", lifespan=_lifespan)

app.mount(video_server)       # tools/video.py       4 tools
_ensure_document_tool()       # deferred: research_document registers on research_server
_ensure_web_tools()           # deferred: research_web* registers on research_server
app.mount(research_server)    # tools/research.py     8 tools total
_ensure_batch_tool()          # deferred: content_batch_analyze registers on content_server
app.mount(content_server)     # tools/content.py      3 tools
app.mount(search_server)      # tools/search.py       1 tool
app.mount(infra_server)       # tools/infra.py        2 tools
app.mount(youtube_server)     # tools/youtube.py      3 tools
app.mount(knowledge_server)   # tools/knowledge/       8 tools
#                                                     ── 28 tools total
```

### Lifespan Hook

The `_lifespan` async context manager handles startup and graceful shutdown:

**Startup** (before `yield`):
1. **Tracing**: `tracing.setup()` configures MLflow tracking URI, experiment, and Gemini autologging (no-op when tracing is disabled)

**Shutdown** (after `yield`):
1. **Tracing**: `tracing.shutdown()` flushes pending async traces
2. **Context cache**: Conditionally cleared when `clear_cache_on_shutdown` is `True`
3. **Weaviate**: `WeaviateClient.aclose()` closes the cluster connection
4. **Gemini**: `GeminiClient.close_all()` tears down all pooled clients

```python
@asynccontextmanager
async def _lifespan(server: FastMCP):
    tracing.setup()
    yield {}
    tracing.shutdown()
    if get_config().clear_cache_on_shutdown:
        await context_cache.clear()
    await WeaviateClient.aclose()
    closed = await GeminiClient.close_all()
```

All singletons lazy-initialize on first use -- the startup phase only configures tracing.

### Sub-Server Independence

Each sub-server is a standalone `FastMCP` instance:

```python
# tools/research.py
research_server = FastMCP("research")

@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def research_deep(topic: TopicParam, ...) -> dict:
    ...
```

Sub-servers share singletons (`GeminiClient`, `get_config()`, `session_store`) via imports from the parent package. They never import from each other.

---

## 3. GeminiClient Pipeline

`GeminiClient` (`client.py`) is a process-wide client pool keyed by API key. It provides two generation entry points that all tools funnel through.

### Client Pool

```
GeminiClient._clients: dict[str, genai.Client]
```

`GeminiClient.get(api_key=None)` returns (or creates) a `genai.Client` for the given key. Default key comes from `get_config().gemini_api_key` or `GEMINI_API_KEY` env var.

### `generate()` -- Raw Text Output

```python
async def generate(
    contents,
    *,
    model=None,
    thinking_level=None,
    response_schema=None,   # dict -> response_json_schema
    temperature=None,
    system_instruction=None,
    tools=None,             # e.g. [GoogleSearch(), UrlContext()]
) -> str
```

Builds a `GenerateContentConfig` with:
- **ThinkingConfig**: resolved from param or config default
- **Temperature**: param or config default
- **response_json_schema**: set when `response_schema` dict is provided
- **system_instruction**: optional system prompt
- **tools**: Gemini tool wiring (GoogleSearch, UrlContext)

Calls `client.aio.models.generate_content()` wrapped in `with_retry()` for exponential backoff. Strips thinking parts from the response -- only returns user-visible text.

### `generate_structured()` -- Validated Pydantic Output

```python
async def generate_structured(
    contents,
    *,
    schema: type[BaseModel],
    ...
) -> BaseModel
```

Delegates to `generate()` with `response_schema=schema.model_json_schema()`, then validates via `schema.model_validate_json(raw)`. This is the primary output path for tools that use default schemas.

### Pipeline Flow

```
Tool function
  -> GeminiClient.generate_structured(contents, schema=VideoResult)
     -> GeminiClient.generate(contents, response_schema=VideoResult.model_json_schema())
        -> with_retry(client.aio.models.generate_content(...))
        -> strip thinking parts
        -> return raw text
     -> VideoResult.model_validate_json(raw)
     -> return validated Pydantic model
  -> model.model_dump() -> dict
```

For custom `output_schema` (caller-provided JSON Schema):
```
Tool function
  -> GeminiClient.generate(contents, response_schema=custom_dict)
     -> (same pipeline)
     -> return raw JSON text
  -> json.loads(raw) -> dict
```

### Retry Mechanism (`retry.py`)

`with_retry(coro_factory)` wraps any async callable with exponential backoff:

- **Retryable patterns**: `429`, `quota`, `resource_exhausted`, `timeout`, `503`, `service unavailable`
- **Backoff**: `base_delay * 2^attempt + jitter`, capped at `max_delay`
- **Config**: `retry_max_attempts` (default 3), `retry_base_delay` (1.0s), `retry_max_delay` (60s)
- **Non-retryable errors**: raised immediately

---

## 4. Tool Conventions

Every tool follows a strict set of conventions enforced across the codebase.

### Required Decorators

Every tool MUST have `ToolAnnotations`:

```python
@server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,      # Does not modify external state
        destructiveHint=False,   # Does not delete data
        idempotentHint=True,     # Same input -> same output
        openWorldHint=True,      # Accesses external APIs
    )
)
```

### Parameter Typing

Parameters use `Annotated` with `Field` constraints:

```python
async def my_tool(
    query: Annotated[str, Field(min_length=2, description="Search query")],
    limit: Annotated[int, Field(ge=1, le=100, description="Max results")] = 10,
    thinking_level: ThinkingLevel = "medium",
) -> dict:
```

Shared type aliases live in `types.py`:

| Alias | Type | Constraints |
|-------|------|-------------|
| `ThinkingLevel` | `Literal["minimal", "low", "medium", "high"]` | -- |
| `Scope` | `Literal["quick", "moderate", "deep", "comprehensive"]` | -- |
| `CacheAction` | `Literal["stats", "list", "clear"]` | -- |
| `ModelPreset` | `Literal["best", "stable", "budget"]` | -- |
| `KnowledgeCollection` | `Literal[7 collection names]` | -- |
| `YouTubeUrl` | `Annotated[str, ...]` | `min_length=10` |
| `TopicParam` | `Annotated[str, ...]` | `min_length=3, max_length=500` |
| `VideoFilePath` | `Annotated[str, ...]` | `min_length=1` |
| `VideoDirectoryPath` | `Annotated[str, ...]` | `min_length=1` |
| `PlaylistUrl` | `Annotated[str, ...]` | `min_length=10` |

### Instruction-Driven Design

Tools accept an `instruction` parameter (free text) instead of fixed modes. The LLM client writes the instruction, Gemini returns structured JSON:

```python
video_analyze(url="...", instruction="List all recipes and ingredients shown")
video_analyze(url="...", instruction="Extract every CLI command demonstrated")
content_analyze(url="https://arxiv.org/...", instruction="Extract the methodology section")
```

### Custom Output Schemas

Tools accept an optional `output_schema` dict (JSON Schema) for caller-defined response shapes. When provided, `generate()` is called with `response_schema=output_schema` instead of the default Pydantic model:

```python
video_analyze(
    url="...",
    instruction="List recipes",
    output_schema={"type": "object", "properties": {"recipes": {"type": "array"}}}
)
```

### Error Convention

Tools **never raise** -- they catch all exceptions and return a `make_tool_error()` dict:

```python
try:
    result = await GeminiClient.generate_structured(...)
    return result.model_dump()
except Exception as exc:
    return make_tool_error(exc)
```

### Docstrings

Every tool has a docstring with `Args:` and `Returns:` sections.

### Write-Through to Weaviate

When Weaviate is configured (`WEAVIATE_URL`), every result-producing tool automatically stores its output via a `store_*` function from `weaviate_store/`. This is the primary mechanism for building the knowledge base -- it requires no action from the MCP client.

**Pattern**: import the store function inside the tool, call after the result is ready:

```python
result = model_result.model_dump()
from ..weaviate_store import store_video_analysis
await store_video_analysis(result, content_id, instruction, source_label)
return result
```

**Tool-to-collection mapping**:

| Tool | Store Function | Collection |
|------|---------------|------------|
| `video_analyze` | `store_video_analysis` | `VideoAnalyses` |
| `video_batch_analyze` | `store_video_analysis` (per file) | `VideoAnalyses` |
| `video_continue_session` | `store_session_turn` | `SessionTranscripts` |
| `video_metadata` | `store_video_metadata` | `VideoMetadata` |
| `research_deep` | `store_research_finding` | `ResearchFindings` |
| `research_plan` | `store_research_plan` | `ResearchPlans` |
| `research_assess_evidence` | `store_evidence_assessment` | `ResearchFindings` |
| `research_document` | `store_research_finding` | `ResearchFindings` |
| `research_web_status` | `store_deep_research` | `DeepResearchReports` |
| `research_web_followup` | `store_deep_research_followup` | `DeepResearchReports` |
| `content_analyze` | `store_content_analysis` | `ContentAnalyses` |
| `content_batch_analyze` | `store_content_analysis` (per file) | `ContentAnalyses` |
| `web_search` | `store_web_search` | `WebSearchResults` |

Tools not in this table (`content_extract`, `video_comments`, `video_playlist`, `research_web` launch-only, `research_web_cancel`, `infra_cache`, `infra_configure`, and the knowledge tools) do not write through.

**Key guarantees**:
- **Non-fatal**: All store functions catch exceptions and log warnings. Tool results are never lost due to Weaviate failures.
- **Guard check**: `_is_enabled()` returns immediately when `weaviate_enabled` is `False`.
- **New tool convention**: When adding a tool that produces analytical results, add a corresponding `store_*` function to `weaviate_store/` and call it from the tool.

---

## 5. Tool Reference (28 tools)

### Video Server (4 tools)

**`video_analyze`** -- Analyze a video with any instruction.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `YouTubeUrl \| None` | `None` | YouTube URL (mutually exclusive with `file_path`) |
| `file_path` | `VideoFilePath \| None` | `None` | Local video path |
| `instruction` | `str` | comprehensive analysis | What to analyze |
| `output_schema` | `dict \| None` | `None` | Custom JSON Schema |
| `thinking_level` | `ThinkingLevel` | `"high"` | Gemini thinking depth |
| `use_cache` | `bool` | `True` | Use cached results |

Returns: `VideoResult` dict (or custom schema). Caches results. Writes to `VideoAnalyses` collection.

**`video_create_session`** -- Create a persistent session for multi-turn video exploration.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `YouTubeUrl \| None` | `None` | YouTube URL |
| `file_path` | `VideoFilePath \| None` | `None` | Local video path |
| `description` | `str` | `""` | Session purpose |

Returns: `SessionInfo` dict with `session_id`. Fetches video title via YouTube API or Gemini fallback.

**`video_continue_session`** -- Continue analysis within an existing session.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `session_id` | `str` | (required) | Session ID from `video_create_session` |
| `prompt` | `str` | (required) | Follow-up question |

Returns: `SessionResponse` dict with `response` and `turn_count`. Appends to session history. Writes to `SessionTranscripts`.

**`video_batch_analyze`** -- Analyze all video files in a directory concurrently.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `directory` | `VideoDirectoryPath` | (required) | Directory path |
| `instruction` | `str` | comprehensive analysis | What to analyze |
| `glob_pattern` | `str` | `"*"` | File filter glob |
| `output_schema` | `dict \| None` | `None` | Custom JSON Schema |
| `thinking_level` | `ThinkingLevel` | `"high"` | Gemini thinking depth |
| `max_files` | `int` | `20` | Max files (1-50) |

Returns: `BatchVideoResult` dict. Uses semaphore-bounded concurrency (3 parallel Gemini calls).

### YouTube Server (3 tools)

**`video_metadata`** -- Fetch YouTube video metadata without Gemini.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `YouTubeUrl` | (required) | YouTube URL |

Returns: `VideoMetadata` dict (title, stats, duration, tags, channel). Costs 1 YouTube API unit, 0 Gemini units. Writes to `VideoMetadata` collection with deterministic UUID.

**`video_comments`** -- Fetch top YouTube comments sorted by relevance.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `YouTubeUrl` | (required) | YouTube URL |
| `max_comments` | `int` | `200` | Max comments (1-500) |

Returns: dict with `video_id`, `comments` list (text, like count, author), and `count`. Costs 1+ YouTube API units, 0 Gemini units.

**`video_playlist`** -- Get video items from a YouTube playlist.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | `PlaylistUrl` | (required) | YouTube playlist URL |
| `max_items` | `int` | `20` | Max items (1-50) |

Returns: `PlaylistInfo` dict. Costs 1 YouTube API unit per page.

### Research Server (8 tools)

**`research_deep`** -- Run multi-phase deep research with evidence-tier labeling.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `topic` | `TopicParam` | (required) | Research question |
| `scope` | `Scope` | `"moderate"` | Research depth |
| `thinking_level` | `ThinkingLevel` | `"high"` | Gemini thinking depth |

Pipeline: Scope Definition (unstructured) -> Evidence Collection (structured, `FindingsContainer`) -> Synthesis (structured, `ResearchSynthesis`) -> `ResearchReport`.

Every claim is labeled: CONFIRMED, STRONG INDICATOR, INFERENCE, SPECULATION, or UNKNOWN. Writes findings to `ResearchFindings`.

**`research_plan`** -- Generate a multi-agent research orchestration plan.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `topic` | `TopicParam` | (required) | Research question |
| `scope` | `Scope` | `"moderate"` | Research depth |
| `available_agents` | `int` | `10` | Agent count (1-50) |

Returns: `ResearchPlan` dict with phases, task decomposition, model assignments. Does NOT spawn agents -- provides the blueprint. Falls back to unstructured generate on structured output failure. Writes to `ResearchPlans`.

**`research_assess_evidence`** -- Assess a claim against sources.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `claim` | `str` | (required) | Statement to verify |
| `sources` | `list[str]` | (required) | Evidence sources |
| `context` | `str` | `""` | Additional context |

Returns: `EvidenceAssessment` dict with tier, confidence (0-1), reasoning. Writes to `ResearchFindings`.

**`research_document`** -- Run multi-phase evidence-tiered research grounded in source documents.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instruction` | `str` | (required) | Research question |
| `file_paths` | `list[str] \| None` | `None` | Local PDF/document paths |
| `urls` | `list[str] \| None` | `None` | URLs to downloadable documents |
| `scope` | `Scope` | `"moderate"` | Research depth |
| `thinking_level` | `ThinkingLevel` | `"high"` | Gemini thinking depth |

4-phase pipeline: Document Mapping (`DocumentMap` per doc, parallel) → Evidence Extraction (`DocumentFindingsContainer` per doc, parallel) → Cross-Reference (`CrossReferenceMap`, all docs in one call) → Synthesis (`DocumentResearchReport`). Scope `quick` skips phases 2–4; phase 3 is skipped for single-document `moderate` scope.

Documents are always uploaded via File API (`research_document_file.py`) regardless of size — amortizes upload cost across all 3–4 Gemini calls. URL documents are downloaded to a temp dir first via `httpx`, then uploaded. Registration uses deferred import pattern (`_ensure_document_tool()` called from `server.py`) to avoid circular import. Writes to `ResearchFindings`.

**`research_web`** -- Launch Gemini Deep Research Agent in background mode.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `topic` | `str` | (required) | Detailed research brief |
| `output_format` | `str` | `""` | Optional report structure guidance |

Returns: launch envelope with `interaction_id`, `status`. Uses `DEEP_RESEARCH_AGENT`.

**`research_web_status`** -- Poll status or retrieve completed Deep Research result.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `interaction_id` | `str` | (required) | Interaction ID from `research_web` |

Returns: status while running; full report + sources + usage when completed. Writes completed reports to `DeepResearchReports`.

**`research_web_followup`** -- Ask follow-up questions on completed Deep Research reports.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `interaction_id` | `str` | (required) | Original Deep Research interaction ID |
| `question` | `str` | (required) | Follow-up question |

Returns: follow-up response with a new `interaction_id`. Appends Q&A to `DeepResearchReports`.

**`research_web_cancel`** -- Cancel an in-flight Deep Research interaction.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `interaction_id` | `str` | (required) | Interaction ID to cancel |

Returns: cancellation status response.

### Content Server (3 tools)

**`content_analyze`** -- Analyze content (file, URL, or text) with any instruction.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instruction` | `str` | comprehensive analysis | What to analyze |
| `file_path` | `str \| None` | `None` | Local file (PDF or text) |
| `url` | `str \| None` | `None` | URL to analyze |
| `text` | `str \| None` | `None` | Raw text content |
| `output_schema` | `dict \| None` | `None` | Custom JSON Schema |
| `thinking_level` | `ThinkingLevel` | `"medium"` | Gemini thinking depth |

Exactly one source required. URL path uses `UrlContext()` tool wiring with two-step fallback (fetch unstructured, then reshape). Writes to `ContentAnalyses`.

**`content_batch_analyze`** -- Batch-analyze multiple content files from a directory or file list.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `instruction` | `str` | comprehensive analysis | What to analyze |
| `directory` | `str \| None` | `None` | Directory to scan |
| `file_paths` | `list[str] \| None` | `None` | Explicit file list |
| `glob_pattern` | `str` | `"*"` | Filter within directory |
| `mode` | `"compare" \| "individual"` | `"compare"` | Analysis mode |
| `output_schema` | `dict \| None` | `None` | Custom JSON Schema |
| `thinking_level` | `ThinkingLevel` | `"high"` | Gemini thinking depth |
| `max_files` | `int` | `20` | File cap (1–50) |

Supports PDF, TXT, MD, HTML, XML, JSON, CSV. Two modes: `compare` sends all files as separate `Part` objects (with `"--- File: name ---"` label parts for disambiguation) in one `types.Content` → single Gemini call; `individual` processes each file via `asyncio.Semaphore(3)`. Registration uses deferred import pattern (`_ensure_batch_tool()` in `server.py`) to avoid circular import. Writes to `ContentAnalyses` per file.

**`content_extract`** -- Extract structured data using a JSON Schema.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | `str` | (required) | Source text |
| `schema` | `dict` | (required) | JSON Schema for extraction |

Returns: dict matching the provided schema. Uses `STRUCTURED_EXTRACT` prompt template.

### Search Server (1 tool)

**`web_search`** -- Search the web using Gemini's Google Search grounding.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | `str` | (required) | Search terms |
| `num_results` | `int` | `5` | Results count (1-20) |

Uses the flash model with `GoogleSearch()` tool wiring. Returns query, response text, and grounding sources (title + URL). Writes to `WebSearchResults`.

### Infra Server (2 tools)

**`infra_cache`** -- Manage the analysis cache.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `action` | `CacheAction` | `"stats"` | `"stats"`, `"list"`, or `"clear"` |
| `content_id` | `str \| None` | `None` | Scope clear to specific ID |

Returns depend on `action`:

| Action | Returns |
|--------|---------|
| `stats` | `{cache_dir, total_files, total_size_mb, ttl_days}` |
| `list` | `{entries: [{file, content_id, tool, cached_at}, ...]}` sorted by `cached_at` descending |
| `clear` | `{removed: int}` — number of files deleted (scoped to `content_id` if provided) |

**`infra_configure`** -- Reconfigure the server at runtime.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `preset` | `ModelPreset \| None` | `None` | `"best"`, `"stable"`, or `"budget"` |
| `model` | `str \| None` | `None` | Model ID override (takes precedence) |
| `thinking_level` | `ThinkingLevel \| None` | `None` | Thinking depth |
| `temperature` | `float \| None` | `None` | Sampling temp (0.0-2.0) |

Changes take effect immediately. Returns current config, active preset, and available presets.

### Knowledge Server (8 tools)

All knowledge tools gracefully degrade when Weaviate is not configured (return empty results, not errors). `knowledge_ask` requires the optional `weaviate-agents` package. `knowledge_query` is **deprecated** — use `knowledge_search` instead.

**`knowledge_search`** -- Search across knowledge collections (hybrid, semantic, or keyword).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | `str` | (required) | Search query |
| `collections` | `list[KnowledgeCollection] \| None` | `None` | Collections to search (all if omitted) |
| `search_type` | `"hybrid" \| "semantic" \| "keyword"` | `"hybrid"` | Search algorithm |
| `limit` | `int` | `10` | Max results per collection (1-100) |
| `alpha` | `float` | `0.5` | Hybrid balance: 0=BM25, 1=vector (hybrid mode only) |
| `evidence_tier` | `str \| None` | `None` | Filter ResearchFindings by evidence tier |
| `source_tool` | `str \| None` | `None` | Filter by originating tool name |
| `date_from` | `str \| None` | `None` | Filter `created_at >= ISO date` |
| `date_to` | `str \| None` | `None` | Filter `created_at <= ISO date` |
| `category` | `str \| None` | `None` | Filter VideoMetadata by category |
| `video_id` | `str \| None` | `None` | Filter by video_id |

Search types: `hybrid` fuses BM25 + vector scores; `semantic` uses `near_text` for pure vector similarity; `keyword` uses `bm25` for pure keyword matching. Filters are collection-aware -- conditions are silently skipped for collections that lack the relevant property (see `knowledge_filters.py`). When `COHERE_API_KEY` is set, results are reranked via Cohere (overfetch 3x, rerank, sort by rerank_score). When `FLASH_SUMMARIZE` is not `false`, Gemini Flash post-processes hits with relevance scoring, one-line summaries, and property trimming. Returns: `KnowledgeSearchResult` with merged, score-sorted results. See [Knowledge Search Pipeline](#15-knowledge-search-pipeline) for details.

**`knowledge_related`** -- Find semantically related objects via near-object vector search.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `object_id` | `str` | (required) | Source object UUID |
| `collection` | `KnowledgeCollection` | (required) | Source collection |
| `limit` | `int` | `5` | Max related results (1-50) |

Returns: `KnowledgeRelatedResult` with related hits sorted by distance.

**`knowledge_stats`** -- Get object counts per collection.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `collection` | `KnowledgeCollection \| None` | `None` | Single collection or all |

Returns: `KnowledgeStatsResult` with per-collection counts and total.

**`knowledge_ingest`** -- Manually insert data into a knowledge collection.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `collection` | `KnowledgeCollection` | (required) | Target collection |
| `properties` | `dict` | (required) | Object properties |

Validates properties against the collection schema -- unknown keys are rejected with allowed `name:type` pairs. Returns: `KnowledgeIngestResult` with object UUID.

**`knowledge_schema`** -- Return property schemas for knowledge collections (no Weaviate needed).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `collection` | `KnowledgeCollection \| None` | `None` | Single collection or all |

Reads from local `CollectionDef` objects -- no Weaviate connection required. Returns `{name, type, description}` per property. Call before `knowledge_ingest` to discover expected fields.

**`knowledge_fetch`** -- Retrieve a single object by UUID.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `object_id` | `str` | (required) | Weaviate object UUID |
| `collection` | `KnowledgeCollection` | (required) | Source collection |

Returns: `KnowledgeFetchResult` with `found` boolean and object `properties`.

**`knowledge_ask`** -- Ask a natural-language question and get an AI-generated answer with source citations.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | `str` | (required) | Natural-language question |
| `collections` | `list[KnowledgeCollection] \| None` | `None` | Collections to query (all if omitted) |

Requires the optional `weaviate-agents` package (`pip install video-research-mcp[agents]`). Uses Weaviate's QueryAgent to search across collections and synthesize an answer. Returns: `KnowledgeAskResult` with `answer` text and `sources` list (collection + object UUID per source). Returns a clear error hint when `weaviate-agents` is not installed.

**`knowledge_query`** -- **[Deprecated]** Retrieve objects using natural-language queries via QueryAgent. Use `knowledge_search` instead, which now includes Cohere reranking and Flash summarization.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | `str` | (required) | Natural-language search query |
| `collections` | `list[KnowledgeCollection] \| None` | `None` | Collections to search (all if omitted) |
| `limit` | `int` | `10` | Max results (1-100) |

Requires the optional `weaviate-agents` package. Returns: `KnowledgeQueryResult` with `_deprecated: true` flag.

**QueryAgent lifecycle**: The QueryAgent instance is lazily created on first call and cached as a module-level singleton, keyed by the frozenset of target collection names. If the collection set changes between calls, a new QueryAgent is created.

---

## 6. Singletons

Five singletons provide shared state across the server.

### GeminiClient (`client.py`)

**Pattern**: Class-level dict pool, one `genai.Client` per API key.

```python
GeminiClient._clients: dict[str, genai.Client]
```

- `get(api_key=None)` -- lazy-creates and caches clients
- `generate()` -- text output with thinking + optional structured schema
- `generate_structured()` -- validated Pydantic output
- `close_all()` -- tears down all clients (called at lifespan shutdown)

### ServerConfig (`config.py`)

**Pattern**: Module-level `_config` variable, lazy-initialized by `get_config()`.

- `get_config()` -- returns the singleton, creating from env vars on first call
- `update_config(**overrides)` -- patches the live config (used by `infra_configure`)
- Not thread-safe for writes, but acceptable for a single-process MCP server

### SessionStore (`sessions.py`)

**Pattern**: Module-level `session_store` singleton.

- In-memory `dict[str, VideoSession]` with optional SQLite backing
- TTL eviction on every `create()` and `get()` call
- Bounded history trimming (`session_max_turns * 2` items)
- LRU eviction when `max_sessions` is reached

### YouTubeClient (`youtube.py`)

**Pattern**: Class-level `_service` singleton (lazy via `get()`).

- Built with `googleapiclient.discovery.build("youtube", "v3", ...)`
- Uses `YOUTUBE_API_KEY` with fallback to `GEMINI_API_KEY`
- Sync API wrapped in `asyncio.to_thread()` for all methods
- `reset()` for testing

### WeaviateClient (`weaviate_client.py`)

**Pattern**: Module-level `_client` variable, thread-safe via `threading.Lock`.

- `get()` -- connects and ensures schema collections exist (idempotent)
- `is_available()` -- checks if configured and reachable
- `close()` / `aclose()` -- tears down the connection
- `reset()` -- clears singleton state for testing
- Supports WCS cloud, local instances, and custom deployments via URL detection

---

## 7. Weaviate Integration

The knowledge layer uses Weaviate as a vector database for persistent, searchable storage of all tool outputs.

### Architecture

```
Tool produces result
  -> weaviate_store.store_*()     # write-through (non-fatal)
     -> WeaviateClient.get()      # lazy connect + schema ensure
        -> weaviate_schema/       # 12 collection definitions
     -> collection.data.insert()  # async via to_thread
```

### Client (`weaviate_client.py`)

`WeaviateClient.get()` auto-detects the deployment type from the URL:

| URL Pattern | Connection Method |
|-------------|-------------------|
| `http://localhost:*`, `http://127.0.0.1:*` | `connect_to_local(host, port, grpc_port=port+1)` |
| `https://*.weaviate.network` | `connect_to_weaviate_cloud(url, auth)` |
| Other | `connect_to_custom(host, port, grpc_host, grpc_port)` |

All connection paths include `AdditionalConfig(timeout=Timeout(init=30, query=60, insert=120))` for production reliability.

On first connection, `ensure_collections()` iterates all 12 `CollectionDef` objects and creates any that don't exist using the v4 `Property()` API (not `create_from_dict`). Existing collections are evolved by adding missing properties via `_evolve_collection()`.

### Schema (`weaviate_schema/` package)

The schema package contains 6 modules: `base.py` (types), `collections.py` (7 core collections), `community.py`, `concepts.py`, `calls.py`, and `deep_research.py`. The `__init__.py` re-exports `ALL_COLLECTIONS` and all types so existing imports remain stable.

Twelve collections, each defined as a `CollectionDef` dataclass:

| Collection | Source Tool(s) | Vectorized Fields |
|------------|---------------|-------------------|
| `ResearchFindings` | `research_deep`, `research_assess_evidence` | topic, claim, reasoning, executive_summary |
| `VideoAnalyses` | `video_analyze`, `video_batch_analyze` | instruction, title, summary, key_points |
| `ContentAnalyses` | `content_analyze` | instruction, title, summary, key_points, entities |
| `VideoMetadata` | `video_metadata` | title, description, tags |
| `SessionTranscripts` | `video_continue_session` | video_title, turn_prompt, turn_response |
| `WebSearchResults` | `web_search` | query, response |
| `ResearchPlans` | `research_plan` | topic, task_decomposition |
| `DeepResearchReports` | `research_web_status`, `research_web_followup` | topic, report_text |
| `CommunityReactions` | comment analysis agent | video_id, sentiment, themes |
| `ConceptKnowledge` | concept extraction | name, description, domain |
| `RelationshipEdges` | relationship mapping | source, target, relationship_type |
| `CallNotes` | call/meeting analysis | title, summary, action_items |

Every collection includes common properties:
- `created_at` (date, skip vectorization, range-indexed)
- `source_tool` (text, skip vectorization, BM25-disabled)

`PropertyDef` supports three index configuration fields:
- `index_filterable` (default `True`) -- roaring-bitmap index for equality/contains filters
- `index_range_filters` (default `False`) -- B-tree index for `>`, `<`, `>=`, `<=`, `between` on int/number/date fields
- `index_searchable` (default `None` = Weaviate default) -- inverted index for BM25 keyword search; set to `False` on JSON blobs, IDs, and metadata text fields

Fields marked `skip_vectorization=True` are stored but not included in the vector embedding (IDs, timestamps, raw JSON blobs).

### Write-Through Store (`weaviate_store/` package)

The store package contains 9 domain modules plus a shared `_base.py` with the `_is_enabled()` guard and helpers. The `__init__.py` re-exports all 14 `store_*` functions so existing imports like `from .weaviate_store import store_video_analysis` keep working.

One async function per collection, all following the same pattern:

```python
async def store_video_analysis(result, content_id, instruction, source_url=""):
    if not _is_enabled():
        return None
    try:
        def _insert():
            client = WeaviateClient.get()
            collection = client.collections.get("VideoAnalyses")
            return str(collection.data.insert(properties={...}))
        return await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.warning("Weaviate store failed (non-fatal): %s", exc)
        return None
```

Key design decisions:
- **Non-fatal**: All store functions catch exceptions and log warnings. Tool results are never lost due to Weaviate failures.
- **Guard function**: `_is_enabled()` checks `get_config().weaviate_enabled` before any Weaviate call.
- **Thread offloading**: Weaviate's sync client is wrapped in `asyncio.to_thread()` to avoid blocking the event loop.
- **Deterministic UUIDs**: `store_video_metadata` uses `weaviate.util.generate_uuid5(video_id)` for deduplication -- repeated metadata fetches for the same video update rather than duplicate.

### Knowledge Tools (`tools/knowledge/`)

Seven tools provide read/write/query access to the knowledge store:
- `knowledge_search` -- search across collections (hybrid, semantic, or keyword mode)
- `knowledge_related` -- near-object vector search for semantic similarity
- `knowledge_stats` -- object counts per collection with optional group_by
- `knowledge_ingest` -- manual insert with property validation
- `knowledge_fetch` -- retrieve a single object by UUID
- `knowledge_ask` -- AI-generated answer with source citations (requires `weaviate-agents`)
- `knowledge_query` -- natural-language object retrieval via QueryAgent (requires `weaviate-agents`)

`knowledge_search` supports three search modes via the `search_type` parameter:
- `"hybrid"` (default) -- fuses BM25 keyword + vector similarity via `collection.query.hybrid()`
- `"semantic"` -- pure vector similarity via `collection.query.near_text()`
- `"keyword"` -- pure BM25 keyword matching via `collection.query.bm25()`

`knowledge_search` also has two optional post-processing stages (Cohere reranking and Flash summarization) described in [Knowledge Search Pipeline](#15-knowledge-search-pipeline).

`knowledge_ask` and `knowledge_query` use the Weaviate `QueryAgent` from the optional `weaviate-agents` package. The QueryAgent translates natural-language queries into optimized Weaviate operations and can synthesize answers from multiple collections. The agent instance is lazily created and cached by collection set.

All tools gracefully degrade when `weaviate_enabled` is `False` (return empty result models, not errors). The QueryAgent tools additionally return an error hint when `weaviate-agents` is not installed.

### Unified Recall Architecture

`/gr:recall` bridges two storage layers:

| Layer | Storage | Search Method | Unique Data |
|-------|---------|---------------|-------------|
| Filesystem | `~/.claude/projects/*/memory/gr/` | Glob + Grep (exact) | Knowledge states, visualizations, full markdown |
| Weaviate | 12 collections | Hybrid/semantic/keyword | Cross-collection search, AI Q&A, similarity |

Availability detection: `knowledge_stats()` at command start. Returns immediately when Weaviate is not configured (no network call). If unavailable, pure filesystem mode.

Category-to-collection mapping:

| Filesystem dir | Weaviate collections |
|---------------|---------------------|
| `gr/research/` | ResearchFindings, ResearchPlans |
| `gr/video/` | VideoAnalyses, VideoMetadata |
| `gr/video-chat/` | SessionTranscripts |
| `gr/analysis/` | ContentAnalyses |
| (none) | WebSearchResults |

Results from `/gr:` commands exist in both layers (filesystem via memory save, Weaviate via write-through). Results from direct MCP tool calls exist only in Weaviate. Recall surfaces both.

---

## 8. Session Management

Sessions enable multi-turn video conversations where the model retains context across prompts.

### In-Memory Store (`sessions.py`)

`SessionStore` holds a `dict[str, VideoSession]`:

```python
@dataclass
class VideoSession:
    session_id: str           # 12-char hex UUID prefix
    url: str                  # YouTube URL or File API URI
    mode: str                 # always "general"
    video_title: str
    history: list[Content]    # Gemini Content objects (user + model pairs)
    created_at: datetime
    last_active: datetime
    turn_count: int
```

### Lifecycle

1. **Create**: `video_create_session` -> `session_store.create(url, mode, title)`
   - Evicts expired sessions (TTL = `session_timeout_hours`)
   - If at `max_sessions`, evicts the least-recently-active session
   - Returns a 12-char hex session ID

2. **Continue**: `video_continue_session` -> `session_store.get(id)` + `add_turn()`
   - Rebuilds the full conversation: `session.history + [new_user_content]`
   - Sends to Gemini with the complete history
   - Appends both user and model content to history
   - Trims history to `session_max_turns * 2` items (sliding window)

3. **Expiry**: Sessions expire after `session_timeout_hours` of inactivity (checked on every `create()` and `get()` call)

### SQLite Persistence (`persistence.py`)

When `GEMINI_SESSION_DB` is set, `SessionStore` delegates to `SessionDB`:

- **WAL mode**: `PRAGMA journal_mode=WAL` for concurrent reads and fast writes
- **Synchronous NORMAL**: trades durability for speed (appropriate for session data)
- **Write-through**: every `create()` and `add_turn()` immediately saves to SQLite
- **Read-through**: `get()` checks memory first, falls back to SQLite, and caches in memory

Content serialization:
- `_content_to_dict()` converts `genai.Content` -> JSON-safe dict (handles `text`, `file_data`, `thought` parts)
- `_dict_to_content()` deserializes back to `genai.Content`

### Local Video Sessions

When a session is created with a local video file:
1. The file is uploaded to Gemini's File API (regardless of size)
2. The returned `file_uri` becomes the session's URL
3. All subsequent turns reference this URI

This ensures the file is available for multi-turn replay without re-uploading.

---

## 9. Caching

Three cache layers work together, each at a different level of the stack:

| Layer | Module | Scope | Storage | TTL | Purpose |
|-------|--------|-------|---------|-----|---------|
| **Analysis cache** | `cache.py` | Tool output (JSON) | Local filesystem | 30 days (file mtime) | Avoid re-analyzing identical content+instruction pairs |
| **Context cache** | `context_cache.py` | Uploaded video content | Gemini API (server-side) | 1 hour (API-managed) | Avoid re-uploading video for multi-tool workflows |
| **Cache bridge** | `tools/video_cache.py` | Orchestration glue | -- | -- | Connects analysis → context cache for video tools |

**Typical flow**: `video_analyze` checks the analysis cache first. On miss, it calls Gemini, saves the result, and fires a context cache prewarm. A subsequent `video_create_session` for the same video reuses the pre-warmed context cache via `ensure_session_cache()`, skipping re-upload. This works for both YouTube (via download + File API upload) and local files (File API URI from upload). Small local files (<20MB) use inline bytes and skip caching.

### Analysis Cache (`cache.py`)

The file-based JSON cache stores tool results on disk to avoid redundant Gemini API calls.

### Key Structure

```
{content_id}_{tool_name}_{instruction_hash}_{model_hash}.json
```

- **content_id**: YouTube video ID or file SHA-256 prefix
- **tool_name**: e.g. `video_analyze`
- **instruction_hash**: MD5 of instruction text (8 hex chars), or `"default"`
- **model_hash**: MD5 of model ID (8 hex chars)

The instruction hash differentiates results for the same content analyzed with different instructions.

### Cache Directory

Default: `~/.cache/video-research-mcp/`. Configurable via `GEMINI_CACHE_DIR`.

### Operations

| Function | Description |
|----------|-------------|
| `load()` | Return cached dict or `None` if miss/expired |
| `save()` | Write analysis dict wrapped in metadata envelope |
| `clear()` | Remove cache files (all or by content_id) |
| `stats()` | Return file count, total size, TTL |
| `list_entries()` | List all cached entries with metadata |

### Envelope Format

```json
{
  "cached_at": "2026-02-27T10:30:00",
  "content_id": "dQw4w9WgXcQ",
  "tool": "video_analyze",
  "model": "gemini-3.1-pro-preview",
  "analysis": { ... }
}
```

### TTL

Cache files are checked by modification time. Files older than `cache_ttl_days` (default 30) are treated as misses. No background cleanup -- expired files are only detected on `load()`.

### Integration with Tools

Only `video_analyze` and `video_batch_analyze` use the cache (via `video_core.py`):

```python
# Check cache
cached = cache_load(content_id, "video_analyze", cfg.default_model, instruction=instruction)
if cached:
    cached["cached"] = True
    return cached

# ... Gemini call ...

# Save to cache
cache_save(content_id, "video_analyze", cfg.default_model, result, instruction=instruction)
```

Cached results include a `"cached": True` flag so callers can distinguish cache hits.

### Context Cache (`context_cache.py`)

Gemini's context caching lets the server reuse uploaded video content across multiple tool calls without re-uploading. The `context_cache` module manages a registry of cached content and handles background prewarming.

**Registry**: `_registry` maps `(content_id, model)` tuples to cache name strings. The registry is persisted to a JSON file on disk so cache references survive server restarts.

**Prewarm**: `start_prewarm()` fires a background task that uploads content to the Gemini cache. `lookup_or_await()` checks the registry and, if a prewarm is in progress, waits with a timeout for it to complete.

**Token suppression**: The `_suppressed` set tracks `(content_id, model)` pairs where caching failed (e.g., video too short to benefit). Once suppressed, the module skips further cache attempts for that pair.

**TTL**: Gemini context caches expire naturally (default 1 hour). No manual cleanup is needed during normal operation. The `clear_cache_on_shutdown` config flag (default `False`) triggers `context_cache.clear()` during the lifespan shutdown hook.

### Cache Bridge (`tools/video_cache.py`)

Thin orchestration layer that wires the context cache into video tool workflows. Four helpers:

| Function | Called by | What it does |
|----------|-----------|--------------|
| `prewarm_cache()` | `video_analyze` (after successful analysis) | Fires `context_cache.start_prewarm()` with a `file_data` Part. Skips YouTube URLs (can't be cached); works for File API URIs from local file uploads |
| `ensure_session_cache()` | `video_create_session` (local files + YouTube download) | Looks up pre-warmed cache, or creates one on-demand. Returns `(cache_name, model, reason)` |
| `resolve_session_cache()` | `ensure_session_cache` (fast path) | Calls `context_cache.lookup_or_await()` to find a pre-warmed cache |
| `prepare_cached_request()` | `video_continue_session` | Checks cache liveness via `refresh_ttl()`, builds request contents accordingly |

When a cache is alive, `prepare_cached_request()` sends only the text prompt (no video re-upload). When it expires, the function falls back to re-attaching the video `file_data` Part.

---

## 10. Configuration

### ServerConfig (`config.py`)

All configuration is resolved from environment variables via `ServerConfig.from_env()`:

| Env Variable | Field | Default | Validation |
|-------------|-------|---------|------------|
| `GEMINI_API_KEY` | `gemini_api_key` | `""` (required at runtime) | -- |
| `GEMINI_MODEL` | `default_model` | `gemini-3.1-pro-preview` | -- |
| `GEMINI_FLASH_MODEL` | `flash_model` | `gemini-3-flash-preview` | -- |
| `DEEP_RESEARCH_AGENT` | `deep_research_agent` | `deep-research-pro-preview-12-2025` | Must not be empty |
| `GEMINI_THINKING_LEVEL` | `default_thinking_level` | `high` | Must be in `{minimal, low, medium, high}` |
| `GEMINI_TEMPERATURE` | `default_temperature` | `1.0` | -- |
| `GEMINI_CACHE_DIR` | `cache_dir` | `~/.cache/video-research-mcp/` | -- |
| `GEMINI_CACHE_TTL_DAYS` | `cache_ttl_days` | `30` | >= 1 |
| `GEMINI_MAX_SESSIONS` | `max_sessions` | `50` | >= 1 |
| `GEMINI_SESSION_TIMEOUT_HOURS` | `session_timeout_hours` | `2` | >= 1 |
| `GEMINI_SESSION_MAX_TURNS` | `session_max_turns` | `24` | >= 1 |
| `GEMINI_RETRY_MAX_ATTEMPTS` | `retry_max_attempts` | `3` | >= 1 |
| `GEMINI_RETRY_BASE_DELAY` | `retry_base_delay` | `1.0` | > 0 |
| `GEMINI_RETRY_MAX_DELAY` | `retry_max_delay` | `60.0` | > 0 |
| `YOUTUBE_API_KEY` | `youtube_api_key` | `""` | Falls back to `GEMINI_API_KEY` |
| `GEMINI_SESSION_DB` | `session_db_path` | `""` | Empty = in-memory only |
| `WEAVIATE_URL` | `weaviate_url` | `""` | -- |
| `WEAVIATE_API_KEY` | `weaviate_api_key` | `""` | -- |
| `CLEAR_CACHE_ON_SHUTDOWN` | `clear_cache_on_shutdown` | `False` | Clear context caches on server shutdown |
| `COHERE_API_KEY` | *(drives `reranker_enabled`)* | `""` | Enables Cohere reranking in `knowledge_search` |
| `RERANKER_ENABLED` | `reranker_enabled` | derived | `True` when Cohere key is set and not explicitly `false` |
| `RERANKER_PROVIDER` | `reranker_provider` | `cohere` | Reranker backend (currently only `cohere`) |
| `FLASH_SUMMARIZE` | `flash_summarize` | `True` | Enable Gemini Flash post-processing of search hits |
| `GEMINI_TRACING_ENABLED` | `tracing_enabled` | derived | Enabled when `MLFLOW_TRACKING_URI` is set and flag is not `false` |
| `MLFLOW_TRACKING_URI` | `mlflow_tracking_uri` | `""` | MLflow store URI. Empty = tracing disabled |
| `MLFLOW_EXPERIMENT_NAME` | `mlflow_experiment_name` | `video-research-mcp` | MLflow experiment name |
| -- | `weaviate_enabled` | derived | `True` if `WEAVIATE_URL` is set |

### Model Presets

Three presets are available via `infra_configure`:

| Preset | Default Model | Flash Model | Description |
|--------|---------------|-------------|-------------|
| `best` | `gemini-3.1-pro-preview` | `gemini-3-flash-preview` | Max quality (lowest rate limits) |
| `stable` | `gemini-3-pro-preview` | `gemini-3-flash-preview` | Fallback (higher rate limits) |
| `budget` | `gemini-3-flash-preview` | `gemini-3-flash-preview` | Cost-optimized (highest rate limits) |

### Runtime Updates

`update_config(**overrides)` patches the live singleton:

```python
cfg = get_config()                    # current config
data = cfg.model_dump()               # to dict
data.update({k: v for k, v in overrides.items() if v is not None})
_config = ServerConfig(**data)        # re-validate via Pydantic
```

Changes take effect immediately for all subsequent tool calls. The API key is excluded from `infra_configure` output for security.

---

## 11. URL Validation

YouTube URL validation (`tools/video_url.py`) prevents spoofed domains and extracts video IDs from all legitimate YouTube URL formats.

### Host Validation

```python
def _is_youtube_host(host: str) -> bool:
    # Matches: youtube.com, www.youtube.com, m.youtube.com, music.youtube.com
    return host == "youtube.com" or host.endswith(".youtube.com")

def _is_youtu_be_host(host: str) -> bool:
    # Matches: youtu.be, www.youtu.be
    return host == "youtu.be" or host == "www.youtu.be"
```

Host matching is case-insensitive and strips port numbers.

### Supported URL Formats

| Format | Example |
|--------|---------|
| Standard watch | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` |
| Short link | `https://youtu.be/dQw4w9WgXcQ` |
| Shorts | `https://www.youtube.com/shorts/dQw4w9WgXcQ` |
| Embed | `https://www.youtube.com/embed/dQw4w9WgXcQ` |
| Live | `https://www.youtube.com/live/dQw4w9WgXcQ` |
| Mobile | `https://m.youtube.com/watch?v=dQw4w9WgXcQ` |
| Music | `https://music.youtube.com/watch?v=dQw4w9WgXcQ` |
| With playlist | `https://www.youtube.com/watch?v=xxx&list=PLxxx` |

### Normalization

All URLs are normalized to `https://www.youtube.com/watch?v=VIDEO_ID`:
- Backslashes are stripped
- Video ID is extracted and cleaned of query parameters
- Invalid or non-YouTube URLs raise `ValueError`

### Spoofing Prevention

The host check uses exact matching and `.endswith()` rather than substring matching. This prevents attacks like:
- `https://not-youtube.com/watch?v=xxx` (rejected -- not a youtube.com domain)
- `https://youtube.com.evil.com/watch?v=xxx` (rejected -- `evil.com` doesn't end with `.youtube.com`)

### Local Video Validation (`tools/video_file.py`)

Local files are validated for:
- **Existence**: `Path.exists()`
- **File type**: `Path.is_file()`
- **Extension**: Must be in `SUPPORTED_VIDEO_EXTENSIONS` (mp4, webm, mov, avi, mkv, mpeg, wmv, 3gpp)

Files under 20 MB use inline `Part.from_bytes()`. Larger files are uploaded via the Gemini File API with polling until ACTIVE state.

---

## 12. Error Handling

### ToolError Model (`errors.py`)

All tool errors return a consistent Pydantic model:

```python
class ToolError(BaseModel):
    error: str                        # Exception message
    category: str                     # ErrorCategory enum value
    hint: str                         # Human-readable recovery hint
    retryable: bool = False           # Whether the caller should retry
    retry_after_seconds: int | None   # Suggested wait (quota errors only)
```

### Error Categories

| Category | Trigger Pattern | Retryable |
|----------|----------------|-----------|
| `URL_INVALID` | URL parsing failures | No |
| `URL_PARSE_FAILED` | URL extraction failures | No |
| `API_PERMISSION_DENIED` | 403 + "permission" | No |
| `API_QUOTA_EXCEEDED` | 429, "quota", "resource_exhausted" | Yes (60s) |
| `API_INVALID_ARGUMENT` | 400 errors, invalid params | No |
| `API_NOT_FOUND` | 404 errors | No |
| `VIDEO_RESTRICTED` | 403 (non-permission) | No |
| `VIDEO_PRIVATE` | "private" in message | No |
| `VIDEO_UNAVAILABLE` | "unavailable" in message | No |
| `NETWORK_ERROR` | "timeout", "timed out" | Yes |
| `FILE_NOT_FOUND` | `FileNotFoundError` | No |
| `FILE_UNSUPPORTED` | "unsupported video extension" | No |
| `FILE_TOO_LARGE` | -- | No |
| `WEAVIATE_CONNECTION` | "weaviate" + connect patterns | Yes |
| `WEAVIATE_SCHEMA` | "weaviate" + schema patterns | No |
| `WEAVIATE_QUERY` | "weaviate" (generic) | No |
| `WEAVIATE_IMPORT` | "weaviate" + import patterns | No |
| `UNKNOWN` | Everything else | No |

### Categorization

`categorize_error(exc)` maps exceptions to `(ErrorCategory, hint)` by pattern-matching the exception message string. It checks patterns in priority order (most specific first).

### Tool Integration

```python
def make_tool_error(error: Exception) -> dict:
    cat, hint = categorize_error(error)
    retryable = cat in {API_QUOTA_EXCEEDED, NETWORK_ERROR, WEAVIATE_CONNECTION}
    return ToolError(
        error=str(error),
        category=cat.value,
        hint=hint,
        retryable=retryable,
        retry_after_seconds=60 if cat == API_QUOTA_EXCEEDED else None,
    ).model_dump()
```

Convention: Tools **never raise**. Every exception path returns `make_tool_error(exc)`.

---

## 13. Prompt Templates

### Research Prompts (`prompts/research.py`)

**System prompt** (`DEEP_RESEARCH_SYSTEM`): Sets the non-sycophantic analyst persona. Requires evidence-tier labeling on all claims.

**Phase templates** (all use `.format()` interpolation):

| Template | Variables | Purpose |
|----------|-----------|---------|
| `SCOPE_DEFINITION` | `{topic}`, `{scope}` | Define research scope, stakeholders, constraints |
| `EVIDENCE_COLLECTION` | `{topic}`, `{context}` | Extract findings with evidence tiers |
| `SYNTHESIS` | `{topic}`, `{findings_text}` | Synthesize findings into executive summary |
| `RESEARCH_PLAN` | `{topic}`, `{scope}`, `{available_agents}` | Generate phased execution plan |
| `EVIDENCE_ASSESSMENT` | `{claim}`, `{sources_text}`, `{context}` | Assess claim against sources |

### Content Prompts (`prompts/content.py`)

**`STRUCTURED_EXTRACT`**: Template for `content_extract` tool. Interpolates `{content}` and `{schema_description}` to produce a JSON extraction prompt.

### Video Prompts

The video analysis preamble lives in `tools/video_core.py` (not in `prompts/`):

```python
_ANALYSIS_PREAMBLE = (
    "Analyze this video thoroughly. For timestamps, use PRECISE times from the "
    "actual video (not rounded estimates). Extract AT LEAST 5-10 key points. ..."
)
```

This is prepended to the user's instruction for default-schema video analysis.

---

## 14. Tracing

Optional MLflow integration that instruments Gemini calls and MCP tool entrypoints without affecting server functionality when `mlflow-tracing` is not installed.

### Two Instrumentation Layers

| Layer | Mechanism | Span Type | What It Captures |
|-------|-----------|-----------|------------------|
| **Autolog** | `mlflow.gemini.autolog()` | `CHAT_MODEL` | Every `generate_content` call via the google-genai SDK |
| **Tool spans** | `@trace(name="...", span_type="TOOL")` decorator | `TOOL` | MCP tool entrypoint, parents the autolog child spans |

### Graceful Degradation

`tracing.py` uses a guarded import pattern:

```python
try:
    import mlflow
    import mlflow.gemini
    _HAS_MLFLOW = True
except ImportError:
    _HAS_MLFLOW = False
```

`is_enabled()` returns `False` when either:
- `mlflow-tracing` is not installed (`_HAS_MLFLOW` is `False`)
- `tracing_enabled` is `False` in the config (derived from env vars)

The `@trace` decorator becomes an identity function when tracing is off -- zero overhead, no conditional logic at call sites.

### Configuration

Tracing enablement follows a three-variable hierarchy:

| Variable | Effect |
|----------|--------|
| `MLFLOW_TRACKING_URI` | Where to store traces. Empty = tracing disabled regardless of other flags |
| `GEMINI_TRACING_ENABLED=false` | Force-disable even when `MLFLOW_TRACKING_URI` is set |
| `GEMINI_TRACING_ENABLED=true` (or empty) | Enabled when `MLFLOW_TRACKING_URI` is non-empty |
| `MLFLOW_EXPERIMENT_NAME` | Experiment name (default `video-research-mcp`) |

### Lifecycle

1. **Startup**: `tracing.setup()` in the lifespan hook calls `mlflow.set_tracking_uri()`, `mlflow.set_experiment()`, and `mlflow.gemini.autolog()`. Failures are logged and swallowed -- tracing must never prevent the server from starting.
2. **Runtime**: `@trace` decorators on tool functions create TOOL spans that parent autolog child spans.
3. **Shutdown**: `tracing.shutdown()` calls `mlflow.flush_trace_async_logging()` to flush pending traces.

### Usage Pattern

```python
from .tracing import trace

@knowledge_server.tool(annotations=ToolAnnotations(readOnlyHint=True, ...))
@trace(name="knowledge_search", span_type="TOOL")
async def knowledge_search(...) -> dict:
    ...
```

The `@trace` decorator sits between the FastMCP `@tool` decorator and the function body. When tracing is disabled, it is a no-op passthrough.

---

## 15. Knowledge Search Pipeline

`knowledge_search` has evolved from a simple Weaviate query into a multi-stage pipeline with three optional post-processing layers: collection-aware filtering, Cohere reranking, and Gemini Flash summarization.

### Pipeline Flow

```
knowledge_search(query, collections, filters...)
  1. Build collection-aware filters (knowledge_filters.py)
  2. For each collection:
     a. Dispatch Weaviate query (hybrid/semantic/keyword)
     b. If reranker_enabled: overfetch 3x, pass rerank config
  3. Merge + sort results (rerank_score > base score)
  4. If flash_summarize: Flash post-processing (summarize.py)
  5. Return KnowledgeSearchResult
```

### Collection-Aware Filters (`tools/knowledge_filters.py`)

`build_collection_filter()` constructs a Weaviate `Filter` from optional query parameters, but only includes conditions for properties that actually exist in the target collection. This prevents errors when filtering across heterogeneous collections (e.g., `evidence_tier` only exists in `ResearchFindings`).

```python
# Skip evidence_tier filter for collections that don't have that property
if evidence_tier and "evidence_tier" in allowed_properties:
    conditions.append(Filter.by_property("evidence_tier").equal(evidence_tier))
```

Multiple conditions are combined via `Filter.all_of()` (AND logic). Date strings are parsed to UTC datetimes. The function returns `None` when no conditions apply, which Weaviate interprets as "no filter".

### Cohere Reranking (`tools/knowledge/helpers.py`)

When `COHERE_API_KEY` is set (and `RERANKER_ENABLED` is not `false`), search results are reranked using Cohere's reranking model via Weaviate's native `Rerank` module.

**Overfetch pattern**: The search fetches `limit * 3` results from Weaviate, then reranks and trims to the requested `limit`. This ensures the reranker has enough candidates to surface the most relevant results.

**RERANK_PROPERTY mapping**: Each collection has a designated text property for reranking -- the field that best represents the object's semantic content:

| Collection | Rerank Property |
|------------|----------------|
| `ResearchFindings` | `claim` |
| `VideoAnalyses` | `summary` |
| `ContentAnalyses` | `summary` |
| `VideoMetadata` | `description` |
| `SessionTranscripts` | `turn_response` |
| `WebSearchResults` | `response` |
| `ResearchPlans` | `topic` |
| `CommunityReactions` | `consensus` |
| `ConceptKnowledge` | `description` |
| `RelationshipEdges` | `relationship_type` |
| `CallNotes` | `summary` |

Results are sorted by `(rerank_score, base_score)` descending, so reranked results always float to the top.

### Flash Summarization (`tools/knowledge/summarize.py`)

When `FLASH_SUMMARIZE` is not `false` (default: enabled), Gemini Flash post-processes search results to reduce token consumption when results are sent to the MCP client's context window.

**Models**: `HitSummary` (per-hit) and `HitSummaryBatch` (batch response) in `models/knowledge.py`.

**Pipeline**:
1. Build a prompt with truncated hit properties (max 500 chars per property, max 20 hits)
2. Call `GeminiClient.generate_structured()` with the Flash model and `thinking_level="minimal"`
3. Merge summaries back into hits: replace `properties` with only `useful_properties`, add `summary` field

**Best-effort**: If Flash fails (timeout, quota, parsing error), the original raw hits are returned unchanged. This ensures search always succeeds even when the Flash call fails.

**Key fields on KnowledgeHit**:
- `rerank_score: float | None` -- Cohere reranker score (null when reranking is off)
- `summary: str | None` -- Flash-generated one-line relevance summary (null when Flash is off)

**Flags on KnowledgeSearchResult**:
- `reranked: bool` -- Whether Cohere reranking was applied
- `flash_processed: bool` -- Whether Flash summarization was applied

---

## 16. Companion Packages

The `packages/` directory contains two standalone MCP servers that extend the core `video-research-mcp` server with specialized capabilities. Each is an independent Python package with its own `pyproject.toml`, `src/` layout, tests, and `.venv`.

### `video-agent-mcp` -- Parallel Scene Generation

An MCP server that uses the Claude Agent SDK to run multiple scene generation prompts concurrently, reducing wall-clock time for the video explainer pipeline.

**Architecture**: Single sub-server (`scenes_server`) mounted onto a root `FastMCP("video-agent")`.

**Core module** (`sdk_runner.py`):
- `run_agent_query()` -- Executes a single Claude Agent SDK query with timeout handling
- `run_parallel_queries()` -- Bounded concurrent execution via `asyncio.Semaphore`

**CLAUDECODE env guard**: Before spawning nested Claude instances, `run_parallel_queries()` clears the `CLAUDECODE` environment variable to prevent recursive agent loops. The original value is restored in a `finally` block.

**Concurrency model**: `asyncio.Semaphore(concurrency)` bounds the number of parallel agent queries. Default concurrency is set via `config.agent_concurrency`.

### `video-explainer-mcp` -- Video Explainer Pipeline

An MCP server that wraps the `video_explainer` CLI for pipeline orchestration -- creating, generating, and rendering explainer videos from research content.

**Architecture**: Four sub-servers mounted onto a root `FastMCP("video-explainer")`:

| Sub-server | Purpose |
|------------|---------|
| `project_server` | Project creation, listing, status inspection |
| `pipeline_server` | Pipeline step execution (script, narration, scenes, voiceover, storyboard) |
| `quality_server` | Quality assessment and validation |
| `audio_server` | Audio/voiceover operations |

**CLI wrapping** (`runner.py`): All pipeline operations delegate to `run_cli()`, which uses `asyncio.create_subprocess_exec()` with an argument list (never `shell=True`) to prevent command injection. On timeout, the process receives SIGTERM, waits 5 seconds for graceful shutdown, then SIGKILL.

**Project scanner** (`scanner.py`): Reads filesystem state to determine pipeline step completion without making CLI calls. Each step has a detection rule (directory existence + expected output file).

**Job state machine** (`jobs.py`): In-memory `RenderJob` registry tracks background render operations through `PENDING -> RUNNING -> COMPLETED | FAILED` lifecycle states. Jobs are identified by 12-char hex UUIDs.
