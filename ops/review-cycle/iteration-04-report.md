# Iteration 04 Report - Auth and Secret Handling

Date: 2026-03-01T06:03:47Z
Branch: codex/review/i04
Focus: Iteration 4 - auth and secret handling

## Mission Rewritten as Concise EARS Requirements
1. When iteration state is loaded with `current_iteration=4`, the run shall prioritize authorization controls and secret-handling paths.
2. If iteration 3 lessons indicate typed classification improves reliability, iteration 4 shall add typed authorization failure categorization for policy-denied infra mutations.
3. When `infra_cache(action="clear")` or mutating `infra_configure(...)` is requested, the system shall enforce capability policy via `INFRA_MUTATIONS_ENABLED` and optional `INFRA_ADMIN_TOKEN`.
4. If mutation policy is disabled or token validation fails, the tool shall return structured non-retryable permission-denied errors.
5. When infra tools return runtime configuration, the system shall redact all secret-bearing config fields from response payloads.
6. The run shall persist severity-ranked findings, exploit reasoning, implemented or patch-ready changes, confidence deltas, and next-iteration hypotheses.

## Scope Detection Evidence (Before/After Git Transitions)
- Before transitioning from detached `HEAD`:
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- After creating `codex/review/i04` from `origin/codex/review-mainline`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i04", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 4, "pr_context": false, "pr_url": null}`

## Required Reading Checklist
- `AGENTS.md`, `src/AGENTS.md`, `tests/AGENTS.md`
- `docs/ARCHITECTURE.md`, `docs/DIAGRAMS.md`
- `docs/tutorials/ADDING_A_TOOL.md`, `docs/tutorials/WRITING_TESTS.md`

## Findings (Ordered by Severity)

### F-401 (High) - Infra configuration endpoint leaked non-Gemini secrets
- Evidence:
  - `src/video_research_mcp/tools/infra.py` returned `cfg.model_dump(exclude={"gemini_api_key"})`, which left `youtube_api_key` and `weaviate_api_key` in `current_config`.
- Exploit reasoning:
  - Any MCP client with access to `infra_configure()` read path could exfiltrate service credentials and pivot into upstream APIs.
- Concrete fix:
  - Added full secret-field redaction (`gemini_api_key`, `youtube_api_key`, `weaviate_api_key`, `infra_admin_token`) for infra config responses.
- Implementation status:
  - Implemented with regression test coverage.

### F-402 (Medium) - Mutating infra operations lacked explicit capability/auth gating
- Evidence:
  - `infra_cache(action="clear")` and mutating `infra_configure(...)` could execute for any connected client without policy gate.
- Exploit reasoning:
  - Untrusted clients could clear cache or alter global model settings, causing integrity/availability impact.
- Concrete fix:
  - Added policy gate requiring `INFRA_MUTATIONS_ENABLED=true` for mutations and optional token verification when `INFRA_ADMIN_TOKEN` is set.
- Implementation status:
  - Implemented with regression tests for disabled, token-missing, and token-valid paths.

### F-403 (Low) - Permission-denied errors were not explicitly categorized
- Evidence:
  - `make_tool_error()` lacked typed mapping for `PermissionError`, yielding unstable categorization (`UNKNOWN`) for access control failures.
- Exploit reasoning:
  - Policy denials were harder to triage and automate compared with deterministic permission categories.
- Concrete fix:
  - Added `PERMISSION_DENIED` error category and typed `PermissionError` mapping with deterministic hint + non-retryable semantics.
- Implementation status:
  - Implemented and covered in infra policy tests.

## Implemented Changes
- `src/video_research_mcp/tools/infra.py`
  - Added `_enforce_mutation_policy()` for mutating operations.
  - Added optional `auth_token` parameters for mutating infra tool calls.
  - Added `_redacted_config()` and removed secret-bearing fields from `current_config`.
- `src/video_research_mcp/config.py`
  - Added `infra_mutations_enabled` and `infra_admin_token` config fields and env wiring.
- `src/video_research_mcp/errors.py`
  - Added `PERMISSION_DENIED` category and typed `PermissionError` classification.
- `tests/test_infra_tools.py`
  - Added redaction tests and policy/token enforcement tests.
  - Aligned tool invocation with wrapper-safe `unwrap_tool()` usage.

## Validation Evidence
- Lint:
  - `uv run ruff check src/video_research_mcp/tools/infra.py src/video_research_mcp/config.py src/video_research_mcp/errors.py tests/test_infra_tools.py`
- Tests:
  - `PYTHONPATH=src uv run pytest tests/test_infra_tools.py tests/test_errors.py -v`
  - Result: 17 passed

## Reflective Self-Learning Loop
- Observe:
  - Iteration 3 hypotheses targeted auth/capability controls for infra mutators and secret propagation audits.
- Infer root cause:
  - Control-plane endpoints were designed for convenience and did not enforce explicit capability boundaries; redaction was partial and narrowly scoped.
- Propose strategy:
  - Enforce deny-by-default mutation policy with optional shared secret and redact all secret-bearing runtime config fields.
- Validate:
  - Added focused tests for disabled policy, token checks, and redaction behavior; all pass.
- Confidence change:
  - Infra mutator authorization confidence: 0.46 -> 0.82.
  - Secret non-disclosure confidence for infra responses: 0.39 -> 0.88.
  - Overall iteration-4 objective confidence: 0.51 -> 0.84.

## Lessons Learned
1. Control-plane convenience endpoints need explicit capability contracts even in MCP-local deployments.
2. Secret redaction must be centralized and comprehensive, not single-field.
3. The typed-classification pattern from iteration 3 transfers well to authorization failures (`PermissionError` -> deterministic category).

## Next-Iteration Hypotheses (Iteration 5)
1. Audit cache/registry write-through and cleanup flows for data-integrity drift under partial failure.
2. Evaluate stale-context invalidation and cache consistency across session/cache clear operations.
3. Add targeted integrity tests for cache mutation + diagnostics parity under concurrent writes.

## Scope Detection Evidence (Commit Transition)
- Before commit on `codex/review/i04`:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i04", "base_branch": "main", "uncommitted_files": 10, "ahead_commits": 4, "pr_context": false, "pr_url": null}`
- After commit on `codex/review/i04`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i04", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 5, "pr_context": false, "pr_url": null}`
