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
1. The system shall load all review-cycle memory artifacts before selecting iteration work.
2. When iteration 2 runs, the system shall review validation and schema contracts and produce severity-ranked findings.
3. When a git-state transition is about to occur, the system shall run `scripts/detect_review_scope.py --json` before and after and record outputs.
4. When list-typed inputs cross tool boundaries, the system shall enforce strict `list[str]` validation at ingress.
5. If redirect-following downloads are used, the system shall validate each redirect hop and block policy-violating targets.
6. The system shall persist learning outcomes, confidence deltas, and next-iteration hypotheses at run end.

## Quality delta (iteration 2)
- Before: validation checks were distributed and permissive for malformed JSON-RPC list inputs.
- After: explicit ingress validation rules are codified, reusable, and test-backed.
