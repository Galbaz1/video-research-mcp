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

## FP-010: Delimit untrusted retrieval content in summarization prompts
- Context: LLM post-processing over untrusted search hits and user query text.
- Rule: Wrap query/hit payloads in explicit untrusted-data markers and instruct model to ignore embedded instructions in those payloads.
- Why: Reduces prompt-injection/tool-misuse risk from instruction smuggling in retrieved content.
- Applied in iteration 7:
- `src/video_research_mcp/tools/knowledge/summarize.py`
- Regression coverage:
- `tests/test_knowledge_summarize.py::TestSummarizeHits::test_prompt_hardens_untrusted_query_and_properties`

## FP-011: Delimit untrusted content in second-pass schema reshaping
- Context: Multi-pass URL analysis where first-pass unstructured model output is fed into a second-pass structured extraction prompt.
- Rule: Wrap instruction/content in explicit untrusted-data markers and include hard anti-injection + schema-only response rules.
- Why: Prevents instruction-smuggling payloads in fetched content from steering reshape behavior.
- Applied in iteration 8:
  - `src/video_research_mcp/tools/content.py`
- Regression coverage:
  - `tests/test_content_tools.py::TestContentAnalyze::test_url_fallback_hardens_untrusted_reshape_prompt`

## FP-012: Bound parallel document preparation fan-out
- Context: `research_document` pre-processing pipeline downloading/uploading many sources in parallel.
- Rule: Use bounded concurrency for both download and upload stages in `_prepare_all_documents_with_issues(...)`.
- Why: Reduces socket/memory pressure and availability degradation under large source lists.
- Applied in iteration 8:
  - `src/video_research_mcp/tools/research_document_file.py`
- Regression coverage:
  - `tests/test_research_document_file.py::TestPrepareAllDocumentsWithIssues::test_downloads_use_bounded_concurrency`

## FP-013: Bound per-phase Gemini fan-out in document research pipeline
- Context: `research_document` executes per-document model calls in mapping and evidence phases.
- Rule: Route high-fanout phase execution through bounded concurrency helper with a fixed semaphore cap.
- Why: Prevents quota spikes and runtime instability for large multi-document requests.
- Applied in iteration 8 continuation:
  - `src/video_research_mcp/tools/research_document.py`
- Regression coverage:
  - `tests/test_research_document_tools.py::TestResearchDocument::test_phase_document_map_uses_bounded_concurrency`
  - `tests/test_research_document_tools.py::TestResearchDocument::test_phase_evidence_extraction_uses_bounded_concurrency`

## FP-014: Validate and externalize document fan-out caps
- Context: Document preparation and phase execution were bounded but static (`4`) across deployments.
- Rule: Source concurrency caps from validated runtime config (`DOC_PREPARE_CONCURRENCY`, `DOC_PHASE_CONCURRENCY`) with strict numeric bounds.
- Why: Maintains secure-by-default throttling while allowing safe tuning to environment-specific quota and resource ceilings.
- Applied in iteration 8 continuation:
  - `src/video_research_mcp/config.py`
  - `src/video_research_mcp/tools/research_document.py`
  - `src/video_research_mcp/tools/research_document_file.py`
- Regression coverage:
  - `tests/test_config.py::TestDocumentConcurrencyConfig::test_doc_concurrency_env_overrides_are_applied`
  - `tests/test_config.py::TestDocumentConcurrencyConfig::test_doc_concurrency_rejects_out_of_range_values`
  - `tests/test_research_document_tools.py::TestResearchDocument::test_phase_document_map_uses_bounded_concurrency`
  - `tests/test_research_document_tools.py::TestResearchDocument::test_phase_evidence_extraction_uses_bounded_concurrency`
  - `tests/test_research_document_file.py::TestPrepareAllDocumentsWithIssues::test_downloads_use_bounded_concurrency`

## FP-015: Enforce local content payload size limits
- Context: Local file ingestion for `content_analyze` and compare-mode batch content analysis.
- Rule: Reject files larger than configured `DOC_MAX_DOWNLOAD_BYTES` before reading bytes into memory.
- Why: Constrains memory-pressure abuse from oversized local payloads and keeps ingestion controls aligned across single/batch flows.
- Applied in iteration 8 continuation:
  - `src/video_research_mcp/tools/content.py`
  - `src/video_research_mcp/tools/content_batch.py`
- Regression coverage:
  - `tests/test_content_tools.py::TestBuildContentParts::test_file_rejects_oversized_input`
  - `tests/test_content_batch_tools.py::TestContentBatchAnalyze::test_build_file_parts_rejects_oversized_file`

## FP-016: Cap aggregate compare-mode content payload
- Context: `content_batch_analyze` compare mode combines many files into one model call.
- Rule: Enforce a pre-assembly aggregate byte ceiling (`CONTENT_COMPARE_MAX_TOTAL_BYTES`) before building combined prompt/file parts.
- Why: Prevents high-memory payload amplification from large multi-file compare requests.
- Applied in iteration 8 continuation:
  - `src/video_research_mcp/config.py`
  - `src/video_research_mcp/tools/content_batch.py`
- Regression coverage:
  - `tests/test_config.py::TestContentComparePayloadConfig::test_content_compare_max_total_bytes_env_override`
  - `tests/test_config.py::TestContentComparePayloadConfig::test_content_compare_max_total_bytes_rejects_non_positive`
  - `tests/test_content_batch_tools.py::TestContentBatchAnalyze::test_compare_helper_rejects_oversized_aggregate_payload`

## FP-017: Harden file/text analysis prompt boundaries
- Context: Direct file/text analysis path (`_analyze_parts`) appended user instruction without explicit untrusted-content boundary contract.
- Rule: Inject explicit anti-injection guardrails and tagged task-instruction boundary in analysis prompt suffix.
- Why: Reduces instruction-smuggling risk from untrusted file/text content and reuses iteration-7 boundary lessons.
- Applied in iteration 8 continuation:
  - `src/video_research_mcp/tools/content.py`
- Regression coverage:
  - `tests/test_content_tools.py::TestContentAnalyze::test_parts_path_hardens_untrusted_content_prompt`
