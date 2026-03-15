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
2. If iteration 6 lessons emphasize explicit integrity boundaries, iteration 7 shall apply that pattern to untrusted prompt inputs by labeling and delimiting them.
3. When query text or retrieved properties are inserted into model prompts, the system shall mark those values as untrusted and instruct the model to ignore embedded instructions.
4. If adversarial text attempts instruction override (for example "ignore previous instructions"), regression tests shall verify hardened prompt contracts remain present.
5. The run shall record severity-ranked findings, exploit reasoning, implemented or patch-ready remediations, and confidence deltas in review-cycle artifacts.

## Iteration 8 Mission Rewritten as EARS Requirements
1. When iteration state indicates `current_iteration=8`, the run shall prioritize concurrency and resource-exhaustion risks.
2. If iteration 7 lessons identify untrusted prompt-boundary gaps, iteration 8 shall implement at least one remediation directly derived from those lessons.
3. When second-pass schema reshaping consumes untrusted fetched content, the system shall delimit untrusted fields and instruct the model to ignore embedded instructions.
4. When document preparation fans out downloads or uploads, the system shall apply bounded concurrency controls.
5. The run shall persist severity-ranked findings, exploit reasoning, implemented fixes, confidence deltas, and iteration-9 hypotheses in review-cycle artifacts.

## Iteration 8 Continuation Mission Rewritten as EARS Requirements
1. When iteration state remains `current_iteration=8` with an open iteration PR, the run shall resume that branch and avoid creating a new iteration branch.
2. When any document-research phase performs per-document model fan-out, the system shall enforce bounded concurrency.
3. If focused concurrency tests exist, the run shall validate the new cap with deterministic peak-concurrency assertions.
4. If full-module regression execution remains unstable due known harness drift, the run shall record that limitation in iteration notes and keep the risk open.
5. The run shall persist updated findings, fixes, lessons, and confidence deltas to all review-cycle artifacts.

## Iteration 8 Continuation (Configurable Caps) Mission Rewritten as EARS Requirements
1. When iteration state remains `current_iteration=8` and R-013 residual risk is open, the run shall prioritize configurable concurrency controls over additional fixed-cap changes.
2. When document preparation or document phase execution initializes concurrency limits, the system shall read limits from runtime config instead of hard-coded constants.
3. If a configured document concurrency value is outside `1..16`, config loading shall fail with a validation error.
4. When config-driven caps are introduced, the run shall add focused tests for env override parsing and out-of-range rejection.
5. The run shall persist updated findings, exploit reasoning, fix status, and confidence deltas in iteration-8 artifacts.

## Iteration 8 Continuation Mission Rewritten as EARS Requirements (Local Payload Guardrail Supplement)
1. When iteration state remains `current_iteration=8` and branch `codex/review/i07` is active, the run shall continue without creating a new iteration branch.
2. If iteration-8 lessons identify remaining resource-exhaustion vectors, the run shall apply at least one ingress guard that limits worst-case memory usage.
3. When local files are ingested for content analysis, the system shall reject files larger than configured `DOC_MAX_DOWNLOAD_BYTES` before reading bytes.
4. When compare-mode batch content analysis builds file parts, the system shall reuse the same guarded ingestion path as single-file analysis.
5. The run shall record scope snapshots, severity-ranked findings, validation evidence, confidence deltas, and iteration-9 hypotheses in review-cycle artifacts.

## Iteration 8 Continuation Mission Rewritten as EARS Requirements (Aggregate Payload and Prompt-Boundary Extension)
1. When iteration state remains `current_iteration=8` with PR `#59` open, the run shall resume the existing iteration branch context and shall not create a new iteration branch.
2. When compare-mode content analysis aggregates multiple local files, the system shall enforce a configured aggregate payload ceiling before reading/assembling model parts.
3. If total compare payload bytes exceed the configured ceiling, the tool shall fail fast with structured tool error output before any model call.
4. If iteration-7 lessons require explicit untrusted-input boundaries, file/text analysis prompts shall include anti-injection guardrails and a tagged task-instruction boundary.
5. The run shall capture pre/post transition review-scope snapshots and persist findings, fixes, confidence deltas, and next hypotheses in review-cycle artifacts.

## Iteration 8 Continuation Mission Rewritten as EARS Requirements (Temp Artifact Cleanup)
1. When iteration state remains `current_iteration=8` and iteration PR `#59` is open, the run shall resume `codex/review/i07` and avoid creating a new branch.
2. If iteration-8 lessons show residual resource usage in helper layers, the run shall implement at least one cleanup control that bounds non-memory resource growth.
3. When URL documents are downloaded for preparation, the system shall use a scoped temporary directory and shall clean it after upload processing completes.
4. If cleanup controls are added to document preparation helpers, the run shall add deterministic regression tests proving cleanup occurs post-processing.
5. The run shall persist scope snapshots, severity-ranked findings, exploit reasoning, fixes, and confidence deltas in iteration artifacts.

## Iteration 8 Continuation Mission Rewritten as EARS Requirements (Source-Count Guardrail)
1. When iteration state remains `current_iteration=8` with PR `#59` open, the run shall resume existing branch context and shall not create a new iteration branch.
2. When `research_document` receives `file_paths` and/or `urls`, the system shall enforce a configured maximum number of total sources before preparation starts.
3. If provided source count exceeds the configured maximum, the tool shall fail fast with structured tool error output and shall skip document preparation/model calls.
4. If iteration-8 lessons emphasize ingress guardrails, this run shall add config validation plus regression coverage for the source-count limit.
5. The run shall persist scope snapshots, severity-ranked findings, exploit reasoning, fixes, confidence deltas, and iteration-9 hypotheses in review-cycle artifacts.

## Iteration 8 Continuation Mission Rewritten as EARS Requirements (2026-03-15T14:17:05Z)
1. When iteration state indicates `current_iteration=8`, the run shall prioritize concurrency and resource-exhaustion controls in batch analysis paths.
2. If iteration 7 lessons require explicit untrusted-content boundaries, the run shall apply at least one prompt-hardening remediation in a remaining extraction path.
3. When batch video/content analysis runs in individual mode, the system shall enforce configurable bounded concurrency via validated runtime configuration.
4. If `BATCH_TOOL_CONCURRENCY` is unset, the system shall default to a safe cap of `3` and validate configured values in the range `1..16`.
5. When `content_extract` builds extraction prompts from user-provided text, the prompt shall treat content as untrusted data and explicitly reject embedded instruction execution.
6. The run shall persist severity-ranked findings, exploit reasoning, fixes, validation output, and confidence deltas to review-cycle artifacts before completion.

## Iteration 8 Continuation Mission Rewritten as EARS Requirements (2026-03-15T15:04:01Z)
1. When iteration state indicates `current_iteration=8` with branch `codex/review/i07` active, the run shall resume existing branch context and shall not create a new iteration branch.
2. When URL document downloads are configured with a byte limit larger than Gemini's single-file ingest ceiling, the system shall cap effective download bytes to `50MB` before network transfer.
3. If effective download bytes exceed the ingest ceiling, the tool shall fail fast during download rather than after expensive transfer/upload work.
4. If iteration-7 lessons require explicit untrusted-data boundaries, document-research prompt templates shall instruct models to ignore command-like content embedded in documents and intermediate findings.
5. The run shall persist scope snapshots, severity-ranked findings, exploit reasoning, implemented fixes, validation outputs, and confidence deltas to review-cycle artifacts before completion.
