# Risk Register

## R-001
- Severity: High
- Area: Trust boundary / outbound fetch
- Evidence: Prior to iteration-1 patch, `content_analyze` accepted URL input and entered `_analyze_url` without `validate_url` guard.
- Current status: Mitigated in iteration 1 by adding URL policy validation at ingress.
- Residual risk: DNS-policy parity depends on continuous reuse of `validate_url()` by future URL-taking tools.

## R-002
- Severity: Medium
- Area: Operational integrity / authorization
- Evidence: Prior to iteration 4, `infra_cache(action="clear")` and mutating `infra_configure(...)` executed without explicit capability gating.
- Exploit reasoning: Any connected MCP client can modify global runtime behavior or erase cache state, creating integrity and availability impact.
- Status: Mitigated in iteration 4 via `INFRA_MUTATIONS_ENABLED` policy gate + optional `INFRA_ADMIN_TOKEN` enforcement.
- Residual risk: Deployments that intentionally set `INFRA_MUTATIONS_ENABLED=true` without a token still permit all connected clients to mutate config/cache.

## R-003
- Severity: Medium
- Area: Local filesystem trust boundary
- Evidence: Local path ingress previously resolved unrestricted host paths in video/content/document tools.
- Exploit reasoning: In shared or semi-trusted host setups, broad path access can expose sensitive local documents to LLM processing.
- Status: Mitigated in iteration 2 with `LOCAL_FILE_ACCESS_ROOT` policy gate; residual risk is misconfiguration when root is unset.

## R-004
- Severity: Medium
- Area: Validation/test contract reliability
- Evidence: Decorated tool direct calls fail as `FunctionTool` in subset test runs (`tests/test_content_tools.py`, `tests/test_content_batch_tools.py`).
- Exploit reasoning: Test harness contract drift can hide regressions and delay detection of real validation failures.
- Status: Open (schedule deep fix during iteration 9 regression blind-spot pass).

## R-005
- Severity: Medium
- Area: External API idempotency / quota integrity
- Evidence: Prior upload flow in `src/video_research_mcp/tools/video_file.py` had no same-hash lock around cache-check + upload critical section.
- Exploit reasoning: Concurrent retries could duplicate external uploads for the same content and amplify quota burn.
- Status: Mitigated in iteration 3 with per-content-hash upload lock and regression test.

## R-006
- Severity: Low
- Area: Partial-failure transparency / evidence integrity
- Evidence: Prior to iteration 6, `src/video_research_mcp/tools/research_document_file.py` logged per-source preparation failures but did not expose skipped sources in result payloads.
- Exploit reasoning: Consumers could assume full-source coverage when synthesis used only a subset.
- Status: Mitigated in iteration 6 by adding structured `preparation_issues` propagation from preparation helpers into final report schema.
- Residual risk: Preparation issues are exposed only when at least one source is prepared; all-source failure still returns a top-level tool error.

## R-007
- Severity: High
- Area: Secret handling / control-plane disclosure
- Evidence: Prior to iteration 4, `infra_configure` returned `current_config` with non-Gemini credential fields still present (`youtube_api_key`, `weaviate_api_key`).
- Exploit reasoning: Any MCP client invoking infra config introspection could retrieve service credentials and pivot into external systems.
- Status: Mitigated in iteration 4 by redacting all secret-bearing config fields from infra responses.

## R-008
- Severity: High
- Area: Cache persistence integrity
- Evidence: Prior to iteration 5, `src/video_research_mcp/cache.py` wrote cache payloads directly to final files (`write_text` on target path).
- Exploit reasoning: Interrupted writes can persist truncated JSON and invalidate previously correct cache entries, causing availability and consistency degradation.
- Status: Mitigated in iteration 5 with unique temp-file staging + atomic `replace`.

## R-009
- Severity: Medium
- Area: Registry hydration integrity
- Evidence: Prior to iteration 5, `src/video_research_mcp/context_cache.py::_load_registry` loaded nested JSON without strict shape validation.
- Exploit reasoning: Malformed persisted data could introduce invalid in-memory mappings and reduce reliability of context cache diagnostics/reuse.
- Status: Mitigated in iteration 5 with strict `{str: {str: str}}` filtering during load.

## R-010
- Severity: Medium
- Area: Prompt-injection/tool-misuse resistance
- Evidence: Iterations 1-6 focused on trust boundaries, validation, idempotency, auth, cache integrity, and fault isolation; no dedicated adversarial prompt-injection review artifacts yet.
- Exploit reasoning: Untrusted content merged into model prompts may induce policy bypass attempts without explicit adversarial coverage tests.
- Status: Mitigated in iterations 7-8 with untrusted-data prompt delimiters + adversarial test coverage in both `tools/knowledge/summarize.py` and `tools/content.py::_reshape_to_schema`.
- Residual risk: Future prompt-building paths may regress unless anti-injection prompt contracts are reused systematically.

## R-011
- Severity: Medium
- Area: Prompt-injection/tool-misuse resistance
- Evidence: `src/video_research_mcp/tools/content.py:208` and `src/video_research_mcp/tools/content.py:216` pass raw `unstructured` model output directly into second-pass schema reshaping prompts.
- Exploit reasoning: Adversarial instructions embedded in fetched/parsed content can influence second-pass behavior and reduce schema/summary reliability.
- Status: Mitigated in iteration 8 by untrusted-data delimiters and explicit anti-injection prompt constraints in `_reshape_to_schema(...)`.

## R-012
- Severity: Medium
- Area: Concurrency/resource exhaustion
- Evidence: Prior `research_document_file._prepare_all_documents_with_issues(...)` executed unbounded `asyncio.gather` fan-out for URL downloads and uploads.
- Exploit reasoning: Large source lists could trigger excessive parallel network/file operations and degrade service availability.
- Status: Mitigated in iteration 8 by bounded concurrency (`_DOC_PREPARE_CONCURRENCY=4`) across download/upload phases with regression coverage.

## R-013
- Severity: Medium
- Area: Concurrency/resource exhaustion
- Evidence: Prior to this continuation run, `src/video_research_mcp/tools/research_document.py` used unbounded `asyncio.gather` in `_phase_document_map` and `_phase_evidence_extraction`.
- Exploit reasoning: Large document batches can amplify simultaneous upstream model calls, increasing quota pressure and degrading service responsiveness.
- Status: Mitigated in iteration 8 continuation via bounded phase execution and config-driven cap controls (`DOC_PHASE_CONCURRENCY`, `DOC_PREPARE_CONCURRENCY`) added in 2026-03-15 continuation run.
- Residual risk: Misconfigured caps (too high/too low) can still degrade availability; bounded by validation range `1..16`.

## R-014
- Severity: Low
- Area: Operational tuning / availability
- Evidence: Concurrency controls are now configurable per deployment and validated for range, but operator-selected values still influence latency/throughput tradeoffs.
- Exploit reasoning: Non-malicious misconfiguration (for example maxing both caps in low-resource environments) can increase queueing or contention under load.
- Status: Accepted with guardrails (range validation + secure defaults); monitor via operational telemetry.

## R-015
- Severity: Medium
- Area: Resource exhaustion / local payload size
- Evidence: Prior to this run, `content` ingestion paths (`content.py` file source and `content_batch.py` compare helper) read local files fully into memory without explicit size cap.
- Exploit reasoning: Oversized local files can amplify memory pressure and degrade availability, even when concurrency is bounded.
- Status: Mitigated in iteration 8 continuation by enforcing `DOC_MAX_DOWNLOAD_BYTES` pre-read checks and reusing guarded builder in batch compare path.
- Residual risk: Limit currently reuses document-download cap; future tuning may require a dedicated content-ingestion limit.

## R-016
- Severity: Medium
- Area: Resource exhaustion / aggregate compare payload
- Evidence: Prior to this run, `content_batch` compare mode could assemble a large combined payload across many files without an aggregate-size guard.
- Exploit reasoning: Attackers can submit multiple near-limit files so aggregate in-memory payload becomes disproportionate even when single-file caps pass.
- Status: Mitigated in this continuation by enforcing `CONTENT_COMPARE_MAX_TOTAL_BYTES` before compare assembly.
- Residual risk: Operator misconfiguration of aggregate cap can still increase memory pressure; bounded by positive-int validation and secure default.

## R-017
- Severity: Medium
- Area: Prompt-injection/tool-misuse resistance
- Evidence: Prior to this run, `_analyze_parts(...)` passed free-form instruction alongside untrusted file/text content without explicit anti-injection guardrail text.
- Exploit reasoning: Embedded adversarial instructions in content may reduce model adherence to requested task boundaries.
- Status: Mitigated in this continuation by adding security guardrail instructions and `<TASK_INSTRUCTION>` boundary in prompt suffix.
- Residual risk: Similar boundary contracts must be reused in future prompt-construction paths to avoid regression.
