# Iteration 05 Report - Cache and Data Integrity

Date: 2026-03-01T07:03:30Z
Branch: codex/review/i05
Focus: Iteration 5 - cache and data integrity

## Mission Rewritten as Concise EARS Requirements
1. When iteration state is loaded with `current_iteration=5`, the run shall prioritize cache and persisted-state integrity controls.
2. If iteration 4 lessons emphasize centralized and comprehensive control-plane protections, iteration 5 shall apply a shared integrity hardening pattern across both analysis cache and context-cache registry persistence.
3. When cache data is written to disk, the system shall commit updates atomically so failed writes do not corrupt previously committed cache state.
4. If persisted context-cache registry content contains malformed shapes or non-string entries, the loader shall ignore invalid entries and shall only materialize validated mappings.
5. When review findings are produced, the run shall record severity, exploit reasoning, concrete fixes, validation evidence, lessons learned, and next-iteration hypotheses.
6. The run shall persist updated cycle artifacts (`state.json`, learning log, playbook, risk register, prompt evolution, and iteration report) before completion.

## Scope Detection Evidence (Before/After Git Transitions)
- Before creating `codex/review/i05`:
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`
- After creating `codex/review/i05` from `origin/codex/review-mainline`:
  - `{"mode": "none", "reason": "No local changes and no ahead commits to review.", "branch": "HEAD", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 0, "pr_context": false, "pr_url": null}`

## Required Reading Checklist
- `AGENTS.md`, `src/AGENTS.md`, `tests/AGENTS.md`
- `docs/ARCHITECTURE.md`, `docs/DIAGRAMS.md`
- `docs/tutorials/ADDING_A_TOOL.md`, `docs/tutorials/WRITING_TESTS.md`

## Findings (Ordered by Severity)

### F-501 (High) - Analysis cache writes were non-atomic and could lose integrity on partial failure
- Evidence:
  - `src/video_research_mcp/cache.py` wrote final cache files directly via `p.write_text(...)`.
- Exploit reasoning:
  - Interrupted writes or filesystem errors can leave truncated/invalid JSON at the committed path, turning valid cached analyses into unreadable state and increasing recomputation churn.
- Concrete fix:
  - Switched `cache.save(...)` to atomic commit semantics using unique temp file + `replace(...)`.
- Implementation status:
  - Implemented with regression test `tests/test_cache.py::TestCache::test_save_is_atomic_when_replace_fails`.

### F-502 (Medium) - Context cache registry loader accepted malformed persisted shapes
- Evidence:
  - `src/video_research_mcp/context_cache.py::_load_registry` iterated nested JSON structure without validating top-level/object field types.
- Exploit reasoning:
  - Corrupted or malformed registry JSON could partially poison in-memory registry state, causing stale mappings, diagnostics drift, or unnecessary cache recreation attempts.
- Concrete fix:
  - Added strict shape filtering in `_load_registry` to load only `{str: {str: str}}` entries and ignore invalid structures.
- Implementation status:
  - Implemented with regression test `tests/test_context_cache.py::TestRegistryPersistence::test_load_ignores_invalid_shape_entries`.

### F-503 (Low) - Shared registry temp path could collide across concurrent writers
- Evidence:
  - `src/video_research_mcp/context_cache.py::_save_registry` used fixed `context_cache_registry.tmp` path for staging writes.
- Exploit reasoning:
  - Concurrent processes or rapid parallel writes can contend on a shared temp filename, increasing race/collision risk.
- Concrete fix:
  - Switched registry persistence to unique temp filenames before atomic replace.
- Implementation status:
  - Implemented in `_save_registry`.

## Implemented Changes
- `src/video_research_mcp/cache.py`
  - Added atomic write flow using unique tmp file and `Path.replace`.
- `src/video_research_mcp/context_cache.py`
  - Added unique tmp-file staging for registry writes.
  - Added strict shape validation when loading registry JSON.
- `tests/test_cache.py`
  - Added regression test proving failed replace does not overwrite prior committed payload.
- `tests/test_context_cache.py`
  - Added regression test verifying malformed registry entries are ignored.

## Validation Evidence
- Lint:
  - `uv run ruff check src/video_research_mcp/cache.py src/video_research_mcp/context_cache.py tests/test_cache.py tests/test_context_cache.py`
- Tests:
  - `PYTHONPATH=src uv run pytest tests/test_cache.py tests/test_context_cache.py tests/test_infra_tools.py -v`
  - Result: 74 passed

## Reflective Self-Learning Loop
- Observe evidence:
  - Cache layer wrote directly to final file path and registry loader accepted broad JSON shapes.
- Infer root causes:
  - Integrity controls were applied inconsistently across persistence boundaries; write/read guards were best-effort but not uniformly defensive.
- Proposed fix strategies:
  - Standardize atomic commit semantics across cache-related persistence paths.
  - Validate persisted structure before mutating in-memory registry state.
- Validate fixes:
  - Added targeted regression tests for replace failure preservation and malformed-shape filtering; all targeted checks passed.
- Confidence change:
  - Cache write integrity confidence: 0.58 -> 0.86.
  - Registry load integrity confidence: 0.61 -> 0.84.
  - Overall iteration-5 objective confidence: 0.57 -> 0.85.

## Lesson-Carried Remediation (Required N-1 linkage)
- Derived from iteration 4 lesson: "controls must be centralized and comprehensive."
- Applied in iteration 5:
  - Used a unified persistence hardening pattern (atomic staged writes) across both analysis cache and context-cache registry, instead of hardening only one subsystem.

## Lessons Learned
1. Integrity hardening is strongest when write and load paths are treated as a single contract, not independent best-effort helpers.
2. Atomic writes must use unique staging files to avoid temp-path collisions in multi-process environments.
3. Loader-side schema validation prevents malformed state propagation and keeps diagnostics trustworthy.

## Next-Iteration Hypotheses (Iteration 6)
1. Evaluate whether partial source failures in research-document ingestion should surface explicit skipped-source metadata to strengthen fault isolation transparency.
2. Review tool-level exception boundaries to ensure localized failures cannot silently mask degraded outputs.
3. Expand deterministic error categorization for local persistence failures where recovery guidance can be made explicit.

## Scope Detection Evidence (Commit Transition)
- Before commit on `codex/review/i05`:
  - `{"mode": "uncommitted", "reason": "Working tree has local changes.", "branch": "codex/review/i05", "base_branch": "main", "uncommitted_files": 10, "ahead_commits": 7, "pr_context": false, "pr_url": null}`
- After commit on `codex/review/i05`:
  - `{"mode": "commits", "reason": "Branch is ahead of base with no local unstaged/uncommitted files.", "branch": "codex/review/i05", "base_branch": "main", "uncommitted_files": 0, "ahead_commits": 8, "pr_context": false, "pr_url": null}`
