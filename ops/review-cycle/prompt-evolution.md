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

## Iteration 7 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=7`, the run shall prioritize prompt-injection and tool-misuse resistance.
2. If iteration 6 lessons emphasize explicit safety/integrity contracts, iteration 7 shall enforce explicit anti-injection system policies across all untrusted-content model call paths.
3. When `content_analyze` executes URL-context analysis, the system shall supply a reusable system instruction that treats fetched content as untrusted data.
4. If URL-context structured generation falls back to unstructured fetch plus reshape, the fallback and reshape calls shall preserve the same anti-injection system instruction.
5. When research/document system prompts process source material, they shall explicitly ignore in-content attempts to override role, policy, or tool behavior.
6. The run shall persist severity-ranked findings, exploit reasoning, implemented fixes, confidence deltas, and next-iteration hypotheses in review-cycle artifacts before completion.

## Iteration 8 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=8`, the run shall prioritize concurrency and resource-exhaustion risks in multi-source workflows.
2. If iteration 7 lessons require explicit cross-path contracts, iteration 8 shall apply one shared workload-envelope policy across document preparation and analysis phases.
3. When `research_document` receives source inputs, the system shall reject requests that exceed `RESEARCH_DOCUMENT_MAX_SOURCES`.
4. When URL downloads, document uploads, and per-document phase calls execute, the system shall enforce bounded parallelism via `RESEARCH_DOCUMENT_PHASE_CONCURRENCY`.
5. If temporary download directories are created for URL sources, the system shall remove them after completion or failure.
6. The run shall persist severity-ranked findings, exploit reasoning, implemented fixes, confidence deltas, and next-iteration hypotheses before completion.

## Iteration 9 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=9`, the run shall prioritize test and regression blind spots in security-sensitive flows.
2. If iteration 8 lessons require explicit cross-path contracts, iteration 9 shall enforce equivalent policy contracts across redirect paths and regression harness entrypoints.
3. When URL downloads receive redirect responses, the system shall validate each redirect target before issuing the next request.
4. If redirect depth exceeds policy or redirect metadata is malformed, the system shall return deterministic policy errors and stop download.
5. When direct-call tests import decorated FastMCP tools, the test module shall unwrap tool wrappers before awaiting calls.
6. The run shall persist severity-ranked findings, exploit reasoning, implemented fixes, confidence deltas, and next-iteration hypotheses before completion.

## Iteration 10 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=10`, the run shall prioritize synthesis and prioritized remediation planning across iterations 1-9.
2. If iteration 9 lessons identify regression-harness drift risk, iteration 10 shall implement at least one consolidated regression control derived from those lessons.
3. When the recurring security review executes, the system shall provide one command that runs high-impact security regression checks.
4. If synthesis identifies residual risks that remain open after iteration 10, the run shall rank them by severity/urgency and document next actions in `ops/review-cycle/final-report.md`.
5. The run shall advance cycle state beyond iteration 10 and persist final confidence deltas, lessons learned, and post-cycle hypotheses.
