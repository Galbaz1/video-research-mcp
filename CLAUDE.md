# CLAUDE.md

## Memory Source Guard

Do not import `AGENTS.md` (for example via `@AGENTS.md` or `@../AGENTS.md`) from this file or any `.claude/rules/*.md` file. `AGENTS.md` is Codex-specific and keeping it out of Claude memory prevents duplicate or conflicting guidance.

## What This Is

A monorepo with three separately launched MCP servers:

1. **video-research-mcp** (root) — research, media analysis, source ingestion, knowledge retrieval, and optional provider adapters. Uses the configured Gemini model (`google-genai` SDK) and YouTube Data API v3.
2. **video-explainer-mcp** (`packages/video-explainer-mcp/`) — explainer planning, generation, durable rendering, and assembly of existing materials. Wraps the [video_explainer](https://github.com/prajwal-y/video_explainer) CLI and supports configured renderer routes with separate prerequisites.
3. **video-agent-mcp** (`packages/video-agent-mcp/`) — bounded parallel scene-text generation through the Claude Agent SDK.

All servers default to `~/.config/video-research-mcp/.env` for configuration;
the root also accepts an installer-selected `VIDEO_RESEARCH_ENV_FILE`.
Built with Pydantic v2 and hatchling. Python >= 3.11.

## Commands

```bash
# video-research-mcp (root)
uv sync --locked --extra dev                       # install locked dependencies
uv run --locked pytest tests/ -v                   # all tests
uv run --locked ruff check src/ tests/              # lint
GEMINI_API_KEY=... uv run --locked video-research-mcp # run server

# video-explainer-mcp (packages/)
cd packages/video-explainer-mcp
uv sync --locked --extra dev                       # install locked dependencies
uv run --locked pytest tests/ -v                   # all tests
uv run --locked ruff check src/ tests/              # lint
EXPLAINER_PATH=/path/to/video_explainer uv run --locked video-explainer-mcp

cd ../..
python3 scripts/detect_review_scope.py --json       # from the root checkout
```

## Automated Review Triggers

Use `scripts/detect_review_scope.py --json` to choose the review mode from git state:

- `uncommitted`: there are local unstaged/staged changes (`git status --porcelain` not empty)
- `pr`: clean working tree + branch has open PR (`gh pr view` resolves OPEN PR)
- `commits`: clean working tree, no open PR, and branch is ahead of base (`base_branch..HEAD`)
- `none`: nothing reviewable in current branch state

Trigger this detector:
- when user asks for a review/audit/check
- after major git state transitions (commit, rebase, merge, branch switch)

Priority when multiple states can apply:
1. `uncommitted`
2. `pr`
3. `commits`

## /gr Plugin Routing

Check `/gr:recall` first (already researched?). Unsure which /gr command? Use `/gr:advisor`.
NEVER use `/gr:research-deep` for quick questions (costs $2-5, 10-20 min) — use `/gr:search` instead.

## Architecture

`server.py` mounts domain servers onto a root `FastMCP("video-research")`.
The core workflows include:

| Domain | Source |
| --- | --- |
| Video analysis, sessions, batches, and windows | `tools/video.py`, `tools/video_batch.py`, `tools/video_windows.py` |
| Research, documents, web research, academic metadata, and execution | `tools/research.py` and its deferred registration modules |
| Content analysis and extraction | `tools/content.py`, `tools/content_batch.py` |
| Search and provider adapters | `tools/search.py`, `tools/search_provider.py`, `tools/text_provider.py` |
| Configuration and cache | `tools/infra.py` |
| YouTube metadata, comments, playlists, and channels | `tools/youtube.py`, `tools/youtube_channels.py` |
| Knowledge retrieval and ingestion | `tools/knowledge/` |

Additional mounts cover images/vision, media preparation/perception, audio,
durable jobs, memory, ingestion, live workflows, and hardware. `server.py` is
the current mount inventory; tool discovery provides the exposed schemas.
Registration alone does not establish provider or native-runtime readiness.

**Key patterns:**
- **Instruction-driven tools** — tools accept free-text `instruction` + optional `output_schema` instead of fixed modes
- **Structured output** — Gemini generation uses validated models; deterministic operations validate typed inputs/results without Gemini
- **Error handling** — tools catch operational errors and use `make_tool_error()` within their published dictionary or native `CallToolResult` envelope
- **Write-through storage** — selected result-producing workflows store to Weaviate when configured; store calls are non-fatal
- **Context caching** — `context_cache.py` pre-warms Gemini caches after `video_analyze`; `video_create_session` reuses them via `lookup_or_await()`
- **MLflow tracing** — `@trace()` decorator on all tools; graceful degradation when mlflow not installed
- **Reranker** — Cohere reranking in `knowledge_search` with overfetch pattern; auto-enables when `COHERE_API_KEY` is set

**Key singletons:** `GeminiClient` (client.py), `get_config()` (config.py), `session_store` (sessions.py, optional SQLite via persistence.py), `cache` (cache.py), `WeaviateClient` (weaviate_client.py).

**Optional dependency:** the `agents` extra enables `knowledge_ask` and
`knowledge_query` through Weaviate's QueryAgent. Its constraint lives in
`pyproject.toml`; enable the extra in the environment that launches the server.

> Deep dive: `docs/ARCHITECTURE.md` | `docs/DIAGRAMS.md`

### video-explainer-mcp Architecture

`packages/video-explainer-mcp/src/video_explainer_mcp/server.py` mounts the
following workflow groups:

| Sub-server | Tools | File |
|------------|-------|------|
| project | `explainer_create`, `explainer_inject`, `explainer_status`, `explainer_list` | `tools/project.py` |
| pipeline and rendering | `explainer_generate`, `explainer_step`, `explainer_short`, `explainer_render`, `explainer_render_start`, `explainer_render_poll`, `explainer_render_cancel` | `tools/pipeline.py`, `tools/render_jobs.py` |
| quality | `explainer_refine`, `explainer_feedback`, `explainer_factcheck` | `tools/quality.py` |
| audio | `explainer_sound`, `explainer_music`, `explainer_narration`, `explainer_audio_mix` | `tools/audio.py`, `tools/audio_mix.py` |

Other mounts provide planning, diagnostics, variants, commentary, timing,
refinement, render fact-checking, and existing-material assembly. Stock-media
search/download is not mounted; consult `server.py` for registration.

**Key patterns:**
- **CLI wrapping** — tools invoke the upstream `.venv/bin/video-explainer` console script via `asyncio.create_subprocess_exec` (never shell=True)
- **Filesystem scanning** — `scanner.py` inspects project directories for step completion without CLI calls
- **Background renders** — start/poll/cancel use durable SQLite jobs, frozen requests, leases, and fresh artifact readback
- **Shared config** — same `~/.config/video-research-mcp/.env` as the parent server

**Key modules:** `runner.py` (subprocess executor), `scanner.py` (project inspector), `jobs.py` and `render_worker.py` (durable render lifecycle), `prereqs.py` (system checks), `config.py` (singleton from env).

**Env vars:** `EXPLAINER_PATH` for upstream CLI workflows,
`EXPLAINER_RENDERER_ENTRY` for a configured renderer route,
`EXPLAINER_TTS_PROVIDER` (default: mock), `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`.

### video-agent-mcp Architecture

`packages/video-agent-mcp/` generates scene definitions through bounded SDK calls.

| Sub-server | Tools | File |
|------------|-------|------|
| scenes | `agent_generate_scenes`, `agent_generate_single_scene` | `tools/scenes.py` |

The SDK process has explicit budgets, isolated child configuration and no built-in
tools. Results must be validated before writing scene artifacts.

## Conventions

### New Tools

Every tool MUST have: (1) `ToolAnnotations` decorator, (2) `Annotated` params with
`Field`, (3) Google-style docstring with Args/Returns, and (4) an explicit result
contract. Generative workflows use `GeminiClient.generate_structured()`;
deterministic operations validate typed inputs/results directly without Gemini.
Shared types live in `types.py`.

Native media tools may return `mcp.types.CallToolResult` with typed
`structuredContent`, a JSON text block, and bounded `ImageContent`. Declare
success/error output schemas and offer the same metadata without images.
Preserve existing return contracts; this is the exception in `src/AGENTS.md`.

```python
@server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def my_tool(
    instruction: Annotated[str, Field(description="What to extract")],
    thinking_level: ThinkingLevel = "medium",
) -> dict:
    """One-line summary of what this tool does.

    Args:
        instruction: Free-text analysis instruction.

    Returns:
        Dict with structured results or error via make_tool_error().
    """
```

> Full walkthrough: `docs/tutorials/ADDING_A_TOOL.md`

### New Agents

Frontmatter: `name` (required), `description` (required), `tools` (CSV), `color`, `memory` (project/user), `maxTurns`, `skills` (preload list). Body: persona + workflow + output format. Read-only agents should restrict `tools` to only the MCP query tools they need.

### New Skills

Frontmatter: `name` (required), `description` (required — controls auto-trigger), `allowed-tools`, `disable-model-invocation` (true for side-effect skills). Body loaded only after trigger. Description must include domain-anchor and negative qualifiers to prevent false positives. Use `${CLAUDE_SKILL_DIR}` to reference bundled scripts.

### New Commands

Frontmatter: `description`, `argument-hint`, `allowed-tools`. Body uses `$ARGUMENTS` for user input. Commands are explicit `/gr:name` invocations — always add to `FILE_MAP` in `bin/lib/copy.js`.

### Docstrings

Google-style. Required on every module, public class, public function/method, and non-obvious private helpers. Be concise and factual — one-liner is enough when name + signature are self-explanatory. Args/Returns/Raises only when non-obvious. Pydantic models: document purpose and which tool uses them; don't duplicate `Field(description=...)`. Docstrings do NOT count toward file size limits.

### File Size

~300 lines of executable code per production file (docstrings/comments/blanks excluded). Split by concern, not by line count. Test files may go to 500. Reference: `video.py` / `video_url.py` split.

## Dependencies

### Constraint Policy

Pin to the **major version we actually use**. No cross-major constraints — a constraint like `>=2.0` that accepts both 2.x and 3.x is forbidden when the major versions have breaking API changes. Rationale: overly broad constraints hide version-specific code and create silent compatibility debt (ref: FastMCP 2.x→3.x FunctionTool wrapping incident).

**Format:** `>=MAJOR.MINOR` where MINOR is the lowest version whose API surface we actually use. Never `>=MAJOR.0` unless we've verified compatibility with the .0 release.

### Verified Dependencies

`pyproject.toml` declares the supported API majors; each `uv.lock` records the
exact tested versions. Use `uv sync --locked --extra dev` for verification.
Upgrade from current PyPI metadata, then resolve all three package locks and
verify the affected APIs. Do not maintain a second installed-version table here.

### Known Defensive Patterns (Legitimate)

These `getattr` patterns protect against **SDK response shape variation**, not version incompatibility — do NOT remove:

- `getattr(p, "thought", False)` — Gemini thinking mode parts; `thought` attr only present when thinking is enabled
- `getattr(cand, "grounding_metadata", None)` — search grounding; only present on grounded responses
- `getattr(response, "final_answer", "")` in knowledge/agent.py — weaviate-agents response shape varies by query type
- `try: from googleapiclient.errors import HttpError` in tools/youtube.py — guards error formatting when google-api-python-client isn't importable

### Updating Dependencies

When bumping a dependency:
1. Update constraint in `pyproject.toml`
2. Run `uv lock`, then `uv sync --locked --extra dev` to resolve and install
3. Search for compatibility workarounds that may now be removable (`rg '2\.x|v1|compat|shim|workaround' src/`)
4. Run full test suite: `uv run --locked pytest tests/ -v`

## Agent Teams

Inherit the active configured model for agents. Use bounded, independent lanes
with explicit write ownership and join them before integration.

Agent configuration: `.claude/rules/` contains project-specific conventions that agents inherit automatically via path-filtered frontmatter.

## Testing

Unit tests, all unit-level with mocked Gemini. `asyncio_mode=auto`. No test hits the real API.

**Key fixtures** (`conftest.py`): `mock_gemini_client` (mocks `.get()`, `.generate()`, `.generate_structured()`, `.generate_json_validated()`), `clean_config` (isolates config), `mock_weaviate_client`, `mock_weaviate_disabled`, `_unwrap_fastmcp_tools` (session-scoped, ensures tool callability), autouse `GEMINI_API_KEY=test-key-not-real`, `_disable_tracing`, `_isolate_dotenv`, `_isolate_upload_cache`, `_isolate_durable_jobs`.

**File naming:** `test_<domain>_tools.py` for tools, `test_<module>.py` for non-tool modules.

> Full guide: `docs/tutorials/WRITING_TESTS.md` | Project-specific patterns: `.claude/rules/testing.md`

## Plugin Installer

Two-package architecture: npm distributes plugin assets and registers the pinned
core server via `uvx`; PyPI supplies the Python runtime. The installer supports
scoped Claude and Codex layouts. Same package name, different registries.

```bash
npx video-research-mcp@0.8.0-rc.3              # install the pinned source version
npx video-research-mcp@0.8.0-rc.3 --check      # inspect installation hashes/status
npx video-research-mcp@0.8.0-rc.3 --uninstall  # remove unchanged owned assets
```

To add a command/skill/agent: create file, add to `FILE_MAP` in `bin/lib/copy.js`, run `node bin/install.js --global`.

> Deep dive: `docs/PLUGIN_DISTRIBUTION.md` (FILE_MAP, manifest tracking, discovery mechanism, complete inventory)

## Env Vars

Canonical source: `config.py:ServerConfig`. Key variables:

| Variable | Default | Notes |
|----------|---------|-------|
| `GEMINI_API_KEY` | (required) | Also used as YouTube fallback |
| `GEMINI_MODEL` | `gemini-3.8-flash` | |
| `GEMINI_FLASH_MODEL` | `gemini-3.8-flash` | Same default as `GEMINI_MODEL`; thinking_level is the dial |
| `GEMINI_THINKING_LEVEL` | `medium` | `low` / `medium` / `high`; `minimal` is rejected for models that do not support it |
| `DEEP_RESEARCH_AGENT` | `deep-research-preview-04-2026` | Interactions API agent ID |
| `WEAVIATE_URL` | `""` | Empty = knowledge store disabled |
| `WEAVIATE_API_KEY` | `""` | Required for Weaviate Cloud |
| `GEMINI_SESSION_DB` | `""` | Empty = in-memory only |
| `RERANKER_ENABLED` | `""` | Auto-enabled when `COHERE_API_KEY` set |
| `COHERE_API_KEY` | `""` | Enables Cohere reranker in knowledge_search |
| `FLASH_SUMMARIZE` | `"true"` | Use Flash model for summarization |
| `GEMINI_TRACING_ENABLED` | `""` | Enable MLflow tracing |
| `MLFLOW_TRACKING_URI` | `""` | MLflow server URI |
| `MLFLOW_EXPERIMENT_NAME` | `""` | MLflow experiment name |
| `WEAVIATE_VECTORIZER` | `""` | `openai`, `weaviate`, or `ollama`; selects `openai` when OPENAI_API_KEY is present, otherwise `weaviate` |
| `WEAVIATE_AUTO_MIGRATE` | `""` | Set "true" to auto-migrate collections when vector config changes |
| `EXPLAINER_PATH` | `""` | Path to cloned video_explainer repo |
| `EXPLAINER_TTS_PROVIDER` | `"mock"` | mock, elevenlabs, edge |
| `ELEVENLABS_API_KEY` | `""` | Required for elevenlabs TTS |
| `OPENAI_API_KEY` | `""` | Required for the OpenAI vectorizer and configured OpenAI provider calls |

All servers default to `~/.config/video-research-mcp/.env`; the root uses
`VIDEO_RESEARCH_ENV_FILE` when selected by a local installation. Nonempty process
values take precedence. Blank values and unresolved self-placeholders are treated
as unset and can be filled from the selected file.

All other config (thinking level, temperature, cache dir/TTL, session limits, retry params, YouTube API key) has sensible defaults — see `config.py` or `docs/ARCHITECTURE.md` §10.

## Archive

`archive/` (gitignored) contains development artifacts moved out of the working tree: completed design docs, code reviews, bug reports (now in GitHub Issues), audit snapshots, and research notes. See `archive/INDEX.md` for a full inventory.

## Developer Docs

| Document | Contents |
|----------|----------|
| `docs/ARCHITECTURE.md` | Technical guide to workflows, shared state, provider access, and companions |
| `docs/DIAGRAMS.md` | Server hierarchy, GeminiClient flow, session lifecycle, Weaviate data flow |
| `docs/tutorials/GETTING_STARTED.md` | Install, configure, first tool call |
| `docs/tutorials/ADDING_A_TOOL.md` | Step-by-step tool creation with checklist |
| `docs/tutorials/WRITING_TESTS.md` | Fixtures, patterns, running tests |
| `docs/tutorials/KNOWLEDGE_STORE.md` | Weaviate setup, collection schemas, retrieval, and QueryAgent |
| `docs/PLUGIN_DISTRIBUTION.md` | Two-package architecture, FILE_MAP, discovery, full inventory |
| `docs/PUBLISHING.md` | Dual-registry publishing guide with version sync policy |
| `docs/RELEASE_CHECKLIST.md` | Copy-paste checklist for each release |
| `CHANGELOG.md` | Release history in Keep a Changelog format |
