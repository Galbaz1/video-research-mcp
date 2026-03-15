# Iteration 02 Security Review Report

- Run timestamp (UTC): 2026-03-15T03:45:00Z
- Focus: Validation and schema contracts
- Branch: `codex/review/i01` (resumed existing iteration branch)
- Scope protocol outputs:
  - Pre-transition (detached HEAD):
    - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
  - Post-transition (`codex/review-mainline`):
    - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review-mainline", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 12, "pr_context": false, "pr_url": null}`
  - Pre-transition (`codex/review-mainline` -> `codex/review/i01`):
    - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review-mainline", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 12, "pr_context": false, "pr_url": null}`
  - Post-transition (`codex/review/i01`):
    - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i01", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 2, "pr_context": false, "pr_url": null}`
  - Post-change snapshot:
    - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i01", "base_branch": "main", "uncommitted_files": 11, "ahead_commits": 2, "pr_context": false, "pr_url": null}`

## Mission Rewritten as Concise EARS (Prompt-Optimizer)
1. The automation shall load prior review-cycle memory files before selecting the current iteration plan.
2. When iteration `N` is active, the automation shall execute the focus area assigned to `N` and produce a severity-ranked security report.
3. When a major git-state transition is about to happen, the automation shall run `scripts/detect_review_scope.py --json` before and after the transition and record both outputs.
4. If `current_iteration` is between `1` and `10`, the automation shall run the reflective loop (observe, infer, propose, validate, confidence update) and persist results.
5. If `current_iteration` is greater than `10`, the automation shall generate `ops/review-cycle/final-report.md` and stop creating iteration branches.
6. When iteration `N` is greater than `1`, the automation shall implement at least one remediation derived from a lesson captured in iteration `N-1`.

## Findings by Severity

### High
1. Redirect-hop SSRF validation gap in document downloader (fixed)
- Evidence: [`src/video_research_mcp/url_policy.py:143`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/url_policy.py:143) previously used `httpx.AsyncClient(follow_redirects=True, ...)` and validated only initial/final URLs.
- Exploit reasoning: attacker-controlled URL could return intermediate redirects to blocked/internal hosts; the client would follow those hops before policy checks, crossing trust boundaries.
- Concrete fix: disable automatic redirects, manually follow up to 5 hops, validate every hop URL, and apply peer-IP rebinding checks on each request.
- Implemented change: yes.
- Validation: [`tests/test_url_policy.py:217`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/tests/test_url_policy.py:217) and [`tests/test_url_policy.py:231`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/tests/test_url_policy.py:231).

### Medium
2. Weak list-parameter contract allowed malformed schema/input paths (fixed)
- Evidence: list-typed tool params were coerced with `coerce_json_param(..., list)` but could remain raw strings when parsing failed, then flow into list semantics.
- Affected boundaries:
  - [`src/video_research_mcp/tools/research_document.py:69`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/research_document.py:69)
  - [`src/video_research_mcp/tools/research.py:179`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/research.py:179)
  - [`src/video_research_mcp/tools/content_batch.py:208`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/content_batch.py:208)
  - [`src/video_research_mcp/tools/knowledge/search.py:76`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/knowledge/search.py:76)
- Exploit reasoning: malformed string input at JSON-RPC boundary can trigger character-by-character processing and unbounded task fanout, causing avoidable resource consumption and opaque behavior.
- Concrete fix: add strict shared coercion helper for `list[str]` and enforce it at tool ingress with explicit validation errors.
- Implemented change: yes.
- Validation:
  - [`tests/test_research_document_tools.py:150`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/tests/test_research_document_tools.py:150)
  - [`tests/test_research_tools.py:247`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/tests/test_research_tools.py:247)
  - [`tests/test_content_batch_tools.py:193`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/tests/test_content_batch_tools.py:193)
  - [`tests/test_knowledge_tools.py:170`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/tests/test_knowledge_tools.py:170)

## Implemented / Patch-Ready Changes
- Implemented:
  - Per-hop redirect validation and manual redirect enforcement in `download_checked`.
  - New shared `coerce_string_list_param` helper in [`src/video_research_mcp/types.py:33`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/types.py:33).
  - Strict list-string contract checks across four tool ingress points.
  - Regression tests for malformed non-list string inputs and redirect behavior.
- Patch-ready (not implemented this iteration):
  - Explicit `output_schema` structural limits (depth/property-count caps) to bound pathological custom schema payloads.

## Reflective Self-Learning Loop
- Observe: schema/list coercion accepted malformed values silently, causing non-obvious behavior under direct/edge inputs.
- Infer root cause: input contract enforcement relied on permissive coercion rather than strict post-coercion type guarantees.
- Propose strategy: centralize list-string coercion/validation and apply at every list-bearing trust boundary.
- Validate: code changes + lint clean + URL-policy test suite passing + targeted runtime assertions for new list validation paths.
- Confidence change: 0.61 -> 0.86 for validation-contract robustness across these tools.

## Remediation Derived from Iteration N-1 Lesson
- Iteration-1 lesson: security primitives must be enforced at every ingress trust boundary, not by convention.
- Iteration-2 derived remediation: reused that principle to enforce strict ingress contracts (`coerce_string_list_param`) across all list-typed inputs reviewed this cycle.

## Lessons Learned
- Shared parsing helpers should fail closed for boundary types; permissive fallback paths hide contract violations.
- Redirect handling must be explicit when security policy depends on hop-by-hop trust verification.

## Next-Iteration Hypotheses (Iteration 3: external API failure modes and idempotency)
1. File upload and download retry paths may not preserve idempotency guarantees under partial failure.
2. External API fallback branches may leak inconsistent error categories, weakening caller retry policy.
3. Batch operations may need tighter per-source circuit breakers to avoid cascading failures.
