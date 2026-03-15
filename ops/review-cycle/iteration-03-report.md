# Iteration 03 Report - External API Failure Modes and Idempotency

Date: 2026-03-01T06:20:00Z
Branch: codex/review/i03
Focus: Iteration 3 - external API failure modes and idempotency

## Mission Rewritten as Concise EARS Requirements
1. When iteration state is loaded with `current_iteration=3`, the run shall prioritize external API failure modes and idempotency behavior.
2. When tools perform external upload/download operations, the system shall classify timeout and transport failures into deterministic structured `make_tool_error()` categories.
3. If concurrent retries target the same file content, the upload pipeline shall prevent duplicate upstream uploads and shall reuse cached URIs.
4. Before and after each major git state transition, the automation shall run `scripts/detect_review_scope.py --json` and capture outputs in this report.
5. When iteration 2 lessons identify failure-mode matrix gaps, iteration 3 shall implement at least one remediation directly derived from those lessons.
6. The run shall record findings by severity, exploit reasoning, concrete fixes, implementation status, confidence deltas, and next-iteration hypotheses.

## Scope Detection Evidence (Before/After Git Transitions)
- Before transitioning from detached `HEAD`:
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- After creating/resuming `codex/review/i03` from `origin/codex/review-mainline`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i03", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 3, "pr_context": false, "pr_url": null}`

## Findings (Ordered by Severity)

### F-301 (Medium) - Concurrent upload retries could duplicate upstream File API uploads
- Evidence:
  - `src/video_research_mcp/tools/video_file.py` previously checked cache before upload without per-hash concurrency control.
- Exploit reasoning:
  - Two concurrent tool calls for the same local file can both miss cache and upload simultaneously, causing duplicate external writes, quota burn, and inconsistent retry behavior.
- Concrete fix:
  - Added per-`content_hash` async lock coordination in `_upload_large_file()` so same-hash uploads are serialized and cache is rechecked under lock.
- Implementation status:
  - Implemented and covered with concurrency regression test.

### F-302 (Medium) - External timeout/transport errors were not deterministically categorized
- Evidence:
  - `src/video_research_mcp/errors.py` relied mostly on substring matching; `TimeoutError()` with empty message and typed `httpx` transport exceptions could map to `UNKNOWN`.
- Exploit reasoning:
  - Inconsistent error categorization weakens automated retry behavior and operational response, increasing incident resolution time.
- Concrete fix:
  - Added explicit typed categorization for `TimeoutError`, `httpx.TimeoutException`, and `httpx.NetworkError` to `NETWORK_ERROR`.
- Implementation status:
  - Implemented and covered with focused unit tests.

### F-303 (Low, patch-ready) - Document preparation silently drops partial download/upload failures
- Evidence:
  - `src/video_research_mcp/tools/research_document_file.py:109-115` and `:130-136` log per-source failures and continue without surfacing skipped sources in the tool response.
- Exploit reasoning:
  - Users can receive synthesized outputs from an unintended subset of documents without explicit awareness, reducing evidence integrity under partial external API failure.
- Concrete fix:
  - Patch-ready: return a `skipped_sources` list from preparation and surface it in `research_document` output metadata.
- Implementation status:
  - Not implemented in this iteration; queued for iteration 6 (fault isolation) where response-contract impact can be validated holistically.

## Implemented Changes
- `src/video_research_mcp/tools/video_file.py`
  - Added per-hash upload locking to coalesce concurrent retries and preserve idempotent upload behavior.
- `src/video_research_mcp/errors.py`
  - Added explicit typed mapping for timeout/network exceptions to structured `NETWORK_ERROR`.
- `tests/test_video_file.py`
  - Added `test_concurrent_same_hash_uploads_once` to verify duplicate uploads are prevented.
- `tests/test_errors.py`
  - Added timeout/network categorization tests for `make_tool_error()`.

## Validation Evidence
- Lint:
  - `uv run ruff check src/video_research_mcp/tools/video_file.py src/video_research_mcp/errors.py tests/test_video_file.py tests/test_errors.py`
- Tests:
  - `PYTHONPATH=src uv run pytest tests/test_video_file.py tests/test_errors.py -v`
  - Result: 27 passed

## Reflective Self-Learning Loop
- Observe:
  - Iteration 2 hypotheses explicitly called for failure categorization consistency and idempotency checks in upload/download flows.
- Infer root cause:
  - Failure handling had robust structure (`make_tool_error`) but lacked typed exception guards; upload caching lacked concurrency coordination around the cache boundary.
- Propose strategy:
  - Add typed error mapping for transport/timeouts and add per-hash lock to serialize upload cache critical sections.
- Validate:
  - New tests confirm typed error mapping and single-upload behavior under concurrent calls.
- Confidence change:
  - External API failure categorization confidence: 0.58 -> 0.83.
  - Upload idempotency confidence under concurrent retries: 0.49 -> 0.81.
  - Overall iteration-3 objective confidence: 0.62 -> 0.82.

## Lessons Learned
1. Substring-only exception classification is brittle for typed async clients; typed checks should gate operational categories.
2. Cache-based idempotency requires explicit critical-section control under concurrency, not just cache reads/writes.
3. Partial-success pipelines need explicit user-visible degradation metadata, not only logs.

## Next-Iteration Hypotheses (Iteration 4)
1. Audit secret handling in env/config surfaces and ensure sensitive values never leak via tool responses or logs.
2. Add capability/authorization guard design for infra mutation tools (`infra_cache`, `infra_configure`) to reduce misuse risk.
3. Validate redaction strategy for error messages that may include upstream request details.

## Scope Detection Evidence (Commit Transition)
- Before commit on `codex/review/i03`:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i03", "base_branch": "main", "uncommitted_files": 4, "ahead_commits": 3, "pr_context": false, "pr_url": null}`
- After commit on `codex/review/i03`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i03", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 4, "pr_context": false, "pr_url": null}`
