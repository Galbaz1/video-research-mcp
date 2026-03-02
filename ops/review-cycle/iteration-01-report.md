# Iteration 01 Security Review Report

- Run timestamp (UTC): 2026-03-01T03:26:51Z
- Focus: Architecture and trust boundaries
- Branch: `codex/review/i01`
- Scope protocol output (pre-transition):
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- Scope protocol output (post-transition):
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "codex/review/i01", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- Scope protocol output (post-merge mainline):
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review-mainline", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 1, "pr_context": false, "pr_url": null}`

## Findings by Severity

### High
1. URL trust boundary bypass in `content_analyze` (fixed)
- Evidence: URL input path in [`src/video_research_mcp/tools/content.py:105`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/src/video_research_mcp/tools/content.py:105) previously entered URL-context fetch path without enforcing `url_policy.validate_url()`.
- Exploit reasoning: attacker-controlled URL input could bypass internal URL safety policy applied elsewhere, resulting in inconsistent SSRF boundary controls.
- Concrete fix: add `await validate_url(url)` before enabling URL-context processing; treat `UrlPolicyError` as tool error.
- Implemented change: yes.
- Validation: regression test added at [`tests/test_content_tools.py:72`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/tests/test_content_tools.py:72).

### Medium
2. Runtime mutability control surface lacks explicit authorization gate
- Evidence: destructive cache clear and runtime model mutation are directly exposed in [`src/video_research_mcp/tools/infra.py:47`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/src/video_research_mcp/tools/infra.py:47) and [`src/video_research_mcp/tools/infra.py:105`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/src/video_research_mcp/tools/infra.py:105).
- Exploit reasoning: any attached client can alter global behavior or delete caches, impacting availability/integrity.
- Concrete fix: add configurable capability guard for mutating operations (queued, patch-ready design pending compatibility decision).
- Implemented change: no (queued).

3. Broad filesystem path trust boundary in batch content ingestion
- Evidence: user-provided directory and file paths are resolved directly by [`src/video_research_mcp/tools/content_batch.py:61`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/src/video_research_mcp/tools/content_batch.py:61) and [`src/video_research_mcp/tools/content_batch.py:72`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/src/video_research_mcp/tools/content_batch.py:72).
- Exploit reasoning: in non-single-user environments, unbounded path selection can expose unintended local files to model processing.
- Concrete fix: add optional allowlisted roots configuration and explicit denial outside roots (queued).
- Implemented change: no.

## Implemented / Patch-Ready Changes
- Implemented:
  - URL-policy enforcement at `content_analyze` ingress.
  - Non-HTTPS URL rejection regression test.
- Patch-ready (not yet applied):
  - `infra_*` capability gate.
  - content batch path allowlist.

## Reflective Self-Learning Loop
- Observe: URL-policy logic existed but was not consistently attached at all ingress points.
- Root cause: architecture-level policy reuse relied on convention instead of mandatory utility call at each URL entry point.
- Strategy: codify a playbook rule: every URL-accepting tool must call `validate_url()` before remote fetch behavior.
- Validate: code patch + automated test passed.
- Confidence change: 0.55 -> 0.80 for this boundary after remediation.

## Lessons Learned
- Shared security primitives are only effective when enforced at every trust boundary, not only in one data path.
- Iteration reports need explicit pre/post git-scope evidence to preserve auditability.

## Next-Iteration Hypotheses (Iteration 2: validation/schema contracts)
1. Schema coercion paths may accept malformed custom schemas that degrade failure transparency.
2. Pydantic model defaults and error wrappers may hide validation root causes in tool responses.
3. Output schema routes may need stricter size/shape limits to prevent pathological payload requests.

## Branch/PR Status
- Created `codex/review-mainline` and `codex/review/i01`.
- Opened PR: [#30](https://github.com/Galbaz1/video-research-mcp/pull/30) (`codex/review/i01` -> `codex/review-mainline`).
- Merged PR #30, deleted iteration branch, and fast-forwarded local `codex/review-mainline`.
