# CLAUDE.md

## Memory Source Guard

Do not import `AGENTS.md` (for example via `@AGENTS.md` or `@../AGENTS.md`) from this file or any `.claude/rules/*.md` file. `AGENTS.md` is Codex-specific and keeping it out of Claude memory prevents duplicate or conflicting guidance.

## What This Is

A monorepo with three MCP servers (45 tools total):

1. **video-research-mcp** (root) — 28 tools for video analysis, deep research, content extraction, web search, and context caching. Powered by Gemini 3.1 Pro (`google-genai` SDK) and YouTube Data API v3.
2. **video-explainer-mcp** (`packages/video-explainer-mcp/`) — 15 tools for synthesizing explainer videos from research content. Wraps the [video_explainer](https://github.com/prajwal-y/video_explainer) CLI.
3. **video-agent-mcp** (`packages/video-agent-mcp/`) — 2 tools providing an autonomous research agent orchestrator. Wraps video-research-mcp tools with planning and execution loops.

All servers share `~/.config/video-research-mcp/.env` for configuration. Built with Pydantic v2, hatchling. Python >= 3.11.

## Commands

```bash
# video-research-mcp (root)
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"  # install
uv run pytest tests/ -v                                              # all tests
uv run ruff check src/ tests/                                        # lint
GEMINI_API_KEY=... uv run video-research-mcp                         # run server

# video-explainer-mcp (packages/)
cd packages/video-explainer-mcp
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"  # install
uv run pytest tests/ -v                                              # all tests
uv run ruff check src/ tests/                                        # lint
EXPLAINER_PATH=/path/to/video_explainer uv run video-explainer-mcp  # run server

python3 ~/.claude/scripts/detect_review_scope.py --json               # auto-select review scope
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

## Architecture

`server.py` mounts 7 sub-servers onto a root `FastMCP("video-research")`:

| Sub-server | Tools | Count | Files |
|------------|-------|-------|-------|
| video | `video_analyze`, `video_create_session`, `video_continue_session`, `video_batch_analyze` | 4 | `tools/video.py`, `tools/video_batch.py` |
| research | `research_deep`, `research_plan`, `research_assess_evidence`, `research_document`, `research_web`, `research_web_status`, `research_web_followup`, `research_web_cancel` | 8 | `tools/research.py`, `tools/research_document.py`, `tools/research_web.py` |
| content | `content_analyze`, `content_extract`, `content_batch_analyze` | 3 | `tools/content.py`, `tools/content_batch.py` |
| search | `web_search` | 1 | `tools/search.py` |
| infra | `infra_cache`, `infra_configure` | 2 | `tools/infra.py` |
| youtube | `video_metadata`, `video_comments`, `video_playlist` | 3 | `tools/youtube.py` |
| knowledge | `knowledge_search`, `knowledge_related`, `knowledge_stats`, `knowledge_fetch`, `knowledge_ingest`, `knowledge_schema`, `knowledge_ask`, `knowledge_query` | 8 | `tools/knowledge/` |

**Key patterns:**
- **Instruction-driven tools** — tools accept free-text `instruction` + optional `output_schema` instead of fixed modes
- **Structured output** — `GeminiClient.generate_structured(contents, schema=ModelClass)` returns validated Pydantic models
- **Error handling** — tools never raise; return `make_tool_error()` dicts with `error`, `category`, `hint`, `retryable`
- **Write-through storage** — every tool auto-stores results to Weaviate when configured; store calls are non-fatal
- **Context caching** — `context_cache.py` pre-warms Gemini caches after `video_analyze`; `video_create_session` reuses them via `lookup_or_await()`
- **MLflow tracing** — `@trace()` decorator on all tools; graceful degradation when mlflow not installed
- **Reranker** — Cohere reranking in `knowledge_search` with overfetch pattern; auto-enables when `COHERE_API_KEY` is set

**Key singletons:** `GeminiClient` (client.py), `get_config()` (config.py), `session_store` (sessions.py, optional SQLite via persistence.py), `cache` (cache.py), `WeaviateClient` (weaviate_client.py).

**Optional dependency:** `weaviate-agents>=1.2.0` (install via `pip install video-research-mcp[agents]`) enables `knowledge_ask` and `knowledge_query` tools powered by Weaviate's QueryAgent.

> Deep dive: `docs/ARCHITECTURE.md` (13 sections) | `docs/DIAGRAMS.md` (4 Mermaid diagrams)

### video-explainer-mcp Architecture

`packages/video-explainer-mcp/src/video_explainer_mcp/server.py` mounts 4 sub-servers:

| Sub-server | Tools | File |
|------------|-------|------|
| project | `explainer_create`, `explainer_inject`, `explainer_status`, `explainer_list` | `tools/project.py` |
| pipeline | `explainer_generate`, `explainer_step`, `explainer_render`, `explainer_render_start`, `explainer_render_poll`, `explainer_short` | `tools/pipeline.py` |
| quality | `explainer_refine`, `explainer_feedback`, `explainer_factcheck` | `tools/quality.py` |
| audio | `explainer_sound`, `explainer_music` | `tools/audio.py` |

**Key patterns:**
- **CLI wrapping** — tools call the `video_explainer` Python module via `asyncio.create_subprocess_exec` (never shell=True)
- **Filesystem scanning** — `scanner.py` inspects project directories for step completion without CLI calls
- **Background renders** — `explainer_render_start` returns a job ID; `explainer_render_poll` checks progress
- **Shared config** — same `~/.config/video-research-mcp/.env` as the parent server

**Key modules:** `runner.py` (subprocess executor), `scanner.py` (project inspector), `jobs.py` (render tracking), `prereqs.py` (system checks), `config.py` (singleton from env).

**Env vars:** `EXPLAINER_PATH` (required), `EXPLAINER_TTS_PROVIDER` (default: mock), `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`.

### video-agent-mcp Architecture

`packages/video-agent-mcp/` — autonomous research agent orchestrator.

| Sub-server | Tools | File |
|------------|-------|------|
| agent | `agent_research`, `agent_status` | `tools/agent.py` |

**Key patterns:**
- **Plan-execute loop** — decomposes research goals into tool-call sequences, executes against video-research-mcp
- **Shared config** — same `~/.config/video-research-mcp/.env` as the parent server

## Conventions

### New Tools

Every tool MUST have: (1) `ToolAnnotations` decorator, (2) `Annotated` params with `Field`, (3) Google-style docstring with Args/Returns, (4) structured output via `GeminiClient.generate_structured()`. Shared types live in `types.py`.

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

### Docstrings

Google-style. Required on every module, public class, public function/method, and non-obvious private helpers. Be concise and factual — one-liner is enough when name + signature are self-explanatory. Args/Returns/Raises only when non-obvious. Pydantic models: document purpose and which tool uses them; don't duplicate `Field(description=...)`. Docstrings do NOT count toward file size limits.

### File Size

~300 lines of executable code per production file (docstrings/comments/blanks excluded). Split by concern, not by line count. Test files may go to 500. Reference: `video.py` / `video_url.py` split.

## Dependencies

### Constraint Policy

Pin to the **major version we actually use**. No cross-major constraints — a constraint like `>=2.0` that accepts both 2.x and 3.x is forbidden when the major versions have breaking API changes. Rationale: overly broad constraints hide version-specific code and create silent compatibility debt (ref: FastMCP 2.x→3.x FunctionTool wrapping incident).

**Format:** `>=MAJOR.MINOR` where MINOR is the lowest version whose API surface we actually use. Never `>=MAJOR.0` unless we've verified compatibility with the .0 release.

### Pinned Dependencies

| Package | Constraint | Installed | API Surface We Use | Rationale |
|---------|-----------|-----------|-------------------|-----------|
| `fastmcp` | `>=3.0.2` | 3.0.2 | `FastMCP`, `.mount()`, `.tool()`, `.run()`, `@asynccontextmanager` lifespan | 3.x preserves tool callability; 2.x wraps in non-callable `FunctionTool` |
| `google-genai` | `>=1.57` | 1.65.0 | `genai.Client`, `ThinkingConfig`, `cached_content`, Gemini 3.1 model strings, async `generate_content` | 1.56 added ThinkingConfig; 1.57 added Gemini 3 model support. Preview/beta SDK versions are fine for this project |
| `google-api-python-client` | `>=2.100` | 2.190.0 | YouTube Data API v3 via `build("youtube", "v3")` | Pure REST wrapper; API stable within v2. `>=2.100` is fine |
| `pydantic` | `>=2.0` | 2.12.5 | v2 only: `BaseModel`, `Field`, `model_validator`, `ConfigDict`, `model_dump()` | No v1 patterns anywhere. v3 doesn't exist yet. `>=2.0` is correct |
| `weaviate-client` | `>=4.19.2` | 4.20.1 | v4 collections API: `client.collections.get()`, `weaviate.classes.*`, `AsyncQueryAgent` | v4 is a complete rewrite from v3. Constraint correctly pins v4 |
| `pytest` | `>=8.0` | 9.0.2 | Standard API | pytest 9.x is backwards compatible. `>=8.0` is fine |
| `pytest-asyncio` | `>=1.0` | 1.3.0 | `asyncio_mode = "auto"` (pyproject.toml) | Major rewrite in 1.0 (from 0.x). `asyncio_mode=auto` is 0.18+ but 1.x API is cleaner. Update constraint to `>=1.0` |
| `mlflow-tracing` | `>=3.0` | — | `@trace()` decorator, `MlflowClient` | Optional `[tracing]` extra; graceful no-op when absent |
| `ruff` | `>=0.9` | 0.15.4 | CLI linter/formatter | Pre-1.0; minor versions may change rules. Acceptable |

### Known Defensive Patterns (Legitimate)

These `getattr` patterns protect against **SDK response shape variation**, not version incompatibility — do NOT remove:

- `getattr(p, "thought", False)` — Gemini thinking mode parts; `thought` attr only present when thinking is enabled
- `getattr(cand, "grounding_metadata", None)` — search grounding; only present on grounded responses
- `getattr(response, "final_answer", "")` in knowledge/agent.py — weaviate-agents response shape varies by query type
- `try: from googleapiclient.errors import HttpError` in tools/youtube.py — guards error formatting when google-api-python-client isn't importable

### Updating Dependencies

When bumping a dependency:
1. Update constraint in `pyproject.toml`
2. Run `uv pip install -e ".[dev]"` to resolve
3. Search for compatibility workarounds that may now be removable (`grep -r "2\.x\|v1\|compat\|shim\|workaround"`)
4. Run full test suite: `uv run pytest tests/ -v`

## Agent Teams

Default model for all subagent teams: **Claude Opus 4.6** (`model: "opus"`). This is a hard project requirement — do not use a lighter model for team agents unless the user explicitly requests it.

Agent configuration: `.claude/rules/` contains project-specific conventions that agents inherit automatically via path-filtered frontmatter.

## Testing

724 tests, all unit-level with mocked Gemini. `asyncio_mode=auto`. No test hits the real API.

**Key fixtures** (`conftest.py`): `mock_gemini_client` (mocks `.get()`, `.generate()`, `.generate_structured()`), `clean_config` (isolates config), `mock_weaviate_client`, `mock_weaviate_disabled`, `_unwrap_fastmcp_tools` (session-scoped, ensures tool callability), autouse `GEMINI_API_KEY=test-key-not-real`, `_disable_tracing`, `_isolate_dotenv`, `_isolate_upload_cache`.

**File naming:** `test_<domain>_tools.py` for tools, `test_<module>.py` for non-tool modules.

> Full guide: `docs/tutorials/WRITING_TESTS.md` | Project-specific patterns: `.claude/rules/testing.md`

## Plugin Installer

Two-package architecture: npm (installer) copies commands/skills/agents to `~/.claude/`, PyPI (server) runs via `uvx`. Same package name, different registries.

```bash
npx video-research-mcp@latest              # install plugin (copies markdown files + .mcp.json)
npx video-research-mcp@latest --check      # dry-run
npx video-research-mcp@latest --uninstall  # remove
```

To add a command/skill/agent: create file, add to `FILE_MAP` in `bin/lib/copy.js`, run `node bin/install.js --global`.

> Deep dive: `docs/PLUGIN_DISTRIBUTION.md` (FILE_MAP, manifest tracking, discovery mechanism, complete inventory)

## Env Vars

Canonical source: `config.py:ServerConfig`. Key variables:

| Variable | Default | Notes |
|----------|---------|-------|
| `GEMINI_API_KEY` | (required) | Also used as YouTube fallback |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | |
| `GEMINI_FLASH_MODEL` | `gemini-3-flash-preview` | |
| `DEEP_RESEARCH_AGENT` | `deep-research-pro-preview-12-2025` | Interactions API agent ID |
| `WEAVIATE_URL` | `""` | Empty = knowledge store disabled |
| `WEAVIATE_API_KEY` | `""` | Required for Weaviate Cloud |
| `GEMINI_SESSION_DB` | `""` | Empty = in-memory only |
| `RERANKER_ENABLED` | `""` | Auto-enabled when `COHERE_API_KEY` set |
| `COHERE_API_KEY` | `""` | Enables Cohere reranker in knowledge_search |
| `FLASH_SUMMARIZE` | `"true"` | Use Flash model for summarization |
| `GEMINI_TRACING_ENABLED` | `""` | Enable MLflow tracing |
| `MLFLOW_TRACKING_URI` | `""` | MLflow server URI |
| `MLFLOW_EXPERIMENT_NAME` | `""` | MLflow experiment name |
| `EXPLAINER_PATH` | `""` | Path to cloned video_explainer repo |
| `EXPLAINER_TTS_PROVIDER` | `"mock"` | mock, elevenlabs, openai, gemini, edge |
| `ELEVENLABS_API_KEY` | `""` | Required for elevenlabs TTS |
| `OPENAI_API_KEY` | `""` | Required for openai TTS |

All servers auto-load `~/.config/video-research-mcp/.env` at startup. Process env vars always take precedence over the config file. This ensures keys are available in any workspace, even without direnv.

All other config (thinking level, temperature, cache dir/TTL, session limits, retry params, YouTube API key) has sensible defaults — see `config.py` or `docs/ARCHITECTURE.md` §10.

## Archive

`archive/` (gitignored) contains development artifacts moved out of the working tree: completed design docs, code reviews, bug reports (now in GitHub Issues), audit snapshots, and research notes. See `archive/INDEX.md` for a full inventory.

## Developer Docs

| Document | Contents |
|----------|----------|
| `docs/ARCHITECTURE.md` | Full technical manual — 13 sections covering every pattern and module |
| `docs/DIAGRAMS.md` | Server hierarchy, GeminiClient flow, session lifecycle, Weaviate data flow |
| `docs/tutorials/GETTING_STARTED.md` | Install, configure, first tool call |
| `docs/tutorials/ADDING_A_TOOL.md` | Step-by-step tool creation with checklist |
| `docs/tutorials/WRITING_TESTS.md` | Fixtures, patterns, running tests |
| `docs/tutorials/KNOWLEDGE_STORE.md` | Weaviate setup, 12 collections, 8 knowledge tools |
| `docs/PLUGIN_DISTRIBUTION.md` | Two-package architecture, FILE_MAP, discovery, full inventory |
| `docs/PUBLISHING.md` | Dual-registry publishing guide with version sync policy |
| `docs/RELEASE_CHECKLIST.md` | Copy-paste checklist for each release |
| `CHANGELOG.md` | Release history in Keep a Changelog format |
