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
- Evidence: Decorated tool direct calls fail as `FunctionTool` in subset test runs (`tests/test_content_batch_tools.py`).
- Exploit reasoning: Test harness contract drift can hide regressions and delay detection of real validation failures.
- Status: Mitigated in iteration 9 by applying `unwrap_tool` in `tests/test_content_batch_tools.py` and validating targeted module pass.
- Residual risk: New tool test modules can regress if unwrapping pattern is not consistently applied.

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
- Evidence: Iteration 7 added explicit anti-injection system guardrails in `src/video_research_mcp/prompts/content.py` and wired them through `src/video_research_mcp/tools/content.py` model-call paths, plus hardening in research system prompts.
- Exploit reasoning: Untrusted content merged into model prompts may induce policy bypass attempts without explicit adversarial coverage tests.
- Status: Mitigated in iteration 7 via explicit system-level anti-injection rules and regression assertions on guardrail propagation.
- Residual risk: Guardrails are prompt-based; dedicated adversarial corpus testing across all tools is still pending.

## R-011
- Severity: High
- Area: Concurrency and resource exhaustion
- Evidence: Prior to iteration 8, `research_document` accepted unbounded source lists and used unbounded `asyncio.gather` fan-out in preparation and phase execution; temporary download directories were not explicitly cleaned.
- Exploit reasoning: Large attacker-controlled source sets can drive bursty parallel downloads/uploads/model calls and persistent temp-directory growth, degrading service availability and host stability.
- Status: Mitigated in iteration 8 via `RESEARCH_DOCUMENT_MAX_SOURCES`, bounded phase concurrency controls, and guaranteed tmp-dir cleanup.
- Residual risk: Workload limits are currently concentrated in `research_document`; equivalent envelope checks should be reviewed for other future multi-source tools.

## R-012
- Severity: High
- Area: Trust boundary / redirect SSRF control
- Evidence: Prior to iteration 9, `src/video_research_mcp/url_policy.py::download_checked` used `follow_redirects=True` and validated redirected target only after follow.
- Exploit reasoning: Safe-looking external URL could redirect to a blocked internal target and trigger a network request before policy rejection.
- Status: Mitigated in iteration 9 by switching to manual redirect handling with per-hop `validate_url()` before every follow-up request.
- Residual risk: Equivalent redirect handling guarantees must be preserved for any future download helpers added outside `url_policy.py`.

## R-013
- Severity: Medium
- Area: Regression assurance / control drift
- Evidence: Before iteration 10, high-impact security checks required multiple ad hoc targeted commands with no consolidated runner.
- Exploit reasoning: Operational friction increases the probability that key controls are not re-validated each run, allowing silent regression drift.
- Status: Partially mitigated in iteration 10 via `scripts/run_security_smoke.sh`.
- Residual risk: Smoke suite is currently manual; CI enforcement is still pending.
