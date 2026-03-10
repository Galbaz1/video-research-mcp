<<<<<<< ours
# Knowledge Ingest UX — Problem Analysis, Plan & Grounding

Last updated: 2026-03-05 20:42 CET

> Date: 2026-03-05
> Status: Approved for implementation
> Reviewed by: Claude Opus 4.6 + GPT Plan Reviewer (Codex)

## Problem

When calling `knowledge_ingest`, users and LLM agents must **guess property names** for each Weaviate collection. The tool accepts a generic `dict` for `properties` and validates against the collection schema at runtime — but the schema is never exposed.

This creates a trial-and-error loop:

```
1. Call knowledge_ingest with intuitive property names
2. Get "Unknown properties" error (no hints about what IS allowed)
3. Search existing objects to reverse-engineer the schema
4. Retry with (hopefully) correct names
5. Hit type errors (e.g., string instead of text[])
6. Retry again
```

### Session Evidence (2026-03-05)

Real-world session: GPT-5.4 video analysis with cross-platform sentiment research via 4 parallel researcher agents.

**8 failed calls** before successful ingestion:

| Collection | Rejected Properties | Correct Properties |
|------------|--------------------|--------------------|
| `VideoMetadata` | `channel`, `local_filepath`, `source_url`, `screenshot_dir` | `channel_title` |
| `VideoAnalyses` | `key_points` as string | `key_points` as `text[]` |
| `CommunityReactions` | `platform`, `reaction_summary`, `sentiment_score`, `source_url` | `consensus`, `themes_positive`, `themes_critical`, `notable_opinions_json` |
| `ResearchFindings` | `finding`, `sources` | `claim`, `supporting` |
| `ConceptKnowledge` | `category`, `name`, `related_concepts` | `concept_name`, `description`, `state`, `source_tool` |

### Impact

- **Token waste**: ~500-1000 tokens per failed attempt (8 failures = ~6000 tokens wasted)
- **Agent failures**: Background agents can't self-correct without a schema discovery mechanism
- **Adoption barrier**: New users hit this wall on first manual ingest
- **Stale docs**: `docs/tutorials/KNOWLEDGE_STORE.md:339` claims the error already lists allowed fields — it doesn't

## Root Cause

The schema is defined in `weaviate_schema/*.py` as `CollectionDef` objects with `name`, `data_type`, and `description` per property. The `ALLOWED_PROPERTIES` dict in `tools/knowledge/helpers.py` validates against these at runtime (line ~17). But this information is **never surfaced** to the caller — not in errors, not in docstrings, not via any discovery tool.

### Key code locations

| File | What |
|------|------|
| `src/video_research_mcp/weaviate_schema/base.py:15` | `CollectionDef` dataclass — `name`, `data_type`, `description` (no `required` field) |
| `src/video_research_mcp/weaviate_schema/collections.py` | All 12 collection definitions with property lists |
| `src/video_research_mcp/tools/knowledge/helpers.py:17` | `ALLOWED_PROPERTIES` dict — source of truth for validation |
| `src/video_research_mcp/tools/knowledge/ingest.py:52-56` | Validation logic — rejects unknown keys, but error only shows rejected names |
| `src/video_research_mcp/tools/knowledge/__init__.py:5` | Tool registration — currently exports 7 tools |
| `docs/tutorials/KNOWLEDGE_STORE.md:339` | Stale claim that error lists allowed fields |

## Plan

Six changes, ordered by dependency. All ship together in one PR.

### Step 1: Enrich error message in `knowledge_ingest` (3-5 lines)

**File**: `tools/knowledge/ingest.py:54`

Current error:
```python
f"Unknown properties for {collection}: {sorted(unknown)}"
```

New error — includes `name:type` pairs and a pointer to the schema tool:
```python
f"Unknown properties for {collection}: {sorted(unknown)}. "
f"Allowed: {', '.join(f'{k}:{v}' for k, v in sorted(allowed_with_types.items()))}. "
f"Use knowledge_schema(collection='{collection}') for full details."
```

**Rationale**: Reactive fix. Even without the schema tool, this halves the trial-and-error loop by showing correct names AND types in the error itself.

### Step 2: Fix stale documentation (1-2 lines)

**File**: `docs/tutorials/KNOWLEDGE_STORE.md:339`

The tutorial claims the error already shows allowed fields. This is false. Either update the text to match the new behavior (after step 1) or remove the inaccurate claim.

### Step 3: Add `knowledge_schema` tool (~40 lines)

**File**: New tool, likely in `tools/knowledge/schema.py` or added to an existing knowledge tool file.

```python
@knowledge_server.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def knowledge_schema(
    collection: Annotated[
        KnowledgeCollection | None,
        Field(description="Collection name, or omit for all collections"),
    ] = None,
) -> dict:
    """Show the property schema for knowledge collections.

    Returns property names, types, and descriptions. Use before
    knowledge_ingest to see what properties are expected.

    Args:
        collection: Optional collection name to filter.

    Returns:
        Dict with collection schemas.
    """
```

Key design decisions:

- **No Weaviate connection required** — reads from local `CollectionDef` Python objects, not from the Weaviate instance. Works even when `WEAVIATE_URL` is empty.
- **No `required` flag** — `CollectionDef` has no concept of required vs optional. Don't fabricate metadata that doesn't exist.
- **Single-collection is the primary path** — all-collections response can bloat agent context (12 collections x ~10 properties each). Single-collection lookup should be the recommended usage.
- **Compact response** — return `name`, `type`, `description` per property. No references (those aren't writable via `knowledge_ingest`).

### Step 4: Register tool + add discoverability hint (5 lines)

**Files**:
- `tools/knowledge/__init__.py` — add `knowledge_schema` to exports
- `tools/knowledge/ingest.py` — add one line to `knowledge_ingest` docstring:

```python
"""Manually insert data into a knowledge collection.

Tip: call knowledge_schema(collection=...) first to see expected properties.
...
"""
```

**Rationale**: A tool only helps if callers know it exists. The docstring hint is the discoverability bridge from ingest to schema. Unlike fix #3 (rejected docstring with hardcoded field lists), this is a pointer — it won't go stale.

### Step 5: Tests (4 cases, ~60 lines)

**File**: `tests/test_knowledge_schema.py` (or added to existing knowledge test file)

| Test | What it verifies |
|------|-----------------|
| `test_knowledge_schema_single_collection` | Returns correct properties for one collection |
| `test_knowledge_schema_all_collections` | Returns all 12 collections with schemas |
| `test_knowledge_schema_no_weaviate` | Works without Weaviate configured |
| `test_knowledge_ingest_error_shows_allowed` | Error message includes `name:type` pairs and schema hint |

### Step 6: Documentation updates (~10 lines across files)

Update all references to "7 knowledge tools" to "8 knowledge tools":

| File | Location |
|------|----------|
| `README.md` | Tool count in features section |
| `CLAUDE.md` | Architecture table — knowledge row |
| `docs/ARCHITECTURE.md` | Knowledge sub-server section |
| `docs/tutorials/KNOWLEDGE_STORE.md` | Tool inventory + fixed stale claim (step 2) |

Add `knowledge_schema` to the knowledge tool table with description.

## Grounding — Why This Plan, Not Alternatives

### Why not just fix #2 (error message) alone?

Fix #2 is reactive — it only helps **after** a failure. For human users, one failure + good error is acceptable. For **agent workflows** (the primary consumer of these tools), any failure is a wasted round-trip. The schema tool enables first-try success, which is the real goal.

### Why not fold schema info into the error message and skip the separate tool?

The error message should be actionable (it now will be), but it's the wrong place for full documentation. Errors are reactive; schema discovery is proactive. Different usage patterns, different tools.

### Why not hardcode property lists in the docstring (fix #3)?

Creates a second source of truth that **will** drift from the actual schema. Every schema change requires remembering to update the docstring — and forgetting is silent (no test catches it). The pointer-based approach (step 4) is durable: it says "ask the schema tool" rather than "here are the fields."

### Why no `required` vs `optional`?

`CollectionDef` in `weaviate_schema/base.py` has three fields: `name`, `data_type`, `description`. There is no `required` attribute. Fabricating one would be dishonest. If required/optional semantics are added to the schema later, `knowledge_schema` can expose them then.

### Why must `knowledge_schema` work without Weaviate?

The schema is defined in Python code (`weaviate_schema/collections.py`), not in the Weaviate instance. Requiring a live Weaviate connection would make the tool useless in the exact scenario where it's most needed: initial setup, testing, and agents running without a configured knowledge store. The validation in `helpers.py` already works from local data — the schema tool should too.

### Why ship all 6 steps together?

Steps 1-2 are trivially small. Step 3 is the core feature. Steps 4-6 are housekeeping. Splitting across PRs creates intermediate states where docs are wrong or the discoverability bridge is missing. One atomic PR is cleaner.

## Effort Estimate

| Step | Lines changed | Risk |
|------|--------------|------|
| 1. Error message | 3-5 | None |
| 2. Stale docs | 1-2 | None |
| 3. Schema tool | ~40 | Low — read-only, no side effects |
| 4. Registration + hint | ~5 | None |
| 5. Tests | ~60 | None |
| 6. Doc updates | ~10 | None |
| **Total** | **~120** | **Low** |

## Decision Log

| Decision | Chose | Over | Why |
|----------|-------|------|-----|
| Priority order | #2 first, #1 next | #1 first | Error fix is 3 lines with zero risk; ship immediately |
| Fix #3 | Skip | Implement | Fragile, creates drift risk, unnecessary with #1+#2 |
| `required` field | Omit | Include | No source of truth in `CollectionDef` |
| Weaviate dependency | Not required | Required | Schema is local Python data, not instance data |
| Separate tool vs error-only | Separate tool | Fold into error | Different usage patterns (proactive vs reactive) |
| Ship strategy | Single PR | Split PRs | Avoids intermediate broken states |
=======
# Plugin Deep Research & Optimization Program Plan (Executed)

## A) Executive Summary

- This is a **24-week (6-month)** optimization program for the plugin product (npm installer + PyPI MCP runtime).
- Program assumes a **core team of 8 specialists** with part-time security and UX support.
- Success is gated by measurable criteria: reliability, compatibility, upgrade safety, latency, and release confidence.
- Work is split into 6 phases with hard go/no-go exits.
- Primary risk areas: upgrade safety, tool contract drift, skill-routing ambiguity, and release regressions.
- By Week 24, target outcomes are: zero critical installer regressions in release candidates, >99.5% tool contract compatibility across stable tools, and <2% rollback rate for plugin updates.
- Quality governance uses weekly architecture/quality/release/risk reviews with named sign-offs.
- Validation evidence is mandatory for every phase (test reports, benchmark dashboards, migration simulations, release checklists).
- Program includes a non-regression matrix covering installer, manifest protection, MCP config merge, discoverability, and contract stability.
- First 2 weeks focus on baseline instrumentation, contract inventory, and failure-mode mapping.

## B) Assumptions and Constraints

1. Repo is the full plugin product (distribution + runtime).
2. No breaking changes to public tool contracts without versioning and migration notes.
3. Test suite remains API-mocked; no live external API calls in CI.
4. Team capacity baseline: 8 FTE equivalent.
5. All phase exits require artifact evidence checked into `docs/metrics/` or CI artifacts.

## C) Phase Plan

## Phase 0 (Weeks 1-2): Baseline and Risk Mapping

- **Objective:** Create trustworthy baselines for reliability, compatibility, and release risk.
- **In scope:** `bin/`, `src/`, `tests/`, `docs/RELEASE_CHECKLIST.md`, `docs/PLUGIN_DISTRIBUTION.md`.
- **Out of scope:** Feature additions.
- **Dependencies:** None.
- **Workstreams/Owners:**
  - Runtime Architect: tool inventory + contract snapshot.
  - Installer Engineer: install/upgrade/uninstall flow map.
  - Test Lead: baseline CI metrics and flaky-test census.
  - Release Engineer: release pipeline baseline.
- **Deliverables:**
  1. Tool contract manifest (JSON) for all exposed tools.
  2. Installer path-state matrix (new install, upgrade, forced overwrite, uninstall).
  3. Baseline report: test pass %, p95 runtime latency (mock harness), failure taxonomy.
- **Definition of Done (DoD):**
  - Contract manifest generated and committed with 100% tool coverage.
  - >=20 installer failure scenarios documented and reproducible.
  - Baseline CI report produced across 5 consecutive runs with >=98% pass rate and flaky test list <=10 tests.
- **Exit Gate (Go/No-Go):** Go only if all baseline artifacts exist and are reproducible by a second engineer.
- **Estimate:** 2 weeks.

## Phase 1 (Weeks 3-6): Installer Hardening

- **Objective:** Make install/upgrade/uninstall behavior deterministic and safe.
- **In scope:** `bin/install.js`, `bin/lib/copy.js`, `bin/lib/manifest.js`, `bin/lib/config.js`, installer tests.
- **Out of scope:** Runtime tool logic.
- **Dependencies:** Phase 0 artifacts.
- **Workstreams/Owners:**
  - Installer Engineer: idempotency + migration safeguards.
  - Test Lead: scenario automation.
  - Release Engineer: backward compatibility checks.
- **Deliverables:**
  1. Automated installer scenario suite (minimum 40 scenarios).
  2. Manifest safety proof tests for user-modified files.
  3. MCP config merge compatibility tests across 5 representative configs.
- **DoD:**
  - 40/40 installer scenarios pass in CI on Linux and macOS runners.
  - 0 data-loss defects in 200 simulated upgrade runs.
  - 100% of user-modified-file protection tests pass.
  - `.mcp.json` merge preserves unrelated user entries in 100% of test fixtures.
- **Exit Gate:** Go only with zero critical severity defects open in installer label.
- **Estimate:** 4 weeks.

## Phase 2 (Weeks 7-11): Tool Contract Reliability

- **Objective:** Eliminate contract drift and enforce structured-output consistency.
- **In scope:** `src/tools/**`, shared types, tool-level tests.
- **Out of scope:** New external integrations.
- **Dependencies:** Contract manifest from Phase 0.
- **Workstreams/Owners:**
  - Runtime Architect: schema guardrails + error-shape consistency.
  - Test Lead: contract test expansion.
  - Observability Engineer: tracing coverage checks.
- **Deliverables:**
  1. Contract compatibility test harness.
  2. Standardized error-shape conformance checks.
  3. Structured-output schema validation report.
- **DoD:**
  - >=99.5% contract compatibility against baseline manifest.
  - 100% tools return documented error dict shape under injected failure tests.
  - 0 uncaught exceptions in 10k mocked tool invocations.
  - Tracing decorator present on 100% of tool entry points (static check).
- **Exit Gate:** Go only if contract compatibility >=99.5% and no P0/P1 contract regressions.
- **Estimate:** 5 weeks.

## Phase 3 (Weeks 12-16): Skills/Agents Quality and Routing Fidelity

- **Objective:** Improve instruction quality and reduce tool-selection errors.
- **In scope:** `skills/**`, `agents/**`, command markdown routing guidance.
- **Out of scope:** Runtime protocol changes.
- **Dependencies:** Stable contracts from Phase 2.
- **Workstreams/Owners:**
  - Prompt Architect: skill rewrite + anti-pattern refinement.
  - UX Researcher: command intent sampling.
  - Test Lead: routing eval suite.
- **Deliverables:**
  1. Skill quality rubric and scored assessments.
  2. Routing benchmark dataset (>=300 prompts).
  3. Updated skills/agents with measurable acceptance criteria.
- **DoD:**
  - Routing top-1 correct tool-family selection >=92% on benchmark set.
  - Hallucinated tool reference rate <=1.5%.
  - Skill rubric average score >=4.2/5 across all shipped skills.
  - Regression set pass rate >=98% across 3 consecutive runs.
- **Exit Gate:** Go only if routing accuracy and hallucination thresholds are met.
- **Estimate:** 5 weeks.

## Phase 4 (Weeks 17-20): Performance and Observability

- **Objective:** Improve latency predictability and diagnostics.
- **In scope:** runtime hot paths, caching behavior, tracing/reporting docs.
- **Out of scope:** installer changes except telemetry hooks.
- **Dependencies:** Phase 2 stability.
- **Workstreams/Owners:**
  - Performance Engineer: benchmark + optimization.
  - Observability Engineer: dashboard + alert thresholds.
  - Runtime Architect: cache/session tuning.
- **Deliverables:**
  1. Benchmark harness and latency dashboard.
  2. Hot-path optimization PRs.
  3. Alerting thresholds and SLO doc.
- **DoD:**
  - p95 mocked end-to-end tool latency improved by >=25% vs Phase 0 baseline.
  - p99 latency variance reduced by >=30%.
  - 100% critical tool categories represented on dashboard.
  - Alert MTTR playbook validated in 3 simulation drills.
- **Exit Gate:** Go only with latency targets met and dashboard live.
- **Estimate:** 4 weeks.

## Phase 5 (Weeks 21-24): Release Hardening and GA Readiness

- **Objective:** Ship safely with controlled rollout and rollback confidence.
- **In scope:** release docs/process, upgrade migrations, smoke tests, RC validation.
- **Out of scope:** major architecture refactors.
- **Dependencies:** Phases 1-4 complete.
- **Workstreams/Owners:**
  - Release Engineer: staged rollout plan.
  - QA Lead: RC gates + rollback drills.
  - Product Lead: GA sign-off.
- **Deliverables:**
  1. RC checklist and signed gate sheet.
  2. Canary rollout results.
  3. Rollback drill report.
- **DoD:**
  - 2 successful RC cycles with zero critical regressions.
  - Canary cohort (>=50 installs) shows rollback rate <2% and install success >=99%.
  - Mean time to rollback <15 minutes in simulation.
  - Final GA sign-off by Architecture + QA + Release + Product.
- **Exit Gate:** GA only if all sign-offs complete and metrics thresholds met.
- **Estimate:** 4 weeks.

## D) Prioritized Backlog (Top Items)

| Work Item | Category | Impact | Effort | Confidence | Risk Reduction | Priority Score |
|---|---|---:|---:|---:|---:|---:|
| Installer scenario automation | installer | 5 | 3 | 5 | 5 | 41.67 |
| Tool contract manifest + compat tests | runtime | 5 | 3 | 4 | 5 | 33.33 |
| `.mcp.json` merge invariant tests | installer | 5 | 2 | 4 | 4 | 40.00 |
| Skills routing benchmark suite | skills | 4 | 3 | 4 | 4 | 21.33 |
| Error-shape conformance checks | runtime | 4 | 2 | 5 | 4 | 40.00 |
| Release rollback drill automation | release | 4 | 2 | 4 | 5 | 40.00 |
| Latency benchmark harness | runtime | 4 | 3 | 4 | 4 | 21.33 |
| Flaky-test quarantine + burn-down | tests | 3 | 2 | 5 | 4 | 30.00 |

## E) Milestones and Staffing Model

- **Day 30:** Baseline complete + installer risk map + first automated scenarios.
- **Day 60:** Installer hardening gates passed; zero critical installer defects.
- **Day 90:** Contract reliability and routing benchmarks operational; first measurable quality lift.
- **Month 4-6:** Performance targets met, two successful RCs, GA readiness gates passed.

Staffing baseline: 8 FTE (2 runtime, 2 installer/release, 2 test/quality, 1 prompt/skills, 1 observability/perf) + 0.5 UX + 0.5 security advisor.

## F) DoD Catalog (Measurable)

1. **Installer Safety DoD:** 200 upgrade simulations, 0 data-loss events, 100% manifest protection tests pass, evidence: CI artifact `installer-sim-report.json`.
2. **Contract Stability DoD:** >=99.5% compatibility, 0 P0/P1 regressions, evidence: `contract-compat-report.json`.
3. **Routing Fidelity DoD:** >=92% top-1 tool-family accuracy on >=300 benchmark prompts, hallucination <=1.5%, evidence: `routing-eval.csv` + summary markdown.
4. **Performance DoD:** p95 latency >=25% better than baseline and p99 variance >=30% better, evidence: benchmark dashboard export.
5. **Release Readiness DoD:** 2 RCs with zero critical regressions; canary install success >=99%, rollback <2%, evidence: signed release gate sheet.

## G) Validation Matrix (Non-Regression)

| Area | Validation Method | Threshold | Artifact |
|---|---|---|---|
| Installer behavior | scenario suite | 100% pass of 40 scenarios | CI junit + JSON |
| Upgrade behavior | simulation harness | 0 data-loss in 200 runs | upgrade report |
| User-modified file protection | manifest tests | 100% pass | test logs |
| MCP registration integrity | config merge tests | 100% fixture conformance | merge report |
| Tool contract compatibility | manifest diff + tests | >=99.5% compatible | compat report |
| Discoverability | command/skill/agent scan tests | 100% expected assets found | scan report |

## H) Risk Register (Top 15)

1. Silent installer overwrite of user edits.
2. Contract drift between docs and runtime.
3. Skill instructions referencing stale tool signatures.
4. Hidden regressions in `.mcp.json` merge.
5. Flaky tests masking release blockers.
6. Performance regressions from safety wrappers.
7. Incomplete rollback procedures.
8. Missing observability for slow failure classes.
9. Inconsistent error dict schemas.
10. Multi-platform path handling edge cases.
11. Unclear ownership across installer/runtime boundaries.
12. Benchmark datasets unrepresentative of real prompts.
13. Excessive scope expansion mid-program.
14. Release gate waivers without evidence.
15. Documentation lag causing operator error.

## I) First 2-Week Sprint (Day-Level)

- **Day 1-2:** Build tool inventory script + capture baseline contract manifest.
- **Day 3-4:** Map installer state machine and enumerate failure scenarios.
- **Day 5:** Draft baseline metric schema and artifact paths.
- **Day 6-7:** Implement first 15 installer scenario tests.
- **Day 8-9:** Generate CI baseline over 5 runs and flaky census.
- **Day 10:** Run risk review and finalize Phase 0 gate checklist.

## J) Open Questions (Max 10)

1. Which tool contracts are explicitly versioned vs implicitly stable?
2. What environments must installer support beyond Linux/macOS?
3. What is acceptable canary cohort size for GA?
4. Are there enterprise-specific `.mcp.json` merge constraints?
5. Which skill routing errors are currently highest user pain?
6. What release cadence should this roadmap align to?
7. Which metrics are mandatory for exec-level reporting?
8. What rollback communication channel and SLA is expected?
9. Are there legal/security review steps before GA?
10. What changes require explicit migration guides?
>>>>>>> theirs
