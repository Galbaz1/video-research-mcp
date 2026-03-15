# Iteration 08 Security Review Report

Date: 2026-03-15T01:04:48Z  
Focus: Concurrency and resource exhaustion

## Scope Detection Snapshots
- Before transition from detached `HEAD`:
  - `{"mode":"none","reason":"No local changes and no ahead commits to review.","branch":"HEAD","base_branch":"main","uncommitted_files":0,"ahead_commits":0,"pr_context":false,"pr_url":null}`
- After switching to `codex/review-mainline`:
  - `{"mode":"commits","reason":"Branch is ahead of base with no local unstaged/uncommitted files.","branch":"codex/review-mainline","base_branch":"main","uncommitted_files":0,"ahead_commits":12,"pr_context":false,"pr_url":null}`
- Before switching to `codex/review/i07`:
  - `{"mode":"commits","reason":"Branch is ahead of base with no local unstaged/uncommitted files.","branch":"codex/review/i07","base_branch":"main","uncommitted_files":0,"ahead_commits":13,"pr_context":false,"pr_url":null}`
- After changes (working tree):
  - `{"mode":"uncommitted","reason":"Working tree has local changes.","branch":"codex/review/i07","base_branch":"main","uncommitted_files":2,"ahead_commits":13,"pr_context":false,"pr_url":null}`
- After commit + PR creation:
  - `{"mode":"pr","reason":"Branch has an open pull request.","branch":"codex/review/i07","base_branch":"main","uncommitted_files":0,"ahead_commits":14,"pr_context":true,"pr_url":"https://github.com/Galbaz1/video-research-mcp/pull/59"}`

## EARS Run Requirements (Concise)
1. When iteration state indicates `current_iteration=8`, the run shall prioritize concurrency and resource-exhaustion risks.
2. If iteration 7 lessons identify untrusted prompt-boundary gaps, iteration 8 shall implement at least one remediation directly derived from that lesson.
3. When document preparation performs parallel download or upload operations, the system shall enforce bounded concurrency.
4. If untrusted reshaped content is fed into a second-pass model prompt, the system shall explicitly mark it as untrusted and instruct the model to ignore embedded commands.
5. The run shall persist severity-ranked findings, exploit reasoning, implemented remediations, confidence deltas, and next-iteration hypotheses.

## Findings By Severity
### Medium
- ID: I08-F1
- Area: Prompt injection in second-pass schema reshaping
- Evidence:
  - Hardened prompt construction now at [`src/video_research_mcp/tools/content.py:207`](/Users/fausto/.codex/worktrees/0c25/gemini-research-mcp/src/video_research_mcp/tools/content.py:207).
  - Regression coverage at [`tests/test_content_tools.py:158`](/Users/fausto/.codex/worktrees/0c25/gemini-research-mcp/tests/test_content_tools.py:158).
- Exploit reasoning: Untrusted text returned from URL-context fetch can include instruction-smuggling payloads that bias schema reshaping.
- Fix status: Implemented in this run (derived from iteration 7 lesson).

### Medium
- ID: I08-F2
- Area: Resource exhaustion from unbounded document preparation fan-out
- Evidence:
  - Prior path used unbounded `asyncio.gather` over all URLs/paths in `_prepare_all_documents_with_issues`.
  - Bounded gather now enforced at [`src/video_research_mcp/tools/research_document_file.py:114`](/Users/fausto/.codex/worktrees/0c25/gemini-research-mcp/src/video_research_mcp/tools/research_document_file.py:114).
  - Concurrency cap test at [`tests/test_research_document_file.py:141`](/Users/fausto/.codex/worktrees/0c25/gemini-research-mcp/tests/test_research_document_file.py:141).
- Exploit reasoning: Large source lists can trigger excessive concurrent network/file operations, increasing memory/socket pressure and reducing service availability.
- Fix status: Implemented in this run.

## Implemented Changes
- Added explicit untrusted-data framing in content reshape fallback prompt:
  - `<UNTRUSTED_INSTRUCTION>` and `<UNTRUSTED_CONTENT>` delimiters.
  - Explicit anti-injection instructions and schema adherence constraints.
- Added bounded fan-out for document preparation:
  - Introduced `_DOC_PREPARE_CONCURRENCY = 4`.
  - Applied bounded execution to both URL download and File API upload stages.
- Added regression tests:
  - `test_url_fallback_hardens_untrusted_reshape_prompt`
  - `test_downloads_use_bounded_concurrency`

## Validation
- `uv run ruff check src/video_research_mcp/tools/content.py src/video_research_mcp/tools/research_document_file.py tests/test_content_tools.py tests/test_research_document_file.py`
- `PYTHONPATH=src uv run pytest tests/test_content_tools.py -k 'hardens_untrusted_reshape_prompt' -q`
- `PYTHONPATH=src uv run pytest tests/test_research_document_file.py -q`
- Result: pass (`1 passed, 16 deselected`; `15 passed`)

## Reflective Self-Learning Loop
- Observe: Iteration 7 left a documented prompt-boundary gap in `_reshape_to_schema`, and iteration-8 scan found unbounded parallelism in document prep.
- Infer root cause: Boundary-hardening patterns were applied selectively, and concurrency controls were inconsistent across batch pipelines.
- Propose strategy: Reuse explicit-untrusted framing from iteration 7 and existing bounded-concurrency design used in batch tools.
- Validate: Implemented both remediations with focused regression tests and lint/test verification.
- Confidence delta: 0.61 -> 0.84 (iteration-8 objective coverage), delivery confidence 0.84 -> 0.89 after validation.

## Lessons Learned
- Prompt-boundary controls should be applied uniformly to all multi-pass LLM flows, not only retrieval summarization paths.
- Any high-fanout async workflow should default to bounded concurrency, even in best-effort helper layers.

## Next-Iteration Hypotheses (Iteration 9)
1. Resolve test-harness drift where decorated tools are not directly callable in subset runs (`FunctionTool` mismatch).
2. Add regression contracts that validate both direct-call and tool-wrapper invocation paths for every tool module.

---

## Continuation Run (2026-03-15T04:xxZ)

### Scope Detection Snapshots
- Run start on active iteration branch (`codex/review/i07`):
  - `{"mode":"pr","reason":"Branch has an open pull request.","branch":"codex/review/i07","base_branch":"main","uncommitted_files":0,"ahead_commits":15,"pr_context":true,"pr_url":"https://github.com/Galbaz1/video-research-mcp/pull/59"}`
- After implementing continuation fixes:
  - `{"mode":"uncommitted","reason":"Working tree has local changes.","branch":"codex/review/i07","base_branch":"main","uncommitted_files":2,"ahead_commits":15,"pr_context":true,"pr_url":"https://github.com/Galbaz1/video-research-mcp/pull/59"}`

### Additional Findings By Severity
#### Medium
- ID: I08-F3
- Area: Resource exhaustion in per-document Gemini fan-out phases.
- Evidence:
  - Unbounded gather previously in `_phase_document_map(...)` and `_phase_evidence_extraction(...)`.
  - Bounded helper and cap now in [`src/video_research_mcp/tools/research_document.py`](/Users/fausto/.codex/worktrees/0c25/gemini-research-mcp/src/video_research_mcp/tools/research_document.py).
  - Regression coverage in [`tests/test_research_document_tools.py`](/Users/fausto/.codex/worktrees/0c25/gemini-research-mcp/tests/test_research_document_tools.py).
- Exploit reasoning: Multi-document requests can trigger high parallel API calls in mapping/evidence phases, increasing quota burn and runtime instability.
- Fix status: Implemented in this continuation run.

### Additional Implemented Changes
- Added `_DOC_PHASE_CONCURRENCY = 4` in `research_document` pipeline.
- Introduced `_gather_bounded(...)` in `research_document.py` and applied it to:
  - `_phase_document_map(...)`
  - `_phase_evidence_extraction(...)`
- Added regression tests:
  - `test_phase_document_map_uses_bounded_concurrency`
  - `test_phase_evidence_extraction_uses_bounded_concurrency`

### Continuation Validation
- `uv run ruff check src/video_research_mcp/tools/research_document.py tests/test_research_document_tools.py` -> pass.
- `PYTHONPATH=src uv run pytest tests/test_research_document_tools.py -k bounded_concurrency -q` -> pass (`2 passed`).
- `PYTHONPATH=src uv run pytest tests/test_research_document_file.py -k downloads_use_bounded_concurrency -q` -> pass (`1 passed`).
- Note: Full `tests/test_research_document_tools.py` run still shows the pre-existing branch issue tracked as R-004 (tool-call test harness drift/hangs in subset contexts).

### Reflective Loop Update
- Observe: Iteration 8 already bounded pre-processing fan-out, but phase-level Gemini fan-out remained unbounded.
- Infer root cause: Concurrency guardrails were applied at ingestion stage but not consistently across all pipeline phases.
- Strategy: Reuse the same bounded-concurrency pattern inside the document research phase executor.
- Validate: Added bounded helper + focused regression tests; measured capped concurrency behavior.
- Confidence change (continuation): 0.84 -> 0.90 for iteration-8 concurrency coverage completeness.

### Lessons Learned (Continuation)
- Bounded concurrency must be applied end-to-end across all multi-stage async pipelines, not only file/network ingress helpers.
- Existing test harness instability can mask legitimate targeted verification; focused deterministic tests should remain mandatory until R-004 is closed.

### Next-Iteration Hypotheses (Iteration 9)
1. Stabilize tool direct-call test harness behavior (R-004) so full-module regression runs stop hanging.
2. Add explicit per-tool stress-contract tests for max fan-out and cancellation behavior across async phases.
- After commit on `codex/review/i07`:
  - `{"mode":"pr","reason":"Branch has an open pull request.","branch":"codex/review/i07","base_branch":"main","uncommitted_files":0,"ahead_commits":16,"pr_context":true,"pr_url":"https://github.com/Galbaz1/video-research-mcp/pull/59"}`

---

## Continuation Run (2026-03-15T04:03:39Z)

### Scope Detection Snapshots
- After resuming iteration branch commit context in detached mode:
  - `{"mode":"commits","reason":"Branch is ahead of base with no local unstaged/uncommitted files.","branch":"HEAD","base_branch":"main","uncommitted_files":0,"ahead_commits":17,"pr_context":false,"pr_url":null}`
- Before commit (after this run's changes):
  - `{"mode":"uncommitted","reason":"Working tree has local changes.","branch":"HEAD","base_branch":"main","uncommitted_files":12,"ahead_commits":17,"pr_context":false,"pr_url":null}`

### Additional Findings By Severity
#### Medium
- ID: I08-F4
- Area: Static concurrency caps in document pipeline.
- Evidence:
  - Prior hard-coded caps in `research_document.py` and `research_document_file.py` prevented deployment-specific quota tuning.
  - Config-driven caps now wired through [`src/video_research_mcp/config.py`](/Users/fausto/.codex/worktrees/ad1d/gemini-research-mcp/src/video_research_mcp/config.py), [`src/video_research_mcp/tools/research_document.py`](/Users/fausto/.codex/worktrees/ad1d/gemini-research-mcp/src/video_research_mcp/tools/research_document.py), and [`src/video_research_mcp/tools/research_document_file.py`](/Users/fausto/.codex/worktrees/ad1d/gemini-research-mcp/src/video_research_mcp/tools/research_document_file.py).
  - Regression coverage added in [`tests/test_config.py`](/Users/fausto/.codex/worktrees/ad1d/gemini-research-mcp/tests/test_config.py), [`tests/test_research_document_tools.py`](/Users/fausto/.codex/worktrees/ad1d/gemini-research-mcp/tests/test_research_document_tools.py), and [`tests/test_research_document_file.py`](/Users/fausto/.codex/worktrees/ad1d/gemini-research-mcp/tests/test_research_document_file.py).
- Exploit reasoning: Fixed caps can under-throttle on constrained hosts or over-throttle on larger hosts, creating either availability spikes or prolonged resource occupation.
- Fix status: Implemented in this continuation run.

### Additional Implemented Changes
- Added `DOC_PREPARE_CONCURRENCY` and `DOC_PHASE_CONCURRENCY` runtime config with validation range `1..16`.
- Replaced hard-coded phase/preparation caps with `get_config()` lookups and safe defaults.
- Added config parsing and bounds tests for document concurrency settings.

### Continuation Validation
- `uv run ruff check src/video_research_mcp/config.py src/video_research_mcp/tools/research_document.py src/video_research_mcp/tools/research_document_file.py tests/test_config.py tests/test_research_document_tools.py tests/test_research_document_file.py` -> pass.
- `PYTHONPATH=src uv run pytest tests/test_config.py -k 'DocumentConcurrencyConfig' -q` -> pass (`2 passed`).
- `PYTHONPATH=src uv run pytest tests/test_research_document_tools.py -k bounded_concurrency -q` -> pass (`2 passed`).
- `PYTHONPATH=src uv run pytest tests/test_research_document_file.py -k downloads_use_bounded_concurrency -q` -> pass (`1 passed`).

### Reflective Loop Update
- Observe: Residual risk R-013 remained open because caps were still static.
- Infer root cause: Initial remediation prioritized immediate safety but did not externalize control for varied deployment limits.
- Strategy: Reuse bounded-concurrency enforcement while moving cap values into validated runtime configuration.
- Validate: Implemented config-backed controls plus focused config and concurrency regression tests.
- Confidence change (continuation): 0.90 -> 0.93 for iteration-8 concurrency objective completeness.

### Lessons Learned (Continuation)
- Hardening is stronger when safeguards are both present and tunable under strict validation constraints.
- Residual-risk closure should include operability controls, not only code-path bounds.
