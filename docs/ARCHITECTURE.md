# Architecture Guide

The research server turns video, documents, text, web queries, and academic
metadata into tool results. Tool modules own the workflow; shared clients own
provider access; caches, sessions, and Weaviate each own a different kind of
state. This guide explains those boundaries so contributors can choose the
right place for a change.

The [tool manifest](metrics/tool-contract-manifest.json) records a dated schema
snapshot. Use current app discovery or a fresh export for exact names, parameters,
defaults, and annotations. Use [Getting Started](tutorials/GETTING_STARTED.md)
to run the server, [Adding a Tool](tutorials/ADDING_A_TOOL.md) to extend it, and
[Writing Tests](tutorials/WRITING_TESTS.md) to verify a change without live APIs.
The [diagrams](DIAGRAMS.md) show the main flows visually.

## 1. System Overview

The root package is a Python MCP server built with FastMCP. Its console entry
point, `video-research-mcp`, calls `server.main()`, which starts the mounted app
with the default stdio transport. Python requirements, dependency ranges, and
extras live in [pyproject.toml](../pyproject.toml); exact resolved versions live
in [uv.lock](../uv.lock).

| Boundary | Implementation | Purpose |
| --- | --- | --- |
| MCP transport and schemas | FastMCP | Registers and mounts tool functions |
| Gemini generation | `google-genai` | GenerateContent, uploads, context caches, and Interactions |
| YouTube metadata | `google-api-python-client` | YouTube Data API v3 |
| Academic metadata | `httpx` through `SemanticScholarClient` | Semantic Scholar APIs |
| Result validation | Pydantic; optional `jsonschema` | Validates the output paths that request it |
| Knowledge storage | `weaviate-client` | Stores and retrieves derived results |
| Optional integrations | `tracing`, `agents`, `strict` extras | MLflow, Weaviate QueryAgent, JSON Schema validation |

Start source exploration with these files:

| Area | Source entry point |
| --- | --- |
| Mounting and process lifecycle | [server.py](../src/video_research_mcp/server.py) |
| Model access and output validation | [client.py](../src/video_research_mcp/client.py) |
| Runtime settings | [config.py](../src/video_research_mcp/config.py), [dotenv.py](../src/video_research_mcp/dotenv.py) |
| Tool workflows | [tools/](../src/video_research_mcp/tools/) |
| Output models and prompts | [models/](../src/video_research_mcp/models/), [prompts/](../src/video_research_mcp/prompts/) |
| Result cache | [cache.py](../src/video_research_mcp/cache.py) |
| Provider context cache | [context_cache.py](../src/video_research_mcp/context_cache.py), [video_cache.py](../src/video_research_mcp/tools/video_cache.py) |
| Conversation state | [sessions.py](../src/video_research_mcp/sessions.py), [persistence.py](../src/video_research_mcp/persistence.py) |
| Knowledge storage | [weaviate_client.py](../src/video_research_mcp/weaviate_client.py), [weaviate_schema/](../src/video_research_mcp/weaviate_schema/), [weaviate_store/](../src/video_research_mcp/weaviate_store/) |
| Input policies | [url_policy.py](../src/video_research_mcp/url_policy.py), [local_path_policy.py](../src/video_research_mcp/local_path_policy.py) |
| Strict video artifacts | [contract/](../src/video_research_mcp/contract/) |

## 2. Composite Server Pattern

`server.py` mounts domain servers without a namespace prefix. Tool names
such as `video_analyze` are therefore the names exposed by the root app.

| Workflow family | Owning modules under `tools/` |
| --- | --- |
| Video analysis and sessions | `video.py`, `video_batch.py`, `video_windows.py` |
| Research and source ingestion | `research.py`, `research_document.py`, `research_web.py`, `academic.py`, `research_execute.py`, `ingestion.py` |
| Content, search, and provider adapters | `content.py`, `content_batch.py`, `search.py`, `search_provider.py`, `text_provider.py`, `twelvelabs.py` |
| Configuration and knowledge | `infra.py`, `knowledge/` |
| YouTube metadata and channels | `youtube.py`, `youtube_channels.py` |
| Media preparation and inspection | `media.py`, `media_read.py`, `media_assets.py`, `image.py`, `media_scenes.py`, `footage_edit.py` |
| Vision and audiovisual perception | `vision.py`, `segmentation.py`, `media_perceive.py`, `video_evidence.py` |
| Audio and dubbing | `audio_dsp.py`, `audio_transcribe.py`, `audio_speakers.py`, `video_dubbing.py` |
| Durable jobs and memory | `jobs.py`, `video_memory_av.py`, `video_memory_lifecycle.py`, `session_memory.py` |
| Research workspaces and outputs | `corpus.py`, `collections.py`, `wiki.py`, `audience.py`, `evidence_export.py`, `notebooks.py`, `synthesis.py`, `corrections.py`, `grounding.py`, `video_note.py` |
| Live workflows and hardware | `live.py`, `hardware.py` |

This table groups responsibilities; `server.py` is the exact mount inventory.
Optional provider and native routes have their own configuration and runtime
requirements. Registration does not establish that those routes are available.

Research and content use deferred registration helpers before mounting. These
helpers import modules that register tools on the already-created domain
server, avoiding a circular import during initialization. Video batch registration
uses an import at the end of `tools/video.py`. The knowledge package imports its
tool modules from `tools/knowledge/__init__.py`.

The lifespan configures tracing at startup. On normal shutdown it flushes traces,
optionally clears provider context caches, then closes Semantic Scholar,
Weaviate, and pooled Gemini clients. Client connections are created on demand;
configuration and the default session store may initialize during imports.

## 3. GeminiClient Pipeline

`GeminiClient.get()` maintains one SDK client per API key. Ordinary generation
uses `client.aio.models.generate_content()`. The shared helper resolves model
and thinking settings, validates model compatibility, builds
`GenerateContentConfig`, applies retries, and extracts visible text while
excluding thought parts.

Choose the output path deliberately:

| Method | Returned value | Local validation |
| --- | --- | --- |
| `generate()` | Text | None; a supplied schema constrains the provider request |
| `generate_structured(..., schema=ResultModel)` | Pydantic model instance | `ResultModel.model_validate_json()` |
| `generate_json_validated(..., schema=..., strict=...)` | Parsed dictionary | Pydantic or optional JSON Schema validation |

A default text analysis calls `generate_structured()` with `ContentResult`, then
serializes the model with `model_dump(mode="json")`. Most caller-supplied schema
paths instead call `generate(response_schema=...)` and parse the returned JSON.
JSON parsing alone does not establish conformance to that schema.

`generate_json_validated()` has an explicit strictness contract. With
`strict=True`, malformed JSON or failed validation raises an error; dictionary
schemas require the optional `jsonschema` dependency. With `strict=False`, it
can return unvalidated parsed data, or a `{"raw": ...}` envelope for non-JSON
text. See [test_client_validated.py](../tests/test_client_validated.py) for both paths.

The shared retry helper recreates the awaitable on each attempt. It retries
message patterns associated with quota, timeout, and service-unavailable errors,
using exponential delay plus jitter. Attempt and delay limits come from config.
It does not repair invalid JSON or failed Pydantic validation after a successful
provider response. See [retry.py](../src/video_research_mcp/retry.py).

The default model accepts `low`, `medium`, and `high` thinking. The shared
`ThinkingLevel` alias also includes `minimal`, but model-specific validation can
reject it. For the modern Flash models listed in `config.py`, generation omits
temperature and rejects an explicit temperature override. Model IDs and presets
are maintained in that file rather than copied into this guide.

## 4. Tool Conventions

Tools are async functions registered on a domain `FastMCP` instance. They have
`ToolAnnotations`, the project `@trace(..., span_type="TOOL")` decorator,
described parameters using `Annotated` and `Field`, and Google-style docstrings.
Shared parameter aliases belong in [types.py](../src/video_research_mcp/types.py);
domain result models belong in `models/`.

Instruction-driven tools accept a task description instead of requiring a fixed
analysis mode. A default model supplies a known response shape; an optional
`output_schema` lets callers choose a shape where the workflow supports it.
`coerce_json_param()` handles clients that pass dictionary or list parameters
as JSON strings. It is a transport helper, not a schema validator.

The tool boundary converts operational exceptions into dictionaries through
`make_tool_error()`. Helpers may raise so the boundary can choose the response.
FastMCP validates parameter schemas for MCP calls; direct Python calls bypass
that validation, so workflow invariants also need explicit checks where required.

Annotations describe behavior to the client. They do not authorize operations or
enforce access policy. When extending a tool, account for uploads, cache writes,
knowledge writes, and provider work as well as its primary result.

## 5. Tool Workflows

The [generated manifest](metrics/tool-contract-manifest.json) records the
registered surface at its `generated_at` date. It is not evidence that
credentials, provider access, or a particular installed server work. Regenerate it
with [export_tool_contract_manifest.py](../scripts/export_tool_contract_manifest.py)
when tool contracts change. Use `--output` for an inspection copy; the default
path overwrites the repository snapshot.

The domains follow several distinct workflows:

| Workflow | Behavior and source |
| --- | --- |
| Video analysis | `video_analyze` prepares one YouTube URL or local file, then calls `video_core.analyze_video()` or the strict pipeline. [video.py](../src/video_research_mcp/tools/video.py) |
| Video batches | Scans supported local files and runs ordinary analysis with three concurrent workers; each item retains its result or error. [video_batch.py](../src/video_research_mcp/tools/video_batch.py) |
| YouTube API tools | Fetch metadata, comments, or playlist items without Gemini generation. [tools/youtube.py](../src/video_research_mcp/tools/youtube.py) |
| Prompt-based research | `research_deep` runs scope, evidence, and synthesis prompts; `research_plan` returns a plan without starting agents; evidence assessment consumes supplied source descriptions. [research.py](../src/video_research_mcp/tools/research.py) |
| Document research | Uploads prepared sources and runs document mapping, evidence extraction, cross-reference, and synthesis. [research_document.py](../src/video_research_mcp/tools/research_document.py) |
| Autonomous web research | Persists launch/follow-up requests before provider submission, then polls by interaction ID; resuming a recorded job does not resubmit it. [research_web.py](../src/video_research_mcp/tools/research_web.py), [research_operations.py](../src/video_research_mcp/research_operations.py) |
| Academic metadata | Queries Semantic Scholar for papers, citations/references, recommendations, or authors. Metadata and an open-access URL are separate from retrieved full text. [academic.py](../src/video_research_mcp/tools/academic.py) |
| Content analysis | Accepts exactly one file, URL, or text source; batch comparison sends files together, while individual mode uses three concurrent workers. [content.py](../src/video_research_mcp/tools/content.py), [content_batch.py](../src/video_research_mcp/tools/content_batch.py) |
| Grounded search | `web_search` uses Google Search grounding and returns response text plus grounding sources. [search.py](../src/video_research_mcp/tools/search.py) |
| Knowledge and infrastructure | Query or ingest stored results, inspect schemas and caches, or change permitted runtime settings. See sections 7, 9, 10, and 15. |

`research_deep` does not wire a search tool into its three calls. Its evidence
labels describe the generated assessment; they are not independent verification
that sources were fetched. Use document research for supplied primary documents,
grounded search for search-backed responses, or `research_web` for autonomous
web research according to the task.

Document preparation retains failures in `preparation_issues` when some sources
can be processed. If none can be prepared, the tool returns an error. Source count,
download size, and per-document phase concurrency are bounded by config. `quick`
scope maps the documents and then makes a lightweight synthesis call, skipping
evidence extraction and cross-reference. Other scopes extract evidence; a single
document in `moderate` scope skips cross-reference.

Content URL analysis validates the URL, then uses the provider's URL Context tool.
If structured output with URL Context fails, it fetches an unstructured response
and reshapes that response in a separate call. The content system instruction is
retained across these steps.

### Strict video contract

`video_analyze(strict_contract=True)` rejects a simultaneous custom
`output_schema`. It takes a separate path: validated `StrictVideoResult` analysis,
parallel strategy and concept-map generation, artifact rendering, quality checks,
then promotion of the temporary files to their final directory.

Successful output includes `analysis.md`, `strategy.md`, `concept-map.html`, and
a quality report retained both in the response and `quality-report.json`.
`VIDEO_OUTPUT_DIR` selects the base directory; otherwise it is
`output` relative to the server's working directory. Failed quality checks return
the report and analysis, remove temporary output, and do not return final artifact
paths. This path does not use the ordinary result cache or its write-through store.

The gates check timestamp formatting/order, minimum key-point length, concept
edge references, nonempty artifacts within the output fence, relative links and
basic HTML envelope tags. `status=pass` has the explicit scope
`artifact_and_structure`. Claim support, source timestamp correctness, media
review and human review remain separate pending fields; `factual_success=false`.

[MediaCoverage](../src/video_research_mcp/models/coverage.py) keeps requested,
extracted and observed intervals, observed frame points, source revision/hash,
measured duration and missing stages separate. Observed coverage is the union of
actual observation intervals divided by independently measured duration. It
retains uncovered gaps and never fills time between extracted frames. Unknown
duration or a missing observation stage cannot pass the coverage gate. A final
model timestamp and a model-declared duration never create an observation receipt.
The current provider pipeline has no such receipt, so it reports coverage as
unknown with `coverage_ratio=null`. Artifacts carry an explicit draft review
status. Existing input parameters remain compatible, including
`coverage_min_ratio`; that threshold applies when actual observations exist.
See [pipeline.py](../src/video_research_mcp/contract/pipeline.py),
[quality.py](../src/video_research_mcp/contract/quality.py), and
[validation.py](../src/video_research_mcp/validation.py).

### Original-source packets and production lineage

[EvidencePacket](../src/video_research_mcp/models/evidence.py) version one retains
stable source/claim IDs, original revision and byte hash, a frozen text or media
observation snapshot, exact passages/intervals, approval and abstention, and
script → narration → storyboard → rendered-text parents. Source content is data.
The deterministic validator checks original bytes, exact passage binding and
approved claim text at every stage. Added captions or voiceover facts are flagged.
Exact quoted text does not establish semantic entailment or factual truth;
`contract_passed` and `factual_success` are separate.

The independently packaged explainer validates `evidence-packet.json` before
atomic injection. Missing or stale sources expose no promoted input path and
preserve the previous input. Initial packets can retain incomplete/unsupported
claims with an explicit failing lineage report. Production acceptance requires
re-injecting the actual narration, storyboard, caption and voiceover text; this
contract does not pretend to inspect a renderer's output automatically.

### Native media and optional external MCPs

`image_crop` is an additive deterministic local operation. It validates PNG
metadata, byte/pixel/crop ceilings and the local path fence before optional
FFmpeg decoding. It writes a fresh atomic crop and returns original pixel
coordinates, dimensions and source/output hashes. The source's original versus
synthetic status remains unverified; the output is an extracted asset.

This tool uses the documented native-media exception in [src/AGENTS.md](../src/AGENTS.md):
an explicit success/error schema, `CallToolResult.structuredContent`, a JSON text
block and a PNG `ImageContent` block of at most 1 MiB. `include_image=false` and
larger crops return metadata and the artifact path for text-only clients. Errors
use the shared redacted `ToolError`, set the protocol error flag and contain no
success artifact path. Annotations describe a local non-destructive write, and
the shared tracing decorator still applies. Deterministic operations invoke no
model. Existing generative tools retain their dictionary/schema/client patterns.

`image_edit` uses lazy optional Pillow preparation and one owned source snapshot.
It records EXIF/crop/resize transforms, explicit annotation/cutout provenance,
actual encoded bytes and a digest-bound manifest. `image_ocr` consumes that same
preparation through an explicitly selected local Tesseract or Apple Vision
backend. The optional native backend compiles only the project's own Swift source
and verifies cached executable bytes. `video_clip_export` measures selected
original PTS and decoded output timing under frame, pixel and byte limits.
`image_manifest_read` verifies the retained manifest, original source and every
declared artifact after restart. Native/text transport both rehash all artifacts.
See [image exports](integrations/IMAGE_EXPORTS.md) for public requests and limits.

`vision_chat`, `vision_ocr` and `vision_grounding` submit exact prepared sources
through the existing metered Gemini client or a server-configured compatible
endpoint. Dry plans make no provider calls; submission requires a current workflow
grant. The selected model, account and effective settings are bound to a digest.
Strict inferred boxes map back through preparation transforms to actual original
pixel crops. Model text/object correctness remains unverified. Compatible HTTP
attests the selected peer before transmission and joins independently bounded
cleanup. See [configured vision](integrations/IMAGE_VISION.md).

Optional external MCPs keep their own schemas, pinned subprocess environments,
dependency notices and payload boundaries. Readiness does not authorize installs,
uploads or inference. They add no imports or startup dependencies to the core.

## 6. Singletons

| Shared state | Owner | Lifetime and reset boundary |
| --- | --- | --- |
| Gemini client pool | `GeminiClient` | One client per key; closed at shutdown |
| Configuration | `config._config` | Initialized from environment; replaced by `update_config()` |
| Video sessions | `sessions.session_store` | Process memory, with optional SQLite backing |
| YouTube API service | `YouTubeClient` | Lazy shared service; synchronous requests offloaded to threads |
| Semantic Scholar HTTP client | `SemanticScholarClient` | Shared async client; closed at shutdown |
| Weaviate clients | `WeaviateClient` | Shared sync and async connections; locks protect initialization |
| QueryAgent | `tools/knowledge/agent.py` | Cached for a target collection set |

These are process-local owners. Multiple server processes do not share session
memory or pending cache tasks. Web-research operations use the durable job store
selected by `VRM_JOB_DB`, independently of the optional session database.

## 7. Weaviate Integration

Weaviate is an optional persistent store for derived results. `WEAVIATE_URL`
enables it; store helpers return immediately when disabled. Enabled writes are
best-effort: a storage failure is logged and does not invalidate the primary
analysis. Most synchronous database operations run through `asyncio.to_thread()`.

The collection definitions in
[weaviate_schema/__init__.py](../src/video_research_mcp/weaviate_schema/__init__.py)
are canonical. There are 13 collections, including `AcademicPapers`. They define
properties, vectorization choices, filter/search indexes, and references. On first
sync connection the client creates missing collections, adds missing properties,
checks vector configuration, and establishes references. Vector migration is
controlled separately by `WEAVIATE_AUTO_MIGRATE`; see
[weaviate_migrate.py](../src/video_research_mcp/weaviate_migrate.py) before enabling it.

Write-through is selected by the workflow, not automatic for every tool:

| Producer | Primary collection |
| --- | --- |
| Ordinary video analysis and video batches | `VideoAnalyses` |
| YouTube metadata | `VideoMetadata` |
| Successful video conversation turns | `SessionTranscripts` |
| Deep research, evidence assessment, and document research | `ResearchFindings` |
| Research plans | `ResearchPlans` |
| Completed autonomous web reports and follow-ups | `DeepResearchReports` |
| Content analysis and successful batch results | `ContentAnalyses` |
| Grounded web search | `WebSearchResults` |
| Returned academic paper records | `AcademicPapers` |

Metadata uses a deterministic video UUID. Video analysis uses a UUID derived
from content ID and instruction, allowing repeat writes to replace the same
object. See [weaviate_store/video.py](../src/video_research_mcp/weaviate_store/video.py)
for the exact key and metadata reference behavior.

Several analysis workflows also await `extract_and_store_graph()`, which makes
an additional Gemini call to derive concepts and relationships, then attempts
storage. This helper catches failures. Its model call is not guarded by Weaviate
enablement, so disabling storage does not by itself eliminate that enrichment
call. See [weaviate_store/graph.py](../src/video_research_mcp/weaviate_store/graph.py).

When storage is disabled, search, related-object, and stats tools return empty
result models. Fetch, ingest, and QueryAgent tools return a configuration error;
QueryAgent tools also check for the required `agents` extra. `knowledge_schema`
reads local definitions and works without a connection. `knowledge_ingest`
validates supplied property names against those definitions. `knowledge_query`
remains registered but is deprecated in favor of `knowledge_search`. The
[Knowledge Store guide](tutorials/KNOWLEDGE_STORE.md) covers setup and collection use.

### Unified Recall Architecture

Plugin commands can also save Markdown and visualization files in project memory.
Those files are owned by the command workflow, separate from Weaviate storage.
[commands/recall.md](../commands/recall.md) describes browsing filesystem results
alongside knowledge queries. Direct MCP calls do not automatically create those
command memory files.

## 8. Session Management

`video_create_session` creates a `VideoSession` containing the source URI, title,
cache name/model, optional local path, SDK conversation history, timestamps, and
turn count. Session IDs are 12-character UUID prefixes. Local sessions always use
a File API upload so subsequent turns have a replayable URI, including when a
one-shot analysis of the same small file would use inline bytes.

A YouTube session normally keeps its normalized URL. With `download=True`, the
server tries yt-dlp, uploads the local download, and attempts a context cache.
Download or cache failure is reflected in the returned status; cache creation
failure can still leave a usable File API URI.

For each continuation, source recovery checks the bound media and
`prepare_cached_request()` refreshes a known context cache. A live cache receives
a text prompt; otherwise the new user content reattaches the source video. Both
paths use a detached, bounded view of recent conversation pairs and optional
scoped derived memory. The request uses the cache's model while cached and the
current default model otherwise. A successful response appends both SDK content
objects to the original history, updates activity time, and attempts to store
the turn when Weaviate is enabled.

`session_compaction.py` limits the request view without trimming the original
archive. It reports omitted message ranges, source/history hashes, and whether
originals are persisted. Its serialized-byte token estimate does not measure
provider media or cache tokens. Derived memory is explicitly non-authoritative.
The original archive is capped at 8 MiB; an oversized turn fails before append.
Scoped sessions require the exact workspace/notebook pair on lookup.

`SessionStore.create()` and `get()` evict inactive sessions from memory; creation
also evicts the least recently active in-memory session at capacity. Setting
`GEMINI_SESSION_DB` enables synchronous write-through on creation and successful
turns, plus SQLite read-through on lookup. Persistence uses WAL mode and preserves
SDK content fields, including opaque thought signatures.

Memory eviction does not delete SQLite rows. Read-through rejects expired rows
for active use; `SessionStore.archive()` can inspect retained originals without
reactivating an expired session. The timeout is therefore an activity limit,
not a database deletion policy. Configure the database before starting the
process: the module-level store captures it at initialization.

## 9. Caching

There are three stored caches and one bridge between video workflows:

| Layer | Owner and storage | What reuse means |
| --- | --- | --- |
| Result cache | `cache.py`; JSON under `cache_dir` | Returns an earlier ordinary video analysis |
| Upload cache | `tools/video_file.py`; `cache_dir/uploads` | Reuses a File API URI after checking file state |
| Context cache | `context_cache.py`; provider resource with local registry | Reuses provider-side video context for sessions |
| Video cache bridge | `tools/video_cache.py` | Coordinates prewarm, lookup, TTL refresh, and fallback |

Only ordinary video analysis and its batch path use the result cache. Version-two
filenames contain a SHA-256 of the normalized complete request contract; caller
paths and URLs never become filename components. The envelope binds original
source digest/revision, provider and credential scope, model, schema, thinking,
actual prompt/metadata, preprocessing, window/sampling and retrieval revision.
The current caller performs no retrieval and records a null retrieval revision.
Equivalent original inline bytes at renamed paths reuse one identity and retain
aliases; changed bytes create a new revision. Controller source fields survive
response projection. Legacy entries and incomplete contracts are explicit misses.

Every replay/write rechecks original bytes. Missing/deleted/changed sources
invalidate dependent result and local context-cache registry state. Unfetched URLs
have unknown freshness and cannot replay results. Local File API references remain
unverifiable for result reuse until uploaded bytes have an immutable commitment:
the existing uploader hashes and reads a path separately. A local prepared hash
alone does not verify the provider's bytes. Inline payloads are directly bound to
the original snapshot; mismatches before or during analysis fail closed.

`use_cache=False` bypasses result and identity-cache reads/writes and context
prewarm. Ordinary source preparation and YouTube metadata optimization still occur;
the [explicit bounded mode](integrations/EXECUTION_BUDGETS.md) additionally skips
those optional remote operations and knowledge enrichment. TTL expiration and
unreadable/malformed/error/proof-artifact entries are misses. Saves are atomic.

File uploads are deduplicated by content hash and a per-hash lock. A cached URI is
checked through the File API before reuse. One-shot local videos below 20 MiB use
inline bytes; larger files and all local sessions use uploads. Provider context
caches require File API URIs: the bridge skips direct YouTube URLs. Downloaded
YouTube sessions can cache their uploaded file.

Context registry keys are `(content_id, model)`. Resource names persist in a JSON
sidecar; pending tasks and token-limit suppression remain process-local. Sessions
refresh the provider TTL before reuse and reattach the video when refresh fails.
Cache failure does not prevent an uncached session. `infra_cache(action="context")`
returns diagnostics; `action="stats"` and `"list"` inspect local cache files.

## 10. Configuration

[ServerConfig](../src/video_research_mcp/config.py) defines every field, environment
mapping, default, and model compatibility rule. `get_config()` loads the file
selected by `VIDEO_RESEARCH_ENV_FILE`, or `~/.config/video-research-mcp/.env`,
before constructing the singleton. Nonempty process values take precedence;
blank values and unresolved self-placeholders can be filled from that file.

| Concern | Environment settings |
| --- | --- |
| Model routing | `GEMINI_MODEL`, `GEMINI_FLASH_MODEL`, `GEMINI_THINKING_LEVEL`, `DEEP_RESEARCH_AGENT` |
| Cache lifetime | `GEMINI_CACHE_DIR`, `GEMINI_CACHE_TTL_DAYS`, `GEMINI_CONTEXT_CACHE_TTL`, `CLEAR_CACHE_ON_SHUTDOWN` |
| Session bounds | `GEMINI_MAX_SESSIONS`, `GEMINI_SESSION_TIMEOUT_HOURS`, `GEMINI_SESSION_MAX_TURNS`, `GEMINI_SESSION_CONTEXT_TOKEN_BUDGET`, `GEMINI_SESSION_RECENT_TURNS`, `GEMINI_SESSION_DB` |
| Document bounds | `DOC_MAX_DOWNLOAD_BYTES`, `RESEARCH_DOCUMENT_MAX_SOURCES`, `RESEARCH_DOCUMENT_PHASE_CONCURRENCY` |
| Local read boundary | `LOCAL_FILE_ACCESS_ROOT` |
| Knowledge storage | `WEAVIATE_URL`, `WEAVIATE_API_KEY`, `WEAVIATE_VECTORIZER`, `WEAVIATE_AUTO_MIGRATE` |
| Search enrichment | `COHERE_API_KEY`, `RERANKER_ENABLED`, `FLASH_SUMMARIZE` |
| Runtime mutation policy | `INFRA_MUTATIONS_ENABLED`, `INFRA_ADMIN_TOKEN` |
| Academic access | `S2_API_KEY`, with `SEMANTIC_SCHOLAR_API_KEY` fallback |
| Tracing | `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME`, `GEMINI_TRACING_ENABLED` |

`infra_configure()` with no overrides reads the current configuration. Its replies
exclude Gemini, YouTube, Weaviate, and Semantic Scholar API keys, plus the infra
admin token. Model, thinking, preset, or temperature overrides require infra mutations to be enabled,
plus the configured admin token if present. `infra_cache(action="clear")` uses
the same policy. `update_config()` rebuilds and validates the config model;
changes affect later consumers but do not reconstruct existing session stores.

## 11. URL Validation

YouTube input uses the host and video-ID rules in
[video_url.py](../src/video_research_mcp/tools/video_url.py). Accepted watch,
short-link, shorts, embed, live, mobile, and music forms normalize to a canonical
watch URL. Exact host matching rejects lookalike domains.

General URLs use `url_policy.validate_url()`: HTTPS, a hostname without embedded
credentials, and DNS addresses outside blocked private, loopback, link-local,
multicast, and reserved ranges. Server-side document downloads use
`download_checked()`, which revalidates redirects, bounds response bytes, and
rejects connections without a peer IP and validates the exposed peer IP. That download policy is
separate from provider-side URL Context retrieval.

Local file workflows resolve paths and apply `LOCAL_FILE_ACCESS_ROOT` when set.
Video inputs also require an existing regular file with a supported extension.
Use the shared policies when adding inputs; tests cover URL attacks, redirects,
size caps, path boundaries, and upload behavior.

## 12. Error Handling

`make_tool_error()` returns the standard fields `error`, `category`, `hint`,
`retryable`, and optional `retry_after_seconds`. Classification combines typed
policy/network exceptions with provider-message patterns. Quota, network,
Weaviate connection, and Semantic Scholar rate-limit categories are retryable;
the quota category includes a suggested wait.

This is the preferred tool contract, not a claim that every existing error branch
has identical fields. Missing sessions have a hand-built envelope, and
`content_extract` includes `raw_response` on malformed JSON. Strict video quality
failures additionally include the quality report and analysis. Consult
[errors.py](../src/video_research_mcp/errors.py), the owning tool, and its tests
when changing a particular error path.

Distinguish a failed primary request from failed enrichment. Primary failures
return errors; context-cache, graph, and write-through storage failures are
generally best-effort. Batch workflows retain per-item failures in the returned
items and counts.

## 13. Prompt Templates

Prompts are workflow inputs, not provider-access or correctness guarantees.
[prompts/research.py](../src/video_research_mcp/prompts/research.py) owns scope,
evidence, planning, and synthesis templates;
[prompts/research_document.py](../src/video_research_mcp/prompts/research_document.py)
owns document-grounded phases. Content and knowledge prompts keep untrusted
source material separate from system instructions.

Video prompting is split between the ordinary analysis preamble in
[video_core.py](../src/video_research_mcp/tools/video_core.py), metadata templates
in [prompts/video.py](../src/video_research_mcp/prompts/video.py), and strict
strategy/concept prompts in `contract/pipeline.py`. A prompt change should be
tested at the workflow that assembles it, including fallbacks that reshape output.

## 14. Tracing

The optional `tracing` extra provides MLflow tool spans and Gemini SDK autologging.
Tracing requires a tracking URI and is disabled explicitly by
`GEMINI_TRACING_ENABLED=false`. The project decorator is a passthrough when
disabled at decoration time. Setup failures are logged; shutdown attempts to
flush pending traces.

The autolog path instruments GenerateContent calls supported by the integration.
Do not infer equivalent coverage for every SDK operation from a tool span.
See [tracing.py](../src/video_research_mcp/tracing.py) and
[test_tracing.py](../tests/test_tracing.py) for the actual setup and failure behavior.

## 15. Knowledge Search Pipeline

`knowledge_search` dispatches hybrid, semantic, or keyword queries to selected
collections. Filters are applied only where the collection has the relevant
property; incompatible conditions are skipped. A requested filter therefore
does not necessarily constrain every searched collection.

When reranking is enabled and a collection has a rerank property, the query
fetches three times the requested limit and asks Weaviate's reranker to score
those candidates. Results merge across collections, sort by rerank score then
base score, and trim to a single overall `limit`. A failing collection logs a
warning while other collections continue.

Optional Flash summarization adds one-line summaries and keeps selected properties.
It preserves original hits when summarization fails. The summarizer builds a
bounded prompt using the constants in `tools/knowledge/summarize.py`; summaries
do not replace the stored source objects. `reranked` and `flash_processed` report
which enrichment occurred.

See [search.py](../src/video_research_mcp/tools/knowledge/search.py),
[knowledge_filters.py](../src/video_research_mcp/tools/knowledge_filters.py),
[helpers.py](../src/video_research_mcp/tools/knowledge/helpers.py), and
[summarize.py](../src/video_research_mcp/tools/knowledge/summarize.py) for query,
score, property, and fallback contracts.

## 16. Companion Packages

The repository also contains two separately installed Python MCP servers with
their own package metadata, locks, configuration, and tests. They are not mounted
by the research server.

[video-agent-mcp](../packages/video-agent-mcp/README.md) generates scene text with
the Claude Agent SDK. Its runner bounds concurrency and timeout, disables tools
and inherited settings/MCP configuration, and overrides `CLAUDECODE` only in the
child environment. A result succeeds only after a successful terminal SDK message
and nonempty output; partial text from an errored run is not returned as success.

[video-explainer-mcp](../packages/video-explainer-mcp/README.md) supports upstream
`video_explainer` CLI workflows and explicitly configured renderer routes. The
runner uses argument-list subprocesses, injects the projects directory for CLI
work, and joins owned processes on timeout or cancellation. The scanner reports
filesystem step state.

Render start/poll/cancel uses durable SQLite jobs with frozen source/settings,
leases, and artifact readback. Startup reconciles retained jobs; an expired lease
or unverified output is reported as `unknown`. Full MP4 decode establishes
playability separately from renderer identity and audiovisual semantics. See
`tools/render_jobs.py` and `render_worker.py` in the companion package.
Its server also mounts planning, diagnostics, audio, commentary, timing,
refinement, and existing-material assembly. Stock-media search/download remains
unmounted. Source installation, runtime prerequisites, and accepted output are
separate conditions.
