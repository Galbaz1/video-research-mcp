# AGENTS.md

## Scope

Codex project instructions equivalent to this repo's Claude setup.

- Root guidance lives here.
- Source-code specific guidance lives in `src/AGENTS.md`.
- Test-specific guidance lives in `tests/AGENTS.md`.

This layout mirrors `.claude/rules/*.md` path scoping using Codex's directory-based AGENTS discovery.

## What This Is

A monorepo with 3 MCP servers (45 tools total):

1. **video-research-mcp** (root) — 28 tools for video analysis, deep research, content extraction, web search, and context caching. Powered by Gemini 3.1 Pro (`google-genai`) and YouTube Data API v3.
2. **video-explainer-mcp** (`packages/video-explainer-mcp/`) — 15 tools for synthesizing explainer videos.
3. **video-agent-mcp** (`packages/video-agent-mcp/`) — 2 tools for parallel scene generation via Claude Agent SDK.

Python >= 3.11.

## Commands

```bash
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
uv run pytest tests/ -v
uv run pytest tests/ -k "video_analyze" -v
uv run ruff check src/ tests/
GEMINI_API_KEY=... uv run video-research-mcp
scripts/detect_review_scope.py --json
```

## Code Review Trigger Protocol

Use `scripts/detect_review_scope.py --json` before review/audit/check requests and after major git-state transitions.

Priority when multiple states apply:
1. `uncommitted`
2. `pr`
3. `commits`

Do not mix review scopes in one pass unless explicitly requested.

## Architecture

`server.py` mounts sub-servers onto `FastMCP("video-research")`:

- `tools/video.py`: video analysis/session/batch tools
- `tools/youtube.py`: metadata/comments/playlist tools
- `tools/research.py`: deep research/planning/evidence + deferred registration for `research_document` and `research_web*` tools
- `tools/research_web.py`: Deep Research Agent tools (`research_web`, status/follow-up/cancel)
- `tools/content.py`: content analyze/extract + `content_batch_analyze` (via deferred import)
- `tools/search.py`: web search tool
- `tools/infra.py`: infra/cache/config tools
- `tools/knowledge/`: knowledge tools

Supporting modules: `video_cache.py`, `video_batch.py`, `research_document_file.py` (File API upload + URL download).

Core project patterns:
- Instruction-driven tools (`instruction` + optional `output_schema`)
- Structured output via `GeminiClient.generate_structured(...)`
- Tools return error dicts (`make_tool_error()`), no exception escape
- Write-through Weaviate storage when configured (non-fatal)
- Context caching with prewarm + session reuse
- MLflow tracing via `@trace()` decorator on all tools (no-op when mlflow not installed)
- Knowledge search with optional Cohere reranking + Flash summarization

## Conventions

### New Tools

Every tool must have:
1. `ToolAnnotations` on the decorator
2. `Annotated[...]` params with `Field(...)`
3. Google-style docstring
4. Structured output via `GeminiClient.generate_structured(...)`

Shared types belong in `types.py`.

### Docstrings

Google-style docstrings are required on modules, public classes/functions/methods, and non-obvious private helpers. Keep docstrings concise and factual.

### File Size

Aim for ~300 lines of executable production code per file (excluding docstrings/comments/blanks). Test files may go to ~500 lines.

## Dependency Policy

Pin to the major version actually used. Do not use cross-major constraints where APIs differ.

Key constraints in this project:
- `fastmcp >=3.0.2`
- `google-genai >=1.57`
- `google-api-python-client >=2.100`
- `httpx >=0.27`
- `pydantic >=2.0`
- `weaviate-client >=4.19.2`
- `mlflow-tracing >=3.0` (optional [tracing])
- `weaviate-agents >=1.2.0` (optional [agents])
- `pytest >=8.0`
- `pytest-asyncio >=1.0`
- `ruff >=0.9`

When updating dependencies:
1. Update `pyproject.toml`
2. Re-resolve deps
3. Remove obsolete compatibility workarounds
4. Run full tests

## Testing Summary

Tests are unit-level with mocked Gemini. No tests should hit real APIs.

Primary fixtures and patterns are documented in `tests/conftest.py` and `docs/tutorials/WRITING_TESTS.md`.

## Plugin Installer Context

Two-package architecture:
- npm package copies commands/skills/agents to `~/.claude/`
- PyPI package runs MCP server via `uvx`

See `docs/PLUGIN_DISTRIBUTION.md` for details.

## Environment Variables

Canonical source: `config.py:ServerConfig`.

Main variables:
- `GEMINI_API_KEY` (required)
- `GEMINI_MODEL` (default `gemini-3.1-pro-preview`)
- `GEMINI_FLASH_MODEL` (default `gemini-3-flash-preview`)
- `DEEP_RESEARCH_AGENT` (default `deep-research-pro-preview-12-2025`)
- `WEAVIATE_URL` (empty disables knowledge store)
- `WEAVIATE_API_KEY`
- `GEMINI_SESSION_DB` (empty means in-memory sessions)
- `COHERE_API_KEY` (auto-enables reranker when set)
- `RERANKER_ENABLED` (override: true/false)
- `FLASH_SUMMARIZE` (default true)
- `GEMINI_TRACING_ENABLED` (default false)
- `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT_NAME`

## Key Docs

- `docs/ARCHITECTURE.md`
- `docs/DIAGRAMS.md`
- `docs/tutorials/GETTING_STARTED.md`
- `docs/tutorials/ADDING_A_TOOL.md`
- `docs/tutorials/WRITING_TESTS.md`
- `docs/tutorials/KNOWLEDGE_STORE.md`
- `docs/CODE_REVIEW_AUTOMATION.md`
- `docs/PLUGIN_DISTRIBUTION.md`
- `docs/PUBLISHING.md`
- `docs/RELEASE_CHECKLIST.md`
