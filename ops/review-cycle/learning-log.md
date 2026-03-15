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
