# Prompt Evolution

## Iteration 1 Mission Rewritten as EARS Requirements

### Original Mission (condensed)
Run an hourly security-focused review loop with branch discipline, reflective learning, persistent memory, and iteration-specific scope.

### EARS Requirements
1. The automation shall load prior state from `ops/review-cycle/state.json`, `learning-log.md`, `fix-playbook.md`, `risk-register.md`, and `prompt-evolution.md` before planning each run.
2. When run context starts, the automation shall rewrite the run mission into concise EARS requirements before code review actions.
3. When `current_iteration` is missing, the automation shall initialize it to `1`.
4. If `current_iteration` is greater than `10`, the automation shall generate `ops/review-cycle/final-report.md` and shall stop branch creation.
5. The automation shall execute `scripts/detect_review_scope.py --json` before and after each major git-state transition and shall record outputs in iteration notes.
6. When working iterations 1-10, the automation shall use `codex/review-mainline` as the only long-lived review branch.
7. When iteration `N` starts and no active branch exists, the automation shall create/resume `codex/review/iNN` from `codex/review-mainline`.
8. The automation shall record findings by severity, exploit reasoning, concrete fixes, implemented or patch-ready changes, lessons learned, and next-iteration hypotheses.
9. The automation shall run a reflective loop on each iteration: observe evidence, infer root causes, propose strategies, validate or draft fixes, and record confidence changes.
10. If iteration `N` is greater than `1`, the automation shall include at least one remediation directly derived from iteration `N-1` lessons.

## Quality delta
- Before: Broad multi-step instruction set with implicit control flow.
- After: Testable run-time requirements with explicit triggers and stop conditions.

## Iteration 2 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=2`, the run shall prioritize validation and schema contract analysis.
2. If iteration 1 logged unresolved trust-boundary lessons, the run shall implement at least one remediation directly derived from those lessons.
3. When local file or directory inputs are accepted by tools, the system shall validate resolved paths against a shared policy boundary when configured.
4. If validation enforcement rejects an input, the tool shall return structured `make_tool_error()` output rather than raising uncaught exceptions.
5. The run shall persist findings, confidence deltas, and next hypotheses to review-cycle memory artifacts before completion.

## Iteration 3 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=3`, the run shall prioritize external API failure modes and idempotency.
2. If iteration 2 lessons identify timeout/retry categorization gaps, the run shall implement at least one typed error-classification remediation.
3. When concurrent requests upload identical file content, the system shall prevent duplicate upstream uploads by coordinating cache checks within a critical section.
4. If timeout or transport exceptions occur, the tool error pipeline shall emit deterministic `NETWORK_ERROR` categorization with retryable semantics.
5. The run shall record severity-ranked findings, implemented fixes, confidence deltas, and next hypotheses in review-cycle artifacts before completion.

## Iteration 4 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=4`, the run shall prioritize authorization controls and secret-handling paths.
2. If iteration 3 lessons indicate typed classification improves reliability, iteration 4 shall add typed authorization failure categorization for policy-denied mutations.
3. When `infra_cache(action="clear")` or mutating `infra_configure(...)` is requested, the system shall enforce capability policy via `INFRA_MUTATIONS_ENABLED` and optional token verification.
4. If mutation policy is disabled or token validation fails, the tool shall return structured `make_tool_error()` output with non-retryable permission semantics.
5. When infra tools return runtime configuration, the system shall redact all secret-bearing fields from response payloads.
6. The run shall persist severity-ranked findings, exploit reasoning, implemented or patch-ready remediations, confidence deltas, and next-iteration hypotheses to review-cycle artifacts.

## Iteration 5 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=5`, the run shall prioritize cache and persisted-state data integrity.
2. If iteration 4 lessons emphasize centralized and comprehensive controls, iteration 5 shall apply one shared integrity hardening pattern across multiple cache subsystems.
3. When cache payloads are written to disk, the system shall stage writes in a temporary file and atomically replace the target file.
4. If persisted context-cache registry content contains malformed entries, the loader shall ignore invalid shapes and shall only hydrate validated string mappings.
5. The run shall record severity-ranked findings, exploit reasoning, implemented fixes, confidence deltas, and next-iteration hypotheses in review-cycle artifacts before completion.

## Iteration 6 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=6`, the run shall prioritize error handling and fault-isolation transparency.
2. If iteration 5 lessons emphasize integrity contracts across persistence boundaries, iteration 6 shall apply the same explicit-integrity pattern to partial-failure metadata across preparation and synthesis boundaries.
3. When any document source fails during download or upload preparation, the system shall record structured per-source failure metadata (`source`, `phase`, `error_type`, `error`).
4. If at least one source is still prepared successfully, the final `research_document` response shall include preparation-failure metadata instead of silently dropping failed sources.
5. If all sources fail preparation, the tool shall return structured `make_tool_error()` output and shall not proceed to synthesis.
6. The run shall persist severity-ranked findings, exploit reasoning, implemented remediations, confidence deltas, and next-iteration hypotheses in review-cycle artifacts before completion.
