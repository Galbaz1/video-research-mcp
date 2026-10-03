# Changelog

This file records notable changes by release. Versioned entries describe the
behavior and validation reported at that time; use current guides for installation
and provider configuration.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Install all 22 packaged Claude skills, including six previously omitted workflows,
  with their contracts, descriptors, helper scripts and license texts. Preserve
  edited and unmanaged resources through upgrades and recovery, and check complete
  packed-skill coverage in CI.

## [0.8.0-rc.1] - 2026-10-02

### Added

- Native Codex plugin packaging with 22 bundled skills and an exact core MCP
  runtime pin. Codex marketplace installation supports the packed local candidate
  and the matching npm version without running the Claude installer.
- The multimodal programme's current core exposes 90 tools, including local image
  inspection/cropping, structured audio/video workflows, evidence-aware research,
  and optional adapters. Adapter prerequisites and evidence limitations remain
  documented; packaging does not qualify an external runtime or model.

### Fixed

- Corrected the packaged video-to-skill helper paths for native Codex installs
  while preserving the existing Claude layout.
- Built-wheel verification now compares every MCP tool contract with candidate
  source instead of requiring an obsolete tool count, and retains configuration
  redaction and actual local image-crop checks.

- Reconcile FFmpeg 6.1 MP3 encoder padding against exact packet timing so complete
  tracks export successfully while truncated tracks remain rejected.
- Exclude the uncleared external renderer subtree from the core source archive
  and reject its payload in archive checks, including equivalent path spellings.

### Acceptance boundary

- This is a core/plugin release candidate. Companion packages retain their own
  versions. Human source audit, held-out comparison, live-provider quality and
  blocked native-runtime qualifications remain open; no programme-wide acceptance
  or superiority claim is implied.

## [0.7.1] - 2026-09-30

### Changed

- Rewrote the README and reader-facing documentation around installation, daily
  use, architecture, contribution, and release tasks. Added a documentation index
  and preserved historical findings, release records, and reporting commitments.
- Corrected configuration, knowledge-store, cache, installer, and companion setup
  explanations against the implementation. Companion package patch versions now
  include their rewritten READMEs.
- Removed model-specific claims from package descriptions and server discovery
  instructions; configured model selection remains the runtime authority.
- Repaired the upstream renderer submodule's public clone URL and pinned revision.
  Aligned companion refinement, rendering, and TTS selectors with that CLI.
  The core PyPI 0.7.1 archives were published before this source-only and companion
  follow-up; their immutable files remain unchanged.

### Security

- Redacted the Semantic Scholar API key from read-only `infra_configure` responses,
  alongside the existing provider secrets. Expanded the secret-redaction regression
  check and built-wheel smoke to cover this field.

## [0.7.0] - 2026-09-29

### Changed

- Default research and summary models now use stable Gemini 3.8 Flash. Unsupported
  minimal thinking requests return an actionable validation error. Explicit-cache
  workflows retain Google's supported generateContent endpoint.
- Upgraded all three Python packages to current stable dependencies, including
  FastMCP 4 and Google GenAI SDK 2, with explicit API-major bounds and refreshed
  locks. Expanded locked CI to companion packages and Python 3.14.
- Global installer registration now uses Claude Code user scope in
  `~/.claude.json`, preserves custom environment/settings and local companion
  servers, and refreshes the server package during resolution. Updated Playwright
  MCP and moved to maintained Node runtimes.
- Audited and simplified skill/provider guides, aligned onboarding with installed
  servers, inherited configured orchestration models, and removed obsolete media
  API instructions. Added a bounded plugin-maintenance skill.
- GitHub release creation now requires passing CI, synchronized versions,
  matching release notes and valid build artifacts. Tags outside main publish
  as prereleases. GitHub source publication does not upload to PyPI or npm.

### Fixed

- Preserved SDK thought signatures and full content through video-session
  history and SQLite serialization.
- Read current Deep Research interaction steps, citations, and error lists;
  preserved typed failures instead of treating absent legacy outputs as success.
- Rejected malformed or escaping installer manifests, preserved unowned/customized
  files, and retained ownership evidence for modified obsolete files.
- Companion scene generation now isolates child settings, enforces terminal SDK
  success and budgets, and uses a valid configurable Claude model.
- Companion render acceptance requires a fresh nonempty artifact; cancellation
  stops and joins subprocess work. Injection filenames cannot escape projects.
- Removed committed documentation conflict markers and unsafe visualization
  cleanup of user directories or unrelated local processes.

## [0.6.1] - 2026-05-21

### Changed

- **Default Gemini model: `gemini-3.5-flash`** with `thinking_level="medium"` (previously `gemini-3.1-pro-preview` / `high`). Both `default_model` and `flash_model` point at 3.5 Flash; preset opt-ins (`best`, `stable`, `budget`) remain available for Pro 3.1, Pro 3, and the legacy 3-flash-preview. The release rationale cited Google's benchmarks as showing better results than 3.1 Pro at about 4× speed and less than half the cost.
- **`.claude-plugin/plugin.json` version sync** — was 12 versions stale at 0.3.3; now part of the documented version-sync policy in `docs/PUBLISHING.md` alongside `pyproject.toml` and `package.json`.

### Added

- **Ollama vectorizer** for Weaviate (`text2vec-ollama`) — local embedding alternative to OpenAI / built-in (#61, community contribution).
- **`.github/workflows/release.yml`** — auto-creates GitHub Release with CHANGELOG section on any `v*.*.*` tag push. Fills the gap that left v0.4.0 through v0.6.0 without release pages (now backfilled).

### Security

- **31 Dependabot alerts resolved** (3 critical, 10 high, 14 medium, 4 low) via `uv lock --upgrade`. Includes fastmcp 3.0.2 → 3.3.1 (Gemini-CLI command injection), python-multipart 0.0.22 → 0.0.29 (DoS), python-dotenv 1.2.1 → 1.2.2 (symlink following), cryptography 46.0.5 → 48.0.0 (buffer overflow), authlib 1.6.8 → 1.7.2 (CSRF + OIDC). google-genai bumped 1.65 → 2.5.0 (major; API remained compatible with this project's usage, with 781 tests reported passing).

## [0.6.0] - 2026-03-25

### Added

- **Media production skills** — 5 new plugin skills for end-to-end AI video production:
  - `tts-production` — ElevenLabs TTS voice-over with API patterns, voice presets, and FFmpeg audio recipes
  - `ffmpeg-production` — Video/audio processing reference with post-processing chain, platform presets, and codec selection
  - `video-generation` — Provider-agnostic video generation (Veo/Sora) with selection matrix and draft-to-final workflow
  - `video-production` — Cinematic multi-shot orchestration with style anchors, 4 chaining patterns, and frame-level QA
  - `image-generation` — Style anchor and prompt optimization for mcp-image (Subject-Context-Style structure)
- Skill descriptions stayed under 200 characters with negative qualifiers; bodies stayed under 2,000 words, with detailed material in `references/` (Level 3 progressive disclosure).

### Changed

- Plugin skill count: 7 → 12
- FILE_MAP entries: 34 → 42

## [0.5.0] - 2026-03-17

### Added

- **Semantic Scholar integration** — 5 new tools: `research_paper_search`, `research_paper_details`, `research_paper_citations`, `research_paper_recommendations`, `research_author_search`
- **AcademicPapers Weaviate collection** with deterministic UUIDs
- **Automatic knowledge graph extraction** — `content_analyze`, `video_analyze`, `research_deep`, `research_web`, `research_document`, `content_batch_analyze` now auto-extract concepts and relationships
- **ConceptKnowledge + RelationshipEdges** collections populated automatically
- **S2-specific error categories** (`S2_RATE_LIMITED`, `S2_NOT_FOUND`)

### Changed

- Collection count: 12 → 13 (AcademicPapers)
- Tool count: 28 → 33

### Fixed

- Weaviate vectorizer config mismatch (`text2vec-weaviate` → `text2vec-openai`)

## [0.4.4] - 2026-03-13

### Fixed

- **Vectorizer auto-detection** — default without `OPENAI_API_KEY` is now `weaviate` (built-in embeddings) instead of `openai`, which had silently failed for Docker users without an OpenAI key

### Added

- **Startup warning** — logs a warning when `WEAVIATE_VECTORIZER=openai` is active but `OPENAI_API_KEY` is not set
- **Env template keys** — `WEAVIATE_VECTORIZER` and `WEAVIATE_AUTO_MIGRATE` added to the installer env template with documentation comments

### Changed

- **Weaviate setup skill** — Step 3 now shows deployment-specific env blocks (Docker vs Cloud) with vectorizer guidance
- **Knowledge Store docs** — replaced broken `docker run` command with docker-compose snippet matching the setup skill

## [0.4.3] - 2026-03-09

### Fixed

- **`_extract_report` turn.text fallback** — Deep Research reports delivered via `turn.text` (instead of `turn.content[].text`) were silently lost; now both formats are captured
- **Transient 403 retry in `research_web_status`** — polling now retries up to 3 times with backoff on transient 403 errors rather than failing immediately
- **Concurrency guard on `research_web`** — prevents launching a second Deep Research task while one is active (API allows only 1 concurrent task per key); returns actionable error with the active interaction ID
- **Timeout heuristic in `/gr:research-deep`** — skill now warns after 20 min and suggests cancel+retry after 30 min of polling without completion

## [0.4.2] - 2026-03-09

### Fixed

- **`/gr:doctor` Serena tool leakage** — added explicit tool discipline section preventing the command from selecting Serena's `Read File` MCP tool instead of Claude Code's built-in `Read` when both are available in the session
- **Banned `model: haiku`** — replaced with `model: sonnet` in 4 commands (`doctor`, `getting-started`, `models`, `explain-status`)

## [0.4.1] - 2026-03-09

### Fixed

- **MCP server startup hang** — added 2-second TCP reachability probe before MLflow setup. Prevents indefinite hang when `MLFLOW_TRACKING_URI` points to an unreachable server (e.g., stopped MLflow instance)
- **`__init__.__version__`** — synced with `pyproject.toml` (was stuck on `0.3.9`)

## [0.4.0] - 2026-03-07

### Added

- **`/gr:advisor` command** — workflow advisor that recommends the optimal `/gr` command for any task. Checks prior work via knowledge store before recommending. Three invocation channels: explicit command, auto-invoked skill, and spawnable agent
- **`gr-advisor` skill** — auto-triggers when the user expresses research, video, or content analysis intent without specifying a `/gr` command. Prevents suboptimal tool choices (e.g., `/gr:research-deep` for quick questions)
- **`gr-advisor` agent** — sonnet-powered subagent for programmatic workflow routing within agent teams
- **Agent/Skill/Command conventions** in CLAUDE.md — documents required frontmatter fields for plugin contributors

### Changed

- **CLAUDE.md** — added minimal `/gr Plugin Routing` section: recall-first pattern and cost-awareness for `/gr:research-deep`

## [0.3.9] - 2026-03-05

### Fixed

- **AskUserQuestion YAML examples** — aligned all 4 code block examples across commands/skills with actual tool schema (`questions` array with `multiSelect` boolean)

## [0.3.8] - 2026-03-05

### Improved

- **`/gr:ingest` command** — now calls `knowledge_schema` before ingesting to discover exact property names; removed hardcoded property table that could drift from schema
- **video-research skill** — added schema-first convention for knowledge ingest workflows

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

- **3× faster server startup** — lazy-import `google-genai` and `weaviate` SDKs; deferred from module load to first tool call (fixes Glama Docker build timeout)

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
- Deep Research launch tracking now evicts stale IDs (TTL + cap) and cleans up terminal interactions to avoid in-memory growth
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
- **PyPI metadata** — added classifiers, project URLs, and version alignment with npm

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
- **Structured output** — added `GeminiClient.generate_structured()` with Pydantic model validation
- **Thinking support** — configurable thinking levels (minimal/low/medium/high) via `ThinkingConfig`
- **Error handling** — `make_tool_error()` with category, hint, and retryable flag (tools never raise)
- **Caching** — file-based analysis cache with configurable TTL

[Unreleased]: https://github.com/Galbaz1/video-research-mcp/compare/v0.7.0...HEAD
[0.7.1]: https://pypi.org/project/video-research-mcp/0.7.1/
[0.7.0]: https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.7.0
[0.6.1]: https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.6.1
[0.6.0]: https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.6.0
[0.5.0]: https://github.com/Galbaz1/video-research-mcp/compare/v0.4.4...v0.5.0
[0.4.4]: https://github.com/Galbaz1/video-research-mcp/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/Galbaz1/video-research-mcp/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/Galbaz1/video-research-mcp/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/Galbaz1/video-research-mcp/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.9...v0.4.0
[0.3.3]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Galbaz1/video-research-mcp/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Galbaz1/video-research-mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Galbaz1/video-research-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.1.0
[0.3.9]: https://pypi.org/project/video-research-mcp/0.3.9/
[0.3.8]: https://pypi.org/project/video-research-mcp/0.3.8/
[0.3.7]: https://pypi.org/project/video-research-mcp/0.3.7/
[0.3.6]: https://pypi.org/project/video-research-mcp/0.3.6/
[0.3.5]: https://pypi.org/project/video-research-mcp/0.3.5/
[0.3.4]: https://pypi.org/project/video-research-mcp/0.3.4/
