# AGENTS.md (tests scope)

Applies to files under `tests/`.

## Testing Patterns

- Test framework is pytest with `asyncio_mode = "auto"`; avoid unnecessary `@pytest.mark.asyncio`.
- Keep tests unit-level with mocked Gemini; no real API calls.
- Standard run command: `PYTHONPATH=src uv run pytest tests/ -v`.

## Fixture Expectations

- `mock_gemini_client`: patches `GeminiClient.get()`, `.generate()`, `.generate_structured()`, `.generate_json_validated()`.
- `clean_config`: resets config singleton between tests.
- `mock_weaviate_client`: patches Weaviate client + collection.
- `mock_weaviate_disabled`: ensures Weaviate is disabled (depends on `clean_config`).
- `_unwrap_fastmcp_tools`: ensures tools remain callable.
- `_set_dummy_api_key`: sets non-real API key for tests.
- `_disable_tracing` (autouse): sets `GEMINI_TRACING_ENABLED=false`.
- `_isolate_dotenv`: blocks loading real `.env`.
- `_isolate_upload_cache`: isolates upload cache to temp dir.
- `_isolate_durable_jobs`: isolates `VRM_JOB_DB` in a temporary SQLite database.

## Test Style

- Import tool functions directly from module paths.
- Mock external services, not internal logic under test.
- Assert structured tool errors via `make_tool_error()` shape.
- For structured-output tests, return concrete model instances from mocked `generate_structured`.
- Use GIVEN/WHEN/THEN docstrings for non-trivial tests.

## Context Cache Tests

- Clear `_registry`, `_pending`, and `_suppressed` state in fixtures.
- Patch registry path to temp directories; never touch real filesystem.
- Use passthrough retry mocks where session tests depend on retry helpers.

