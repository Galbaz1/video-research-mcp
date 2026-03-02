# Iteration 09 Report - Test and Regression Blind Spots

Date: 2026-03-01T15:04:13Z
Branch: codex/review/i09
Focus: Iteration 9 - test and regression blind spots

## Mission Rewritten as Concise EARS Requirements
1. When iteration state indicates `current_iteration=9`, the run shall prioritize regression blind spots in security-sensitive and concurrency-related paths.
2. If iteration 8 lessons require explicit cross-path workload and safety contracts, iteration 9 shall extend that contract discipline to redirect handling and test-harness reliability.
3. When URL downloads encounter redirects, the system shall validate each redirect target before issuing the next request.
4. If redirect depth exceeds policy or redirect metadata is malformed, the system shall return deterministic policy errors.
5. When tool tests import decorated FastMCP tools, the tests shall unwrap tool wrappers before direct coroutine invocation.
6. The run shall persist severity-ranked findings, exploit reasoning, concrete fixes, validation evidence, lessons learned, and next-iteration hypotheses.

## Scope Detection Evidence (Before/After Git Transitions)
- Baseline on detached `HEAD` before review-branch switch:
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- After creating `codex/review/i09` from `origin/codex/review-mainline`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i09", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 16, "pr_context": false, "pr_url": null}`
- Before commit on `codex/review/i09`:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i09", "base_branch": "main", "uncommitted_files": 3, "ahead_commits": 16, "pr_context": false, "pr_url": null}`
- After commit on `codex/review/i09`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i09", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 17, "pr_context": false, "pr_url": null}`
- Before report-finalization commit:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i09", "base_branch": "main", "uncommitted_files": 1, "ahead_commits": 17, "pr_context": false, "pr_url": null}`
- After report-finalization commit:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i09", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 18, "pr_context": false, "pr_url": null}`

## Required Reading Checklist
- `AGENTS.md`, `src/AGENTS.md`, `tests/AGENTS.md`
- `docs/ARCHITECTURE.md`, `docs/DIAGRAMS.md`
- `docs/tutorials/ADDING_A_TOOL.md`, `docs/tutorials/WRITING_TESTS.md`

## Findings (Ordered by Severity)

### F-901 (High) - Redirect policy checks occurred after network follow, allowing first-hop SSRF attempts
- Evidence:
  - [`src/video_research_mcp/url_policy.py`](/Users/fausto/.codex/worktrees/8f30/gemini-research-mcp/src/video_research_mcp/url_policy.py) previously used `httpx.AsyncClient(follow_redirects=True, ...)` and validated redirected URL only after response resolution.
- Exploit reasoning:
  - An attacker-controlled public URL can return a redirect to an internal host; auto-follow may issue the redirected request before policy enforcement, violating trust-boundary intent.
- Concrete fix:
  - Switched to manual redirect handling (`follow_redirects=False`), validated each redirect `Location` target with `validate_url()` before following, and enforced a hard redirect-depth limit.
- Implementation status:
  - Implemented and regression-tested.

### F-902 (Medium) - `content_batch` test suite had broken direct-call path (`FunctionTool`), masking regressions
- Evidence:
  - [`tests/test_content_batch_tools.py`](/Users/fausto/.codex/worktrees/8f30/gemini-research-mcp/tests/test_content_batch_tools.py) imported `content_batch_analyze` directly without `unwrap_tool`, causing `TypeError: 'FunctionTool' object is not callable` in targeted runs.
- Exploit reasoning:
  - Broken tests reduce signal on future security and reliability regressions in batch analysis paths.
- Concrete fix:
  - Added explicit `unwrap_tool()` at import boundary in the test module.
- Implementation status:
  - Implemented and validated.

## Implemented Changes
- [`src/video_research_mcp/url_policy.py`](/Users/fausto/.codex/worktrees/8f30/gemini-research-mcp/src/video_research_mcp/url_policy.py)
  - Replaced auto-follow redirects with manual validated redirect loop.
  - Added deterministic errors for missing redirect location and redirect-depth overflow.
- [`tests/test_url_policy.py`](/Users/fausto/.codex/worktrees/8f30/gemini-research-mcp/tests/test_url_policy.py)
  - Updated redirect behavior assertions for manual hop handling.
  - Added adversarial regression test ensuring blocked redirect targets are rejected before second request.
- [`tests/test_content_batch_tools.py`](/Users/fausto/.codex/worktrees/8f30/gemini-research-mcp/tests/test_content_batch_tools.py)
  - Added `unwrap_tool(content_batch_analyze)` for stable direct-call test execution.

## Validation Evidence
- Lint:
  - `uv run ruff check src/video_research_mcp/url_policy.py tests/test_url_policy.py tests/test_content_batch_tools.py`
- Tests:
  - `PYTHONPATH=src uv run pytest tests/test_url_policy.py tests/test_content_batch_tools.py -q`
  - Result: 43 passed

## Reflective Self-Learning Loop
- Observe evidence:
  - Redirect-path trust control relied on post-follow checks.
  - Regression suite contained a concrete blind spot where a full test module partially failed in targeted execution.
- Infer root causes:
  - Safety policy assumed equivalent behavior between automatic and manual redirect semantics.
  - Test harness parity (`unwrap_tool`) was not uniformly applied across tool test modules.
- Proposed fix strategies:
  - Move URL policy enforcement to pre-follow redirect boundaries.
  - Add explicit regression for blocked redirect target before follow.
  - Normalize tool test import pattern with explicit unwrapping.
- Validate fixes:
  - Implemented code/test patches; lint and targeted tests passed.
- Confidence change:
  - Redirect trust-boundary confidence: 0.58 -> 0.87.
  - Regression-harness reliability confidence (`content_batch`): 0.45 -> 0.90.
  - Overall iteration-9 objective confidence: 0.52 -> 0.86.

## Lesson-Carried Remediation (Required N-1 linkage)
- Derived from iteration 8 lesson: explicit contracts must cover all paths, not only primary flows.
- Applied in iteration 9:
  - Redirect handling now enforces explicit per-hop policy contracts before follow.
  - Regression safety net now explicitly enforces direct-call compatibility for wrapped tools.

## Lessons Learned
1. Trust-boundary checks must occur before network side effects, not after.
2. Safety-critical path tests should include adversarial redirect chains, not only final-URL assertions.
3. Tool-wrapper compatibility must be standardized in every test module to avoid silent coverage drift.

## Next-Iteration Hypotheses (Iteration 10)
1. Produce a synthesis report that maps all mitigations (iterations 1-9) to residual risks and priority tiers.
2. Add one consolidated security regression suite entrypoint for the highest-impact controls (URL policy, infra auth, local path boundaries, workload envelopes).
3. Identify backlog items that remained patch-ready but not implemented and convert them into a prioritized remediation roadmap.
