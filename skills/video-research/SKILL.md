---
name: video-research
description: Use video-research MCP tools for evidence-aware video/document analysis, cited research, academic discovery, and knowledge queries when that server is connected.
---

# Video Research MCP — Tool Usage Guide

Discover whether the `video-research-mcp` server is connected before calling it. Its tools use configured Gemini models, YouTube Data API, Semantic Scholar, optional Weaviate, and deterministic local adapters. Inspect `infra_configure()` for live models; the default is Gemini 3.8 Flash. Generative tools are **instruction-driven**: you supply an instruction and receive structured model output. Other tools use their exposed typed contracts. Three tools (`video_metadata`, `video_comments`, `video_playlist`) use the YouTube Data API directly for fast metadata retrieval without Gemini inference.

## Core Principle

Tools accept an `instruction` parameter instead of fixed modes. Write specific, actionable instructions. The more precise your instruction, the better the structured output.

## Tool Selection Guide

| I want to... | Use this tool |
|---|---|
| Get video title, stats, duration, tags | `video_metadata` |
| List videos in a YouTube playlist | `video_playlist` |
| Analyze a YouTube video | `video_analyze` |
| Have a multi-turn conversation about a video | `video_create_session` + `video_continue_session` |
| Research a topic in depth | `research_deep` |
| Plan a research strategy | `research_plan` |
| Assess a claim against supplied source descriptions | `research_assess_evidence` |
| Launch long-running web-grounded deep research | `research_web` |
| Poll status of a running deep-research job | `research_web_status` |
| Ask follow-up questions on a completed deep-research report | `research_web_followup` |
| Cancel a running deep-research job | `research_web_cancel` |
| Analyze a URL, file, or text | `content_analyze` |
| Batch-analyze a folder of documents | `content_batch_analyze` |
| Extract structured data from content | `content_extract` |
| Deep research grounded in documents | `research_document` |
| Search the web for current info | `web_search` |
| Check or clear the cache | `infra_cache` |
| Inspect or change model/thinking settings | `infra_configure` |
| Search papers or authors | `research_paper_search`, `research_author_search` |
| Fetch paper metadata, citations, or recommendations | `research_paper_details`, `research_paper_citations`, `research_paper_recommendations` |
| Find past analyses and research | `/gr:recall "topic"` (semantic search when Weaviate configured) |
| Get AI answer from past work | `/gr:recall ask "question"` (requires Weaviate + weaviate-agents) |
| Browse knowledge gaps | `/gr:recall fuzzy` or `/gr:recall unknown` |

## Media Storage Conventions

When local media is available, prefer shared project memory paths:
- Videos: `gr/media/videos/<content_id>.mp4`
- Screenshots: `gr/media/screenshots/<content_id>/frame_MMSS.png`

Knowledge results may include:
- `local_filepath`: local video/content file path
- `screenshot_dir`: local screenshot directory path

## Tool Reference

### Video and YouTube Tools

#### `video_metadata` — Get YouTube video metadata (no Gemini cost)
```
video_metadata(url: str)  # YouTube URL
```
Returns `{video_id, title, description, channel_title, published_at, tags[], view_count, like_count, comment_count, duration_seconds, duration_display, category, definition, has_captions, default_language}`.

Costs 1 YouTube API unit, 0 Gemini units. Use this for quick metadata lookups before deciding whether to run a full `video_analyze`.

#### `video_playlist` — List videos in a playlist
```
video_playlist(url: str, max_items: int = 20)  # Playlist URL with list= param
```
Returns `{playlist_id, items[{video_id, title, position, published_at}], total_items}`.

Use to enumerate playlist contents, then pass individual video IDs to `video_analyze` for analysis.

#### `video_analyze` — Analyze any YouTube video
```
video_analyze(
  url: str | None = None,       # YouTube URL
  file_path: str | None = None, # Local video file
  instruction: str = "...",     # What to analyze (default: comprehensive analysis)
  output_schema: dict | None,   # Custom JSON Schema for response shape
  thinking_level: str = "high", # low | medium | high for the default model
  use_cache: bool = True        # Cache results by instruction hash
)
```

**Default output** (VideoResult + metadata): `{title, summary, key_points[], timestamps[{time, description}], topics[], sentiment, source, local_filepath, screenshot_dir}`

**Writing good instructions:**
- BAD: "analyze this video" (too vague, just use the default)
- GOOD: "Extract every CLI command demonstrated, including flags and arguments"
- GOOD: "List all recipes shown with ingredients and cooking times"
- GOOD: "Transcribe this video with timestamps for each speaker change"
- GOOD: "Identify the 3 most controversial claims and rate their evidence strength"

**When to use custom output_schema:**
Use when the default VideoResult shape doesn't match what you need:
```json
{
  "type": "object",
  "properties": {
    "recipes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "ingredients": {"type": "array", "items": {"type": "string"}},
          "steps": {"type": "array", "items": {"type": "string"}}
        }
      }
    }
  }
}
```

**Common instruction patterns:**
- Transcript: `instruction="Transcribe with timestamps"`
- Tutorial extraction: `instruction="Extract commands, tools, and step-by-step workflow"`
- Comparison prep: Call `video_analyze` on each URL with the same instruction, then synthesize

#### `video_create_session` — Start multi-turn video exploration
```
video_create_session(
  url: str | None = None,
  file_path: str | None = None,
  description: str = "",
  download: bool = False
)
```
Returns `{session_id, status, video_title, source_type, cache_status, download_status, cache_reason, local_filepath}`.
Use for iterative Q&A about one video.

#### `video_continue_session` — Follow up within a session
```
video_continue_session(session_id: str, prompt: str)
```
Returns `{response, turn_count}`. Maintains conversation history across turns.

### Content Tools

#### `content_analyze` — Analyze any content (file, URL, or text)
```
content_analyze(
  instruction: str = "...",     # What to analyze
  file_path: str | None,        # Local file (PDF or text)
  url: str | None,              # URL to fetch and analyze
  text: str | None,             # Raw text
  output_schema: dict | None,   # Custom JSON Schema
  thinking_level: str = "medium"
)
```

**Provide exactly one of** `file_path`, `url`, or `text`.

**Default output** (ContentResult): `{title, summary, key_points[], entities[], structure_notes, quality_assessment}`

**Examples:**
- Summarize a webpage: `content_analyze(url="https://...", instruction="Summarize in 3 sentences")`
- Extract from PDF: `content_analyze(file_path="paper.pdf", instruction="Extract methodology with statistical methods")`
- Analyze text: `content_analyze(text="...", instruction="List all named entities with types")`

#### `content_batch_analyze` — Batch-analyze multiple documents
```
content_batch_analyze(
  instruction: str = "...",          # What to analyze across documents
  directory: str | None,             # Directory to scan for content files
  file_paths: list[str] | None,      # Explicit list of file paths
  glob_pattern: str = "*",           # Filter within directory
  mode: str = "compare",            # "compare" (one call) | "individual" (per-file)
  output_schema: dict | None,        # Custom JSON Schema
  thinking_level: str = "high",
  max_files: int = 20
)
```

**Provide either** `directory` or `file_paths` (not both). Supports PDF, TXT, MD, HTML, XML, JSON, CSV.

**Two modes:**
- `compare`: All files sent in one Gemini call for cross-document analysis
- `individual`: Each file analyzed separately with 3 parallel calls

**Examples:**
- Compare papers: `content_batch_analyze(directory="/papers/", instruction="Compare methodologies")`
- Batch summarize: `content_batch_analyze(file_paths=["a.pdf", "b.pdf"], mode="individual", instruction="Summarize")`

#### `content_extract` — Extract structured data with caller-provided schema
```
content_extract(content: str, schema: dict)
```
Use when you have a specific JSON Schema and need schema-constrained extraction; still check error responses and validate required evidence.

### Research Tools

#### `research_deep` — Multi-phase deep research
```
research_deep(
  topic: str,                    # Research question (3-500 chars)
  scope: str = "moderate",       # quick | moderate | deep | comprehensive
  thinking_level: str = "high"
)
```
Runs 3 model-only phases: Scope Definition > Evidence Collection > Synthesis. It retrieves no external sources; proposed CONFIRMED/STRONG INDICATOR tiers become UNKNOWN.
Returns `{topic, scope, executive_summary, findings[{claim, evidence_tier, supporting[], contradicting[], reasoning}], open_questions[], methodology_critique}`.

Evidence tiers: CONFIRMED, STRONG INDICATOR, INFERENCE, SPECULATION, UNKNOWN.

#### `research_plan` — Generate research orchestration blueprint
```
research_plan(topic: str, scope: str = "moderate", available_agents: int = 10)
```
Returns a phased blueprint with task decomposition and model assignments. Does NOT execute — provides the plan.

#### `research_document` — Deep research grounded in source documents
```
research_document(
  instruction: str,                  # Research question for the documents
  file_paths: list[str] | None,      # Local PDF/document paths
  urls: list[str] | None,            # URLs to downloadable documents
  scope: str = "moderate",           # quick | moderate | deep | comprehensive
  thinking_level: str = "high"
)
```

4-phase pipeline: Document Mapping > Evidence Extraction > Cross-Reference > Synthesis.
Documents are uploaded via File API for multi-phase reuse. Inspect generated document/page citations against the originals before relying on a claim.

**Scope controls depth:**
- `quick`: Map + lightweight summary (2 Gemini calls)
- `moderate`: Map + evidence + synthesis (3 calls, skip cross-ref for single doc)
- `deep`/`comprehensive`: All 4 phases with full cross-referencing

**Examples:**
- Analyze a paper: `research_document(file_paths=["paper.pdf"], instruction="Assess methodology")`
- Compare reports: `research_document(file_paths=["q1.pdf", "q2.pdf"], instruction="Find contradictions", scope="deep")`

#### `research_web` — Launch Gemini Deep Research Agent (background)
```
research_web(topic: str, output_format: str = "")
```
Starts a hosted web-grounded research task and returns an `interaction_id`. Runtime and internal search/token/USD ceilings are provider-managed; retain the launch identity across interruptions.

#### `research_web_status` — Poll a Deep Research interaction
```
research_web_status(interaction_id: str)
```
Returns current status while running and returns full report + sources when completed.

#### `research_web_followup` — Ask follow-up questions on completed Deep Research
```
research_web_followup(interaction_id: str, question: str)
```
Returns a contextual follow-up response tied to the original deep-research interaction.

#### `research_web_cancel` — Cancel a running Deep Research task
```
research_web_cancel(interaction_id: str)
```
Requests cancellation of the existing interaction. Inspect the returned state; cancellation does not reverse prior spend.

#### `research_assess_evidence` — Assess a claim against sources
```
research_assess_evidence(claim: str, sources: list[str], context: str = "")
```
Returns `{claim, tier, confidence, supporting[], contradicting[], reasoning}` plus proposal metadata. Source access is unobserved and `factual_success` is false; proposed CONFIRMED/STRONG INDICATOR tiers become UNKNOWN.

### Academic Discovery

The Semantic Scholar tools search metadata/abstracts, fetch details, follow citations/references, recommend papers, and search authors. They do not read full papers automatically. Fetch primary full text before making methodology claims; distinguish abstract-only evidence and missing papers. Read current tool schemas for filters, identifier formats, pagination, and limits.

### Search Tool (1)

#### `web_search` — Google Search via Gemini grounding
```
web_search(query: str, num_results: int = 5)
```
Returns `{query, response, sources[{title, url}]}`. Uses Gemini Flash with Google Search.

### Infrastructure Tools (2)

#### `infra_cache` — Manage analysis cache
```
infra_cache(action="stats" | "list" | "clear", content_id=None)
```

#### `infra_configure` — Runtime config changes
```
infra_configure(preset=None, model=None, thinking_level=None, temperature=None, auth_token=None)
```

Read-only configuration inspection needs no mutation grant. Configuration changes and cache clearing require `INFRA_MUTATIONS_ENABLED` and the configured admin token when required. Handle a policy refusal without changing operator policy.

## Workflow Patterns

### Research a topic end-to-end
1. `research_plan(topic)` > orchestration blueprint
2. Run independent calls in parallel within the available worker/provider budget:
   - `web_search(query)` > gather current sources (Gemini Flash)
   - `research_deep(topic, scope="deep")` > full analysis with evidence tiers (configured analysis model)
3. `research_assess_evidence(claim, sources)` > model assessment — call independent claims in parallel within the budget, then inspect decisive primary evidence

### Analyze a YouTube video with community context
1. `video_metadata(url)` > quick metadata (title, view count, comment count)
2. `video_analyze(url, instruction="...")` > primary analysis
3. Background: `comment-analyst` agent fetches and analyzes YouTube comments
4. Background: `visualizer` agent generates interactive concept map
5. Workers return owned outputs; the parent merges them into `analysis.md` after required workers join

### Analyze a YouTube playlist
1. `video_playlist(url)` > list all videos in the playlist
2. For each video, call `video_analyze(url)` or `video_metadata(url)` as needed
3. Synthesize results across videos

### Analyze a video for a specific use case
1. `video_analyze(url, instruction="Provide a comprehensive analysis")` > overview
2. `video_analyze(url, instruction="Extract all code examples with context")` > deep dive
3. Or use sessions for iterative exploration:
   - `video_create_session(url)` > get session_id
   - `video_continue_session(session_id, "What libraries are used?")` > follow up

### Recall & Knowledge Retrieval

When registered in Claude Code, `/gr:recall` uses `knowledge_search` for semantic queries
when Weaviate is configured, and falls back to filesystem grep otherwise.
Knowledge states (fuzzy/unknown) and visualization browsing are always filesystem-based.
In Codex, use the exposed `knowledge_search` and `knowledge_ask` tools; Claude command aliases are not loaded by the native plugin.

### Ingesting data into the knowledge store

**Always call `knowledge_schema(collection="<name>")` before `knowledge_ingest`.** This returns the exact property names and types — never guess field names.

```
knowledge_schema(collection="ResearchFindings")  # discover fields first
knowledge_ingest(collection="ResearchFindings", properties={...})  # then ingest
```

### Compare multiple videos (orchestrated by you)
1. Call `video_analyze` on each URL with the same instruction
2. Synthesize the results in your response — you are the comparison engine

### Extract structured data from documents
1. `content_analyze(file_path="paper.pdf", instruction="Summarize methodology")` > overview
2. `content_extract(content=text, schema={...})` > precise structured extraction

## Error Handling

All tools return error dicts instead of raising:
```json
{"error": "message", "category": "API_QUOTA_EXCEEDED", "hint": "wait a minute", "retryable": true}
```
Always check for `"error"` key in the response before processing results. The runtime already retries transient Gemini failures. After a retryable result, permit at most one controlled retry for an idempotent call within the authorized budget; retain repeated failure and stop. For background research, retain and poll the existing interaction ID rather than launching a duplicate.

## Caching

Results are cached by `{content_id}_{tool}_{instruction_hash}_{model_hash}`. Different instructions for the same content produce separate cache entries. Use `use_cache=False` to force fresh analysis.

## Thinking Levels

| Level | When to use |
|-------|-------------|
| `minimal` | Only explicitly selected compatible models; rejected by the default Gemini 3.8 Flash |
| `low` | Quick summaries, simple tasks |
| `medium` | Content analysis (default for content tools) |
| `high` | Video analysis, research, complex reasoning (default for video/research) |

## Completion and Evidence

Before declaring completion, verify the exact input and requested coverage, non-empty required fields, source/timestamp/page pointers, and the saved artifact. Label model inference, abstract-only evidence, sampled/condensed transcripts, and uncertain speaker identities. A structured schema does not establish truth; inspect primary evidence for decision-critical claims.

For batches, retain successes, failures, refusals, and omissions in the denominator. Write-through Weaviate storage is non-fatal: report persistence separately from analysis, and do not infer storage from tool success. A cached result is evidence from its original generation, not a fresh provider call. Stop at terminal failure or exhausted repair budget with a concrete next cause-finding step.
