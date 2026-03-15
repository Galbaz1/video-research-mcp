# Iteration 02 Report - Validation and Schema Contracts

Date: 2026-03-01T04:05:41Z
Branch: codex/review/i02
Focus: Iteration 2 - validation and schema contracts

## Mission Rewritten as Concise EARS Requirements
1. When iteration state is loaded, the automation shall execute the iteration matching `current_iteration` and shall inherit unresolved risks and hypotheses from the prior iteration.
2. For iteration 2, the automation shall review validation and schema contracts across tool ingress points, including path, URL, and payload boundary handling.
3. When a previous iteration lesson identifies boundary inconsistency, the automation shall implement at least one remediation directly derived from that lesson.
4. Before and after each major git state transition, the automation shall run `scripts/detect_review_scope.py --json` and capture outputs in this report.
5. The automation shall record findings by severity, exploit reasoning, concrete fixes, implementation status, and next-iteration hypotheses.

## Scope Detection Evidence (Before/After Git Transitions)
- Before switching to iteration branch (detached context):
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- Around transition to `codex/review/i02`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i02", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 2, "pr_context": false, "pr_url": null}`

## Findings (Ordered by Severity)

### F-201 (Medium) - Local filesystem path contracts were permissive at multiple tool ingress points
- Evidence:
  - `src/video_research_mcp/tools/video_file.py:53`
  - `src/video_research_mcp/tools/content.py:41`
  - `src/video_research_mcp/tools/content_batch.py:61`
  - `src/video_research_mcp/tools/research_document_file.py:119`
  - `src/video_research_mcp/tools/video_batch.py:66`
- Exploit reasoning:
  - In semi-trusted MCP deployments, induced tool calls can target arbitrary local paths and send data into model processing, crossing host trust boundaries.
- Concrete fix:
  - Added config-driven local path boundary via `LOCAL_FILE_ACCESS_ROOT` and centralized enforcement helper.
  - Enforced policy at all local path ingress points above.
- Implementation status:
  - Implemented and tested (focused tests).

### F-202 (Medium) - Direct tool-call contract instability in subset tests
- Evidence:
  - `tests/test_content_tools.py` and `tests/test_content_batch_tools.py` direct calls to decorated tools fail with `TypeError: 'FunctionTool' object is not callable` in this environment.
- Exploit reasoning:
  - This is primarily a reliability/testability contract issue. It can hide regressions if CI paths rely on direct-call semantics for decorated tools.
- Concrete fix:
  - No product code change in this iteration; tracked as follow-up for iteration 9 (test blind spots) because this appears pre-existing in branch baseline.
- Implementation status:
  - Patch-ready investigation note only.

## Implemented Changes
- Added `src/video_research_mcp/local_path_policy.py` with shared path resolution + root enforcement.
- Added `local_file_access_root` to runtime config from `LOCAL_FILE_ACCESS_ROOT`.
- Wired enforcement into:
  - `video_file` local file validation
  - `content` local file ingestion
  - `content_batch` directory and explicit file resolution
  - `video_batch` directory resolution
  - `research_document_file` local file path preparation
- Added targeted regression tests for root boundary enforcement:
  - `tests/test_video_file.py`
  - `tests/test_content_tools.py`
  - `tests/test_content_batch_tools.py`

## Reflective Self-Learning Loop
- Observe:
  - Iteration 1 left open local filesystem boundary risk (`R-003`) and recommended trust-policy matrix work.
- Infer root cause:
  - Boundary controls were applied unevenly (URL policy existed, local path policy did not), leading to inconsistent ingress validation contracts.
- Propose strategy:
  - Introduce a single policy primitive (`enforce_local_access_root`) and fan it into all local path ingress points.
- Validate:
  - `uv run ruff check ...` passed for touched files.
  - Focused policy tests passed:
    - `TestValidateVideoPath::test_rejects_path_outside_local_access_root`
    - `TestBuildContentParts::test_file_outside_local_access_root`
    - `TestResolveFiles::test_directory_outside_local_access_root`
- Confidence change:
  - Local path boundary confidence: 0.42 -> 0.79 after centralized guard + tests.
  - Validation contract confidence overall: 0.63 -> 0.74 (remaining drag due direct-call `FunctionTool` test contract issue).

## Lessons Learned
1. Policy centralization is lower risk than patching each tool ad hoc and improves future coverage.
2. Optional hardening flags preserve backward compatibility while enabling secure-by-default deployments where explicitly configured.
3. Validation regressions can be hidden if test harness contract assumptions drift (decorated-callability needs dedicated coverage).

## Next-Iteration Hypotheses (Iteration 3)
1. External API failure-mode coverage should explicitly test idempotent retries and partial-failure behavior for batch/document pipelines.
2. Upload/download workflows need resilience contracts for timeout, stale cache, and concurrent retries with deterministic error typing.
3. Add failure-mode matrix tests that assert `make_tool_error()` category consistency for transport/API exceptions.

## Scope Detection Evidence (Commit Transition)
- Before commit on `codex/review/i02`:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i02", "base_branch": "main", "uncommitted_files": 16, "ahead_commits": 2, "pr_context": false, "pr_url": null}`
- After commit on `codex/review/i02`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i02", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 3, "pr_context": false, "pr_url": null}`
