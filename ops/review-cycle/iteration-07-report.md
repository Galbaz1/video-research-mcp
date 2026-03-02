# Iteration 07 Report - Prompt Injection and Tool Misuse Resistance

Date: 2026-03-01T10:04:39Z
Branch: codex/review/i07
Focus: Iteration 7 - prompt injection and tool misuse resistance

## Mission Rewritten as Concise EARS Requirements
1. When iteration state indicates `current_iteration=7`, the run shall prioritize prompt-injection and tool-misuse resistance.
2. If iteration 6 lessons emphasize explicit fault/integrity contracts, iteration 7 shall carry that lesson by adding explicit anti-injection guardrails across all untrusted-content model-call paths.
3. When a tool analyzes untrusted URL/file/text content, the system shall provide non-overridable system-level safety rules that treat content as data, not instructions.
4. If URL-context structured generation falls back to a two-step reshape flow, the fallback call chain shall preserve the same anti-injection system guardrails.
5. When research/document prompts include untrusted source material, the system prompt shall explicitly reject in-content attempts to override policy, role, or tool behavior.
6. The run shall persist severity-ranked findings, exploit reasoning, concrete fixes, validation evidence, lessons learned, and next-iteration hypotheses.

## Scope Detection Evidence (Before/After Git Transitions)
- Before transitioning from detached `HEAD` to review branch:
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- Transition note:
  - Direct checkout of `codex/review-mainline` was blocked because that branch is already attached to another worktree; branch creation proceeded from the `codex/review-mainline` ref.
- After creating `codex/review/i07` from `codex/review-mainline`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i07", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 12, "pr_context": false, "pr_url": null}`
- Before commit on `codex/review/i07`:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i07", "base_branch": "main", "uncommitted_files": 11, "ahead_commits": 12, "pr_context": false, "pr_url": null}`
- After commit on `codex/review/i07`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i07", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 13, "pr_context": false, "pr_url": null}`

## Required Reading Checklist
- `AGENTS.md`, `src/AGENTS.md`, `tests/AGENTS.md`
- `docs/ARCHITECTURE.md`, `docs/DIAGRAMS.md`
- `docs/tutorials/ADDING_A_TOOL.md`, `docs/tutorials/WRITING_TESTS.md`

## Findings (Ordered by Severity)

### F-701 (High) - Untrusted-content analysis paths lacked explicit anti-injection system guardrails
- Evidence:
  - `src/video_research_mcp/tools/content.py:153-168` previously issued URL-context generation calls without `system_instruction` safety controls.
  - `src/video_research_mcp/tools/content.py:211-225` fallback reshape path previously re-invoked model generation without explicit anti-injection constraints.
- Exploit reasoning:
  - Adversarial webpage/document text can include instruction-smuggling payloads that bias model behavior during both primary and fallback flows, potentially degrading output integrity and tool-policy adherence.
- Concrete fix:
  - Added a shared `CONTENT_ANALYSIS_SYSTEM` anti-injection policy and passed it to all model invocations in `content_analyze` and `content_extract`, including URL fallback reshape calls.
- Implementation status:
  - Implemented with regression assertions in `tests/test_content_tools.py`.

### F-702 (Medium) - Research system prompts did not explicitly reject in-content prompt-injection attempts
- Evidence:
  - `src/video_research_mcp/prompts/research.py:23-31` previously focused on evidence rigor but did not explicitly instruct the model to ignore source-embedded override attempts.
  - `src/video_research_mcp/prompts/research_document.py:22-28` had no explicit “document text is untrusted data” clause.
- Exploit reasoning:
  - Source material can contain instructions like “ignore prior rules” that compete with tool intent, raising risk of policy drift in synthesis-heavy workflows.
- Concrete fix:
  - Added explicit prompt-injection resistance rules to both research system prompts.
- Implementation status:
  - Implemented as prompt hardening (no behavioral API break).

## Implemented Changes
- `src/video_research_mcp/prompts/content.py`
  - Added `CONTENT_ANALYSIS_SYSTEM` with explicit anti-injection and anti-tool-misuse rules.
- `src/video_research_mcp/tools/content.py`
  - Applied `system_instruction=CONTENT_ANALYSIS_SYSTEM` to URL-context calls, fallback reshape calls, standard part-analysis calls, and structured extraction calls.
- `src/video_research_mcp/prompts/research.py`
  - Added anti-injection clauses to `DEEP_RESEARCH_SYSTEM`.
- `src/video_research_mcp/prompts/research_document.py`
  - Added anti-injection clauses to `DOCUMENT_RESEARCH_SYSTEM`.
- `tests/test_content_tools.py`
  - Added assertions that content-analysis/extract model calls include `CONTENT_ANALYSIS_SYSTEM`.
  - Updated tests to use `unwrap_tool(...)` for direct-call compatibility in this isolated test module.

## Validation Evidence
- Lint:
  - `uv run ruff check tests/test_content_tools.py src/video_research_mcp/tools/content.py src/video_research_mcp/prompts/content.py src/video_research_mcp/prompts/research.py src/video_research_mcp/prompts/research_document.py`
- Tests:
  - `PYTHONPATH=src uv run pytest tests/test_content_tools.py -v`
  - Result: 16 passed

## Reflective Self-Learning Loop
- Observe evidence:
  - Multi-step untrusted-content flows (URL fetch + reshape) preserved schema behavior but not explicit injection resistance contracts.
- Infer root causes:
  - Safety intent existed implicitly in task prompts but not as explicit, reusable system-level policy.
- Proposed fix strategies:
  - Introduce one shared anti-injection system instruction for content tools.
  - Harden research/document system prompts to explicitly ignore in-content override attempts.
  - Add tests that verify guardrail propagation on all relevant call paths.
- Validate fixes:
  - Added targeted assertions for `system_instruction` propagation and reran focused lint/tests.
- Confidence change:
  - Prompt-injection resistance confidence (content tools): 0.48 -> 0.84.
  - Prompt-injection resistance confidence (research prompts): 0.52 -> 0.78.
  - Overall iteration-7 objective confidence: 0.50 -> 0.82.

## Lesson-Carried Remediation (Required N-1 linkage)
- Derived from iteration 6 lesson: silent degradation must be replaced by explicit contracts.
- Applied in iteration 7:
  - Replaced implicit “prompt should be safe enough” behavior with explicit reusable guardrail contracts (`CONTENT_ANALYSIS_SYSTEM`) and verification tests that enforce those contracts across fallback paths.

## Lessons Learned
1. Fallback paths are often the weakest point for safety-policy propagation and need explicit parity checks.
2. System-level reusable guardrails reduce policy drift across multi-step tool pipelines.
3. Prompt hardening should be accompanied by test assertions on actual call wiring, not only static prompt text updates.

## Next-Iteration Hypotheses (Iteration 8)
1. Stress-test concurrency of URL/file analysis flows with large inputs and repeated fallback to evaluate resource-exhaustion behavior.
2. Add focused guardrails or limits for expensive multi-document and multi-file parallel paths.
3. Evaluate timeout/cancellation behavior in async gather pipelines under high load.
