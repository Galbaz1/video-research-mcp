# Review Cycle Learning Log

## Iteration 1 (Architecture and Trust Boundaries) - 2026-03-01T03:26:51Z
- Observation: `content_analyze` accepted arbitrary URLs and passed them directly into Gemini `UrlContext` without applying the repo's SSRF policy gate.
- Inference: Trust boundary handling was inconsistent; URL hardening existed for document downloads (`url_policy.py`) but not for URL-context analysis.
- Strategy: Reuse `validate_url()` at tool ingress to unify outbound URL controls across tooling.
- Validation: Added guard in `content_analyze` and a regression test to assert non-HTTPS URLs are rejected pre-model-call.
- Confidence change: 0.55 -> 0.80 for URL-boundary consistency in content tooling after patch + test.
- Delivery confidence: 0.80 -> 0.88 after PR #30 merged cleanly into `codex/review-mainline`.

## Iteration 2 seed hypotheses
- Add an explicit per-tool trust policy matrix (local file, remote URL, external API) and test each edge.
- Evaluate whether `infra_*` mutating tools need an opt-in guard for non-local transports.

## Iteration 2 (Validation and Schema Contracts) - 2026-03-01T04:05:41Z
- Observation: Local filesystem inputs across multiple tools had no centralized boundary contract, while URL inputs already had shared policy controls.
- Inference: Validation strategy was asymmetric across trust boundaries, which increases policy drift risk and weakens schema-level ingress guarantees.
- Strategy: Introduce one shared local-path policy primitive and apply it at every local path ingress point.
- Validation: Added `LOCAL_FILE_ACCESS_ROOT` config, wired `enforce_local_access_root()` into all path-taking tool ingress points, and added focused regression tests.
- Confidence change: 0.42 -> 0.79 for local filesystem trust-boundary enforcement.
- Delivery confidence: 0.74 -> 0.82 after lint + targeted policy test pass.

## Iteration 3 seed hypotheses
- Validate external API failure categorization consistency (`make_tool_error`) under retries/timeouts.
- Add idempotency checks for partial-success batch/download flows.

## Iteration 3 (External API Failure Modes and Idempotency) - 2026-03-01T06:20:00Z
- Observation: Timeout/transport exceptions from async clients could bypass deterministic category mapping, and concurrent uploads with the same content hash could race before cache writes.
- Inference: Failure mode contracts depended on brittle string matching and non-atomic cache workflows, which weakens retry semantics and quota efficiency under concurrency.
- Strategy: Add typed network/timeout error categorization and introduce per-content-hash upload lock coordination in the File API upload path.
- Validation: Added regression tests for `make_tool_error()` timeout/network mappings and concurrent same-hash upload coalescing; focused lint/tests passed.
- Confidence change: 0.62 -> 0.82 for iteration-3 objective coverage.

## Iteration 4 seed hypotheses
- Review auth/capability guards for runtime-mutating tools (`infra_cache`, `infra_configure`).
- Audit secret propagation paths in logs and tool error payloads.

## Iteration 4 (Auth and Secret Handling) - 2026-03-01T06:03:47Z
- Observation: `infra_configure` returned `current_config` with non-Gemini secrets intact (`youtube_api_key`, `weaviate_api_key`), and mutating infra operations had no explicit capability gate.
- Inference: Control-plane mutators were effectively unauthenticated and config responses could leak credential material to any connected MCP client.
- Strategy: Add explicit infra mutation policy enforcement (`INFRA_MUTATIONS_ENABLED` + optional `INFRA_ADMIN_TOKEN`), redact all secret-bearing config fields from infra responses, and classify policy denial using typed `PermissionError` mapping.
- Validation: Implemented gating/redaction patches in `infra.py` + `config.py`, added typed `PERMISSION_DENIED` category in `errors.py`, and added focused infra-tool regression coverage; lint/tests passed.
- Confidence change: 0.51 -> 0.84 for auth/capability controls on infra mutators and config-secret non-disclosure.

## Iteration 5 seed hypotheses
- Audit cache/data-integrity invariants around context cache registry persistence and partial-write behavior.
- Review document/source ingestion paths for duplicate identity handling and stale-reference integrity drift.

## Iteration 5 (Cache and Data Integrity) - 2026-03-01T07:03:30Z
- Observation: `cache.save()` wrote directly to final JSON path, and `context_cache._load_registry()` accepted non-validated nested shapes from disk.
- Inference: Cache persistence and reload integrity contracts were asymmetrical; failed writes or malformed persisted data could degrade cache consistency and diagnostics reliability.
- Strategy: Apply staged atomic writes with unique temp files and enforce strict loader shape validation before mutating in-memory registry.
- Validation: Added atomic replace in `cache.py`, unique tmp registry persistence and schema-like filtering in `context_cache.py`, plus focused regression tests; targeted lint/tests passed.
- Confidence change: 0.57 -> 0.85 for cache/data-integrity objective coverage.

## Iteration 6 seed hypotheses
- Surface partial-source skips explicitly in research-document outputs to improve fault-isolation transparency.
- Audit tool exception boundaries for silent-degradation patterns where best-effort behavior hides missing evidence.

## Iteration 6 (Error Handling and Fault Isolation) - 2026-03-01T09:01:57Z
- Observation: `research_document` logged and skipped per-source download/upload failures during `_prepare_all_documents(...)`, but synthesis output did not disclose skipped sources.
- Inference: Fault handling favored availability but weakened evidence-integrity transparency, creating a silent-degradation path for downstream decisions.
- Strategy: Introduce structured preparation-failure capture across both download and upload phases, then expose that metadata in final `DocumentResearchReport` responses.
- Validation: Added `_prepare_all_documents_with_issues(...)`, threaded `preparation_issues` through quick/full synthesis paths, and added focused regression tests for helper-level and tool-level visibility; lint/tests passed.
- Confidence change: 0.60 -> 0.87 for fault-isolation transparency in document research ingestion.

## Iteration 7 seed hypotheses
- Evaluate prompt-injection and instruction-smuggling resistance across tools that combine untrusted content with system prompts.
- Add negative tests that prove malicious document/content strings cannot override tool safety constraints or policy gates.

## Iteration 7 (Prompt Injection and Tool Misuse Resistance) - 2026-03-01T16:03:02Z
- Observation: `knowledge` Flash post-processing built prompts by embedding query and hit properties directly in free-form text (`src/video_research_mcp/tools/knowledge/summarize.py`) without explicit untrusted-data framing.
- Inference: Untrusted retrieval content could attempt instruction smuggling (for example "ignore previous instructions") and reduce reliability of summary/property-selection outputs.
- Strategy: Apply iteration-6 lesson ("make implicit integrity boundaries explicit") to prompt boundaries by introducing explicit untrusted-data delimiters and hard model instructions to ignore embedded commands.
- Validation: Hardened `_build_prompt(...)` with `UNTRUSTED_QUERY`/`UNTRUSTED_HIT` wrappers and added adversarial regression coverage in `tests/test_knowledge_summarize.py::test_prompt_hardens_untrusted_query_and_properties`; focused lint + tests passed.
- Confidence change: 0.58 -> 0.81 for prompt-boundary robustness in knowledge summarization path.
- Delivery confidence: 0.81 -> 0.86 after targeted tests passed on branch `codex/review/i07`.

## Iteration 8 seed hypotheses
- Audit concurrency/resource-exhaustion risks in batch/document pipelines (`asyncio.gather` fan-out, upload/download parallelism) and add bounded concurrency controls where needed.
- Add negative tests covering adversarially large batch inputs to validate graceful degradation instead of resource spikes.

## Iteration 8 (Concurrency and Resource Exhaustion) - 2026-03-15T01:04:48Z
- Observation: `research_document_file._prepare_all_documents_with_issues(...)` used unbounded `asyncio.gather` for both URL downloads and File API uploads, and iteration-7 residual risk remained open for `_reshape_to_schema` prompt boundaries.
- Inference: Reliability controls were uneven across parallel paths; batch tools had semaphores while document preparation helpers and one multi-pass prompt path did not.
- Strategy: Apply one shared bounded-concurrency primitive to document preparation fan-out and apply iteration-7 untrusted-data boundary pattern to second-pass schema reshaping.
- Validation: Added bounded gather with `_DOC_PREPARE_CONCURRENCY=4`, hardened `_reshape_to_schema(...)` with untrusted delimiters/rules, and added focused regression coverage (`test_downloads_use_bounded_concurrency`, `test_url_fallback_hardens_untrusted_reshape_prompt`); targeted lint/tests passed.
- Confidence change: 0.61 -> 0.84 for iteration-8 objective coverage.
- Delivery confidence: 0.84 -> 0.89 after focused validations passed on `codex/review/i07`.

## Iteration 9 seed hypotheses
- Fix direct-call test harness drift where decorated tools appear as `FunctionTool` in subset runs.
- Add explicit callable-contract tests around `_unwrap_fastmcp_tools` behavior to prevent future regression blind spots.

## Iteration 8 Continuation (Phase Fan-out Hardening) - 2026-03-15T04:20:00Z
- Observation: While iteration-8 bounded download/upload fan-out in `research_document_file`, `research_document` still used unbounded `asyncio.gather` for per-document mapping/evidence model calls.
- Inference: Resource controls were stage-local rather than pipeline-wide, leaving residual quota and latency-spike risk under large document sets.
- Strategy: Reuse bounded concurrency pattern from iteration-8 ingestion helper inside phase executors via shared `_gather_bounded(...)`.
- Validation: Added `_DOC_PHASE_CONCURRENCY=4` and bounded execution for `_phase_document_map` and `_phase_evidence_extraction`; added focused regression tests proving peak concurrency stays capped.
- Confidence change: 0.84 -> 0.90 for iteration-8 objective completeness.

## Iteration 9 seed hypotheses (updated)
- Resolve the existing tool-wrapper/direct-call harness instability (R-004) that causes hangs in full-module subset runs.
- Add cancellability and backpressure tests for long-running async fan-out phases.

## Iteration 8 Continuation (Configurable Concurrency Caps) - 2026-03-15T04:03:39Z
- Observation: Iteration-8 fan-out limits were enforced but remained hard-coded (`4`) across preparation and phase execution, leaving R-013 residual risk open for deployment mismatch.
- Inference: Safety controls without validated operator tuning create a second-order reliability risk under heterogeneous runtime quotas/resources.
- Strategy: Preserve bounded execution but move caps to validated runtime config (`DOC_PREPARE_CONCURRENCY`, `DOC_PHASE_CONCURRENCY`, range `1..16`) and consume via `get_config()`.
- Validation: Added config fields/validators and targeted tests for env parsing + bounds, while keeping bounded concurrency assertions green in document pipeline tests.
- Confidence change: 0.90 -> 0.93 for iteration-8 objective closure quality.

## Iteration 9 seed hypotheses (reconfirmed)
- Close R-004 by making tool direct-call behavior deterministic across full and subset pytest runs.
- Add regression contracts for cancellation/backpressure on long-running fan-out phases.

## Iteration 8 Continuation (Local Payload Guardrail) - 2026-03-15T08:06:16Z
- Observation: Iteration-8 fan-out controls were in place, but local content ingestion paths still read full file payloads without explicit size enforcement.
- Inference: Resource-exhaustion protection remained incomplete because concurrency limits did not constrain per-task payload size.
- Strategy: Reuse shared ingress boundary controls by enforcing `DOC_MAX_DOWNLOAD_BYTES` in `_build_content_parts(...)` and routing batch compare helper through the same guarded builder.
- Validation: Added size guard in `content.py`, reused guard in `content_batch.py`, and added focused regression tests for oversized file rejection in both single-file and compare helper flows.
- Confidence change: 0.93 -> 0.95 for iteration-8 resource-exhaustion completeness.

## Iteration 9 seed hypotheses (refined)
- Stabilize FastMCP wrapper/direct-call compatibility in tests (R-004) so full-module validation is trustworthy.
- Add pre-execution guard-order tests to prove size/validation checks run before expensive file reads and model calls.
