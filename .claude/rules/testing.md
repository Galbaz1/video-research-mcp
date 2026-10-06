---
paths: "tests/**/*.py"
---

# Testing Patterns (this project)

## Framework

- pytest with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed
- All tests are unit-level with mocked Gemini — no test hits the real API
- `PYTHONPATH=src uv run pytest tests/ -v` to run

## Key Fixtures (conftest.py)

- `mock_gemini_client` — patches `GeminiClient.get()`, `.generate()`, `.generate_structured()`, `.generate_json_validated()`
- `clean_config` — resets config singleton between tests
- `mock_weaviate_client` — patches Weaviate client + collection
- `mock_weaviate_disabled` — ensures Weaviate is disabled (depends on `clean_config`)
- `_unwrap_fastmcp_tools` (autouse, session) — ensures tools are callable regardless of FastMCP version
- `_set_dummy_api_key` (autouse) — sets `GEMINI_API_KEY=test-key-not-real`
- `_disable_tracing` (autouse) — sets `GEMINI_TRACING_ENABLED=false`
- `_isolate_dotenv` (autouse) — prevents loading real `.env` files
- `_isolate_upload_cache` (autouse) — temp dir for upload cache
- `_isolate_durable_jobs` (autouse) — temporary `VRM_JOB_DB` SQLite database

## Patterns

- Import tool functions directly: `from video_research_mcp.tools.video import video_analyze`
- Mock external services, not internal logic
- Use `make_tool_error()` assertions: `assert "error" in result`
- Structured output mocking: `mock_gemini_client["generate_structured"].return_value = ModelInstance(...)`
- GIVEN/WHEN/THEN in docstrings for non-trivial tests

## Context Cache Tests

- Always clear `_registry`, `_pending`, `_suppressed` in fixtures
- Patch `_registry_path` to temp dir — never touch real filesystem
- Use `_passthrough_retry` mock for `with_retry` in session tests
