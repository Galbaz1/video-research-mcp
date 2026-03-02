# Security Fix Playbook

## FP-001: Enforce URL Policy at Tool Ingress
- Context: Any tool accepting user URLs and triggering outbound fetch behavior.
- Rule: Validate URL with `validate_url()` before model/tool fetch.
- Why: Prevents non-HTTPS, credentialed URLs, and private-network SSRF targets from crossing trust boundary.
- Applied in iteration 1:
  - [`src/video_research_mcp/tools/content.py`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/src/video_research_mcp/tools/content.py)
- Regression coverage:
  - [`tests/test_content_tools.py`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/tests/test_content_tools.py)

## FP-002: Capability gate for infra mutating tools
- Context: Runtime-mutating tools (`infra_cache`, `infra_configure`) can change global runtime state.
- Rule: Require explicit enablement (`INFRA_MUTATIONS_ENABLED=true`) for mutating operations and require token match when `INFRA_ADMIN_TOKEN` is configured.
- Why: Reduces unauthorized integrity/availability impact from untrusted tool-call paths.
- Applied in iteration 4:
  - `src/video_research_mcp/tools/infra.py`
  - `src/video_research_mcp/config.py`
- Regression coverage:
  - `tests/test_infra_tools.py::TestInfraTools::test_infra_configure_blocks_mutation_when_disabled`
  - `tests/test_infra_tools.py::TestInfraTools::test_infra_configure_requires_token_when_configured`
  - `tests/test_infra_tools.py::TestInfraTools::test_infra_cache_clear_requires_token_when_configured`

## FP-003: Constrain local file ingress with configurable root boundary
- Context: Tools accepting local file/directory paths in MCP environments.
- Rule: Resolve user path to absolute and enforce optional `LOCAL_FILE_ACCESS_ROOT` via shared helper before filesystem reads.
- Why: Reduces host filesystem exfiltration risk from induced tool calls in semi-trusted agent sessions.
- Applied in iteration 2:
  - `src/video_research_mcp/local_path_policy.py`
  - `src/video_research_mcp/tools/video_file.py`
  - `src/video_research_mcp/tools/content.py`
  - `src/video_research_mcp/tools/content_batch.py`
  - `src/video_research_mcp/tools/video_batch.py`
  - `src/video_research_mcp/tools/research_document_file.py`
- Regression coverage:
  - `tests/test_video_file.py`
  - `tests/test_content_tools.py`
  - `tests/test_content_batch_tools.py`

## FP-004: Coalesce concurrent file uploads by content hash
- Context: File API uploads with retrying or parallel tool calls on identical local files.
- Rule: Guard same-hash upload path with a shared async lock and re-check cache within the critical section before uploading.
- Why: Prevents duplicate upstream uploads, preserves quota, and improves idempotency under concurrent retries.
- Applied in iteration 3:
  - `src/video_research_mcp/tools/video_file.py`
- Regression coverage:
  - `tests/test_video_file.py::TestUploadCache::test_concurrent_same_hash_uploads_once`

## FP-005: Type-based network error categorization
- Context: Structured tool error output for timeout and transport failures.
- Rule: Classify typed timeout/network exceptions (`TimeoutError`, `httpx.TimeoutException`, `httpx.NetworkError`) as `NETWORK_ERROR`.
- Why: Ensures deterministic retry semantics and cleaner operational triage.
- Applied in iteration 3:
  - `src/video_research_mcp/errors.py`
- Regression coverage:
  - `tests/test_errors.py`

## FP-006: Redact secret-bearing fields in infra config responses
- Context: `infra_configure` exposes runtime config to MCP clients.
- Rule: Exclude all secret-bearing fields (`gemini_api_key`, `youtube_api_key`, `weaviate_api_key`, `infra_admin_token`) from serialized config payloads.
- Why: Prevents credential disclosure through control-plane tool responses.
- Applied in iteration 4:
  - `src/video_research_mcp/tools/infra.py`
- Regression coverage:
  - `tests/test_infra_tools.py::TestInfraTools::test_infra_configure_redacts_all_secret_fields`

## FP-007: Atomic staged writes for cache persistence
- Context: JSON cache/registry writes that can be interrupted by I/O failures.
- Rule: Write payload to a unique temp file in the same directory and atomically `replace()` the target file.
- Why: Preserves last known-good data and prevents partially written files from becoming committed state.
- Applied in iteration 5:
  - `src/video_research_mcp/cache.py`
  - `src/video_research_mcp/context_cache.py`
- Regression coverage:
  - `tests/test_cache.py::TestCache::test_save_is_atomic_when_replace_fails`

## FP-008: Validate persisted registry shape before hydration
- Context: Disk-backed context-cache registry loads into in-memory mappings at process start.
- Rule: Accept only `{str: {str: str}}` structure and ignore malformed entries.
- Why: Prevents malformed persisted state from poisoning registry integrity and diagnostics behavior.
- Applied in iteration 5:
  - `src/video_research_mcp/context_cache.py`
- Regression coverage:
  - `tests/test_context_cache.py::TestRegistryPersistence::test_load_ignores_invalid_shape_entries`

## FP-009: Surface per-source preparation failures in research outputs
- Context: Multi-source research workflows where partial source preparation failures are tolerated for availability.
- Rule: Capture per-source preparation failures (download/upload) in structured metadata and return them in final tool output.
- Why: Prevents silent evidence-coverage drift and allows clients to reason about trust/completeness before acting on synthesis.
- Applied in iteration 6:
  - `src/video_research_mcp/tools/research_document_file.py`
  - `src/video_research_mcp/tools/research_document.py`
  - `src/video_research_mcp/models/research_document.py`
- Regression coverage:
  - `tests/test_research_document_tools.py::TestResearchDocument::test_surfaces_preparation_issues`
  - `tests/test_research_document_file.py::TestPrepareAllDocumentsWithIssues::test_collects_download_failures_and_keeps_successes`

## FP-010: Enforce anti-injection system guardrails on untrusted-content analysis paths
- Context: Content-analysis tools process attacker-controlled URL/file/text inputs and include multi-step fallback reshaping.
- Rule: Apply one shared system-level anti-injection policy to every model call in the chain (primary + fallback + reshape + extraction).
- Why: Prevents policy drift where fallback flows silently lose guardrails and become easier to steer by in-content instructions.
- Applied in iteration 7:
  - `src/video_research_mcp/prompts/content.py`
  - `src/video_research_mcp/tools/content.py`
  - `src/video_research_mcp/prompts/research.py`
  - `src/video_research_mcp/prompts/research_document.py`
- Regression coverage:
  - `tests/test_content_tools.py::TestContentAnalyze::test_url_uses_url_context`
  - `tests/test_content_tools.py::TestContentAnalyze::test_url_fallback_on_structured_failure`
  - `tests/test_content_tools.py::TestContentExtract::test_extract_returns_parsed_json`

## FP-011: Enforce workload envelopes for multi-source document research
- Context: `research_document` downloads/uploads/processes user-supplied source lists across multiple async phases.
- Rule: Enforce max source count at ingress, bound fan-out concurrency for each phase, and clean temp resources in finally blocks.
- Why: Prevents resource exhaustion and event-loop/API pressure under large or adversarial source lists.
- Applied in iteration 8:
  - `src/video_research_mcp/config.py`
  - `src/video_research_mcp/tools/research_document.py`
  - `src/video_research_mcp/tools/research_document_file.py`
- Regression coverage:
  - `tests/test_research_document_tools.py::TestResearchDocument::test_rejects_too_many_sources`
  - `tests/test_research_document_file.py::TestPrepareAllDocumentsWithIssues::test_cleans_tmp_dir_after_url_preparation`

## FP-012: Validate redirect targets before issuing follow-up requests
- Context: URL download helpers that fetch user-supplied URLs and allow redirects.
- Rule: Disable automatic redirect following and validate every redirect `Location` target with URL policy checks before sending the next request.
- Why: Prevents first-hop SSRF attempts where a safe initial URL redirects into blocked/internal address space before policy enforcement.
- Applied in iteration 9:
  - `src/video_research_mcp/url_policy.py`
- Regression coverage:
  - `tests/test_url_policy.py::TestDownloadChecked::test_redirect_validates_final_url`
  - `tests/test_url_policy.py::TestDownloadChecked::test_blocks_redirect_before_following_blocked_target`

## FP-013: Normalize tool unwrapping in batch-tool direct-call tests
- Context: Tests that directly invoke decorated FastMCP tools.
- Rule: Apply `unwrap_tool()` at import boundary before awaiting tool functions.
- Why: Prevents `FunctionTool` wrapper mismatches from masking true behavioral regressions.
- Applied in iteration 9:
  - `tests/test_content_batch_tools.py`
- Regression coverage:
  - `tests/test_content_batch_tools.py` (full module passes in targeted run)

## FP-014: Consolidate high-impact controls into one smoke suite
- Context: Security regressions detected across trust-boundary, auth, idempotency, and redirect paths in iterations 1-9.
- Rule: Keep a single runnable smoke command that exercises the highest-impact mitigations on every recurring security review run.
- Why: Reduces review friction and catches policy drift early without requiring full-suite execution.
- Applied in iteration 10:
  - `scripts/run_security_smoke.sh`
- Regression coverage:
  - `tests/test_content_tools.py::TestContentAnalyze::test_url_rejects_non_https_before_model_call`
  - `tests/test_infra_tools.py::TestInfraTools::test_infra_configure_requires_token_when_configured`
  - `tests/test_video_file.py::TestUploadCache::test_concurrent_same_hash_uploads_once`
  - `tests/test_video_file.py::TestValidateVideoPath::test_rejects_path_outside_local_access_root`
  - `tests/test_research_document_tools.py::TestResearchDocument::test_surfaces_preparation_issues`
  - `tests/test_research_document_tools.py::TestResearchDocument::test_rejects_too_many_sources`
  - `tests/test_url_policy.py::TestDownloadChecked::test_blocks_redirect_before_following_blocked_target`
  - `tests/test_content_batch_tools.py::TestContentBatchAnalyze::test_compare_mode`
