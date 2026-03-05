# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.7] - 2026-03-05

### Fixed

- **comment-analyst agent** — changed model from `haiku` (banned) to `opus` per global policy

## [0.3.6] - 2026-03-05

### Added

- **`knowledge_schema` tool** — returns property names, types, and descriptions for any collection without requiring a Weaviate connection. Call before `knowledge_ingest` to discover expected fields

### Improved

- **`knowledge_ingest` error messages** — unknown-property errors now include allowed `name:type` pairs and a hint to call `knowledge_schema`, eliminating trial-and-error loops

## [0.3.5] - 2026-03-05

### Changed

- **3x faster server startup** — lazy-import `google-genai` and `weaviate` SDKs; deferred from module load to first tool call (fixes Glama Docker build timeout)

## [0.3.4] - 2026-03-05

### Added

- **`__main__.py` entry point** — enables `python -m video_research_mcp` for Docker and direct invocation (fixes Glama Docker build)

### Fixed

- **Stale `__version__`** — `__init__.py` now tracks the actual release version instead of hardcoded `0.1.0`

## [0.3.3] - 2026-03-05

### Added

- **Gemini Deep Research Agent tools** — added `research_web`, `research_web_status`, `research_web_followup`, and `research_web_cancel` for long-running web-grounded research via the Interactions API
- **DeepResearchReports knowledge collection** — stores completed deep-research reports, usage metadata, and follow-up Q&A; includes cross-references to `ResearchFindings` and `WebSearchResults`
- **`DEEP_RESEARCH_AGENT` config variable** — explicit environment variable and runtime validation for selecting the Interactions API agent
- **`/gr:research-deep` command** — interview-driven command workflow for launching and iterating on Deep Research runs
- **`research-brief-builder` skill** — brief-quality checklist and challenge templates for high-signal research prompts

### Fixed

- Deep Research follow-up tool annotation now correctly marks write behavior (`readOnlyHint=false`)
- Deep Research launch tracking now evicts stale IDs (TTL + cap) and cleans terminal interactions to avoid in-memory growth
- Follow-up results are now persisted to Weaviate (`follow_ups_json`) instead of storing only follow-up IDs

### Changed

- `researcher` agent now includes Deep Research and knowledge-search tools in its default workflow
- Installer copy map now ships the new `/gr:research-deep` command and `research-brief-builder` skill

## [0.3.2] - 2026-03-03

### Added

- **`/gr:getting-started` command** — interactive first-time setup: verifies config, runs smoke test, shows all available commands and optional features
- Installer "Next steps" now links to Gemini API key page and directs users to `/gr:getting-started`

### Fixed

- **Installer: removed unpublished MCP servers** — `video-explainer-mcp` and `video-agent-mcp` are not on PyPI; the installer was creating broken server entries that failed on startup for every new user
- **Installer: removed unresolvable env placeholders** — `${MLFLOW_TRACKING_URI}` was written as a literal string in `.mcp.json` (no shell expansion); server reads config from `~/.config/video-research-mcp/.env` instead

## [0.3.1] - 2026-03-03

### Added

- **Local filesystem boundary enforcement** — new `local_path_policy.py` validates all local file paths against `LOCAL_FILE_ACCESS_ROOT`; applied in `video_file`, `video_batch`, `research_document_file` (PR #41)
- **Infra mutation auth gating** — `infra_configure` now requires `auth_token` matching `INFRA_ADMIN_TOKEN` env var; `infra_cache` read-only ops remain unauthenticated (PR #41)
- **Prompt injection guardrails** — system prompts for content, research, research_document, and knowledge tools now include injection defense instructions (PR #41)
- **`PERMISSION_DENIED` error category** — new error classification in `errors.py` for `PermissionError`, `TimeoutError`, `httpx.TimeoutException`, `httpx.NetworkError` (PR #41)
- **`DocumentPreparationIssue` model** — surfaces file preparation problems in `research_document` reports (PR #41)
- **Security tests** — adversarial prompt corpus coverage (#43), policy-inheritance guard tests (#44), smoke suite extension (#45)
- 5 new config fields: `research_document_max_sources`, `research_document_phase_concurrency`, `local_file_access_root`, `infra_mutations_enabled`, `infra_admin_token`

### Fixed

- **Atomic cache writes** — `cache.py` and `context_cache.py` now write via UUID temp files to prevent corruption on concurrent access (PR #41)
- **Sensitive config redaction** — `infra_configure` output redacts `GEMINI_API_KEY`, `WEAVIATE_API_KEY`, `COHERE_API_KEY`, `INFRA_ADMIN_TOKEN` (PR #41)
- Weaviate setup skill: minor fix in SKILL.md

### Changed

- `url_policy.py` — expanded URL validation with stricter enforcement
- `research_document.py` — concurrency limits via config fields
- README: clarify plugin = MCP servers + commands + skills + agents
- Docs: fix tool counts (41 total), review-cycle finalization

## [0.3.0] - 2026-03-01

### Added

- **video-agent-mcp** — new package: parallel scene generation via Claude Agent SDK (PR #16)
- **video-explainer-mcp** — new package: 15 tools for synthesizing explainer videos from research (PR #10)
- **MLflow tracing** — `@trace` decorator on all 24 tools, MLflow MCP server plugin, `/gr:traces` command, and health check in `/gr:doctor` (PR #12)
- **Cohere reranking** — optional server-side reranking via Cohere when `COHERE_API_KEY` is set. Auto-detected; disable with `RERANKER_ENABLED=false` (PR #18)
- **Flash summarization** — Gemini Flash post-processes search hits to score relevance, generate one-line summaries, and trim unnecessary properties. Disable with `FLASH_SUMMARIZE=false` (PR #18)
- **Media asset pipeline** — local file paths propagated through video/content pipelines, shared `gr/media` asset directory with recall actions (PR #17, #18)
- **`generate_json_validated()`** — dual-path JSON validation in `GeminiClient` (PR #19, pending)
- **Project-level git rules** — branch protection policy in `.claude/rules/git.md`

### Changed

- CI: bumped `actions/checkout` v4 to v6, `astral-sh/setup-uv` v5 to v7, `actions/setup-python` v5 to v6 (PRs #13, #14, #15)
- Knowledge search: `rerank_score` and `summary` fields on `KnowledgeHit`
- Weaviate schema: local media path fields added to collections (PR #17)

### Fixed

- MCP transport JSON string deserialization for list parameters in `knowledge_ingest` and `knowledge_search`

### Deprecated

- **`knowledge_query`** — use `knowledge_search` instead, which now includes Cohere reranking and Flash summarization for better results with lower token usage. `knowledge_ask` (AI-powered Q&A) is unaffected

## [0.2.0] - 2026-02-28

### Added

- **Knowledge store** — 7 Weaviate collections with write-through storage from every tool
- **Knowledge tools** — `knowledge_search`, `knowledge_related`, `knowledge_stats`, `knowledge_fetch`, `knowledge_ingest` for querying stored results
- **QueryAgent tools** — `knowledge_ask` and `knowledge_query` powered by `weaviate-agents` (optional dependency)
- **YouTube tools** — `video_metadata`, `video_comments`, `video_playlist` via YouTube Data API v3
- **Context caching** — automatic Gemini cache pre-warming after `video_analyze` for both YouTube and local files; session reuse via `ensure_session_cache()`. Large local files (>=20MB) are context-cached automatically on session creation
- **Session persistence** — optional SQLite backend for video Q&A sessions (`GEMINI_SESSION_DB`)
- **Plugin installer** — npm package that copies commands, skills, and agents to `~/.claude/` and configures MCP server
- **MLflow MCP plugin** — `/gr:traces` command for querying, tagging, and evaluating traces; `mlflow-traces` skill with field path reference and `extract_fields` discipline; `mlflow-mcp` server auto-installed via `uvx`; MLflow health check in `/gr:doctor`
- **Diagnostics** — `/gr:doctor` command for MCP wiring, API key, Weaviate, and MLflow connectivity checks
- **Retry logic** — exponential backoff with jitter for Gemini API calls
- **Batch analysis** — `video_batch_analyze` for concurrent directory-level video processing
- **PyPI metadata** — classifiers, project URLs, version alignment with npm

### Changed

- Bumped version from 0.1.0 to 0.2.0 (aligned with npm package)
- Unified tool count to 23 across all documentation

## [0.1.0] - 2026-02-01

### Added

- **Core server** — FastMCP root with 7 mounted sub-servers (stdio transport)
- **Video analysis** — `video_analyze`, `video_create_session`, `video_continue_session` for YouTube URLs and local files
- **Research tools** — `research_deep` (multi-phase with evidence tiers), `research_plan`, `research_assess_evidence`
- **Content tools** — `content_analyze`, `content_extract` with caller-provided JSON schemas
- **Search** — `web_search` via Gemini grounding with source citations
- **Infrastructure** — `infra_cache` (view/list/clear), `infra_configure` (runtime model/thinking/temperature)
- **Structured output** — `GeminiClient.generate_structured()` with Pydantic model validation
- **Thinking support** — configurable thinking levels (minimal/low/medium/high) via `ThinkingConfig`
- **Error handling** — `make_tool_error()` with category, hint, and retryable flag (tools never raise)
- **Caching** — file-based analysis cache with configurable TTL

[Unreleased]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.3...HEAD
[0.3.3]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Galbaz1/video-research-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Galbaz1/video-research-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.1.0
