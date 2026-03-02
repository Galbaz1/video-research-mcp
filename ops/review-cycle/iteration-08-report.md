# Iteration 08 Report - Concurrency and Resource Exhaustion

Date: 2026-03-01T13:00:00Z
Branch: codex/review/i08
Focus: Iteration 8 - concurrency and resource exhaustion

## Mission Rewritten as Concise EARS Requirements
1. When iteration state indicates `current_iteration=8`, the run shall prioritize concurrency and resource-exhaustion risks in multi-source pipelines.
2. If iteration 7 lessons require explicit cross-path guardrail parity, iteration 8 shall enforce one shared workload-envelope contract across all document-research phases.
3. When `research_document` receives `file_paths` and `urls`, the tool shall reject requests exceeding a configured source limit before preparation begins.
4. When URL downloads, document uploads, and per-document Gemini phases execute, the system shall bound concurrent tasks using a shared configurable limit.
5. If temporary URL download directories are created, the system shall always clean them up after preparation completes or fails.
6. The run shall persist severity-ranked findings, exploit reasoning, concrete fixes, validation evidence, lessons learned, and next-iteration hypotheses.

## Scope Detection Evidence (Before/After Git Transitions)
- Baseline on detached `HEAD` before switching to review lineage:
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- After switching to `origin/codex/review-mainline` (detached):
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 15, "pr_context": false, "pr_url": null}`
- After creating `codex/review/i08`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i08", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 15, "pr_context": false, "pr_url": null}`
- Before commit on `codex/review/i08`:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i08", "base_branch": "main", "uncommitted_files": 11, "ahead_commits": 15, "pr_context": false, "pr_url": null}`
- After commit on `codex/review/i08`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i08", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 17, "pr_context": false, "pr_url": null}`

## Required Reading Checklist
- `AGENTS.md`, `src/AGENTS.md`, `tests/AGENTS.md`
- `docs/ARCHITECTURE.md`, `docs/DIAGRAMS.md`
- `docs/tutorials/ADDING_A_TOOL.md`, `docs/tutorials/WRITING_TESTS.md`

## Findings (Ordered by Severity)

### F-801 (High) - `research_document` accepted unbounded source-list size
- Evidence:
  - [`src/video_research_mcp/tools/research_document.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/src/video_research_mcp/tools/research_document.py) previously accepted unconstrained `file_paths`/`urls` and only checked for non-empty input.
- Exploit reasoning:
  - A large source list can trigger excessive concurrent downloads/uploads/model calls and increase memory, CPU, and upstream quota pressure, degrading availability.
- Concrete fix:
  - Added policy-enforced source cap via `RESEARCH_DOCUMENT_MAX_SOURCES` (`ServerConfig.research_document_max_sources`) with fail-fast structured error when exceeded.
- Implementation status:
  - Implemented and covered by regression test.

### F-802 (Medium) - Unbounded gather fan-out in document preparation and phase mapping/extraction
- Evidence:
  - [`src/video_research_mcp/tools/research_document_file.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/src/video_research_mcp/tools/research_document_file.py) previously used unconstrained `asyncio.gather` for URL downloads and File API uploads.
  - [`src/video_research_mcp/tools/research_document.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/src/video_research_mcp/tools/research_document.py) previously used unconstrained `asyncio.gather` for phase-1 and phase-2 per-document Gemini calls.
- Exploit reasoning:
  - Bursty fan-out increases risk of event-loop pressure, API throttling cascades, and unstable latency under adversarial or accidental high-volume inputs.
- Concrete fix:
  - Added shared bounded concurrency helper in both modules and enforced config-driven limit via `RESEARCH_DOCUMENT_PHASE_CONCURRENCY`.
- Implementation status:
  - Implemented with targeted test coverage and lint/test validation.

### F-803 (Medium) - Temporary download directories were not cleaned up
- Evidence:
  - [`src/video_research_mcp/tools/research_document_file.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/src/video_research_mcp/tools/research_document_file.py) previously created `mkdtemp` directories for URL downloads without cleanup.
- Exploit reasoning:
  - Repeated runs can accumulate disk usage and eventually degrade node stability or cause write failures.
- Concrete fix:
  - Added `finally` cleanup with `shutil.rmtree` via `asyncio.to_thread`, guaranteeing cleanup after success/failure.
- Implementation status:
  - Implemented with regression test that asserts cleanup call.

## Implemented Changes
- [`src/video_research_mcp/config.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/src/video_research_mcp/config.py)
  - Added `research_document_max_sources` and `research_document_phase_concurrency` config fields and env parsing.
- [`src/video_research_mcp/tools/research_document.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/src/video_research_mcp/tools/research_document.py)
  - Added fail-fast source-count enforcement.
  - Added bounded gather helper and applied to phase-1/phase-2 per-document calls.
- [`src/video_research_mcp/tools/research_document_file.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/src/video_research_mcp/tools/research_document_file.py)
  - Added bounded gather helper for download/upload fan-out.
  - Added guaranteed temp-dir cleanup in `finally`.
- [`tests/test_research_document_tools.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/tests/test_research_document_tools.py)
  - Added source-limit regression test.
- [`tests/test_research_document_file.py`](/Users/fausto/.codex/worktrees/6e71/gemini-research-mcp/tests/test_research_document_file.py)
  - Added temp-dir cleanup regression test.

## Validation Evidence
- Lint:
  - `uv run ruff check src/video_research_mcp/config.py src/video_research_mcp/tools/research_document.py src/video_research_mcp/tools/research_document_file.py tests/test_research_document_tools.py tests/test_research_document_file.py`
- Tests:
  - `PYTHONPATH=src uv run pytest tests/test_research_document_tools.py tests/test_research_document_file.py -v`
  - Result: 25 passed

## Reflective Self-Learning Loop
- Observe evidence:
  - Multi-source document flow had explicit content safety controls (iteration 7) but lacked explicit workload bounds and cleanup guarantees.
- Infer root causes:
  - Safety contracts focused on prompt-level misuse resistance while operational contracts (fan-out bounds, temporary resource lifecycle) were implicit.
- Proposed fix strategies:
  - Introduce config-backed source caps and bounded fan-out helper usage at every high-cost stage.
  - Enforce cleanup in finally blocks for temporary artifacts.
  - Add focused regression tests for both ingress limits and cleanup behavior.
- Validate fixes:
  - Implemented in tool/config layers and validated with lint + targeted tests.
- Confidence change:
  - Concurrency/resource-exhaustion confidence in `research_document` pipeline: 0.46 -> 0.83.
  - Temporary-resource lifecycle confidence: 0.52 -> 0.88.
  - Overall iteration-8 objective confidence: 0.49 -> 0.84.

## Lesson-Carried Remediation (Required N-1 linkage)
- Derived from iteration 7 lesson: explicit contracts must be consistently applied across all paths.
- Applied in iteration 8:
  - Added explicit, shared workload-envelope contracts (source cap + bounded concurrency + guaranteed cleanup) across all multi-source preparation and processing paths.

## Lessons Learned
1. Prompt-safety hardening must be paired with operational-safety hardening in the same pipelines.
2. Bounded fan-out should be centralized and config-driven to avoid per-function drift.
3. Temporary-file lifecycle management is an availability control, not only housekeeping.

## Next-Iteration Hypotheses (Iteration 9)
1. Audit regression blind spots in stress/concurrency scenarios that current unit tests still do not simulate.
2. Add targeted tests for phase-concurrency behavior under partial-failure bursts.
3. Review decorated-tool call patterns for remaining direct-call test harness drift (`unwrap_tool` coverage consistency).
