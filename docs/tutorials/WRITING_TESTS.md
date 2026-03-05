# Writing Tests

How to write, organize, and run tests for the video-research-mcp server.

## Test Philosophy

All tests are **unit-level with mocked Gemini and Weaviate**. No test should ever hit a real API. The test suite validates:

1. **Tool functions** -- correct input handling, structured output, error paths
2. **Pydantic models** -- defaults, roundtrip serialization, validation
3. **Helper functions** -- URL parsing, content building, cache operations

Currently 540 tests across 20+ test files, all running in under 10 seconds.

## Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run a single file
uv run pytest tests/test_video_tools.py -v

# Run a single test
uv run pytest tests/test_video_tools.py::TestVideoAnalyze::test_video_analyze_default_schema -v

# Run tests matching a keyword
uv run pytest tests/ -k "video_analyze" -v

# Run with output (useful for debugging)
uv run pytest tests/ -v -s
```

### asyncio_mode=auto

The project uses `asyncio_mode = "auto"` in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

This means async test functions run automatically without needing `@pytest.mark.asyncio` on every test. However, it is still common practice in this codebase to include the marker explicitly for clarity.

## Conftest Fixtures

All shared fixtures live in `tests/conftest.py`. Four autouse fixtures run for every test, plus several opt-in fixtures for specific scenarios.

### Autouse fixtures (run automatically)

### `_set_dummy_api_key` (autouse)

```python
@pytest.fixture(autouse=True)
def _set_dummy_api_key(monkeypatch):
    """Ensure tests never hit real Gemini API."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
```

Sets a fake API key so the config singleton initializes without errors.

### `_disable_tracing` (autouse)

```python
@pytest.fixture(autouse=True)
def _disable_tracing(monkeypatch):
    """Disable MLflow tracing in all tests to avoid real tracking-server calls."""
    monkeypatch.setenv("GEMINI_TRACING_ENABLED", "false")
```

Prevents tests from contacting a real MLflow tracking server. The `test_tracing.py` module patches the tracing module directly and does not rely on this fixture.

### `_isolate_dotenv` (autouse)

```python
@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch):
    """Prevent tests from loading the user's real ~/.config/video-research-mcp/.env."""
    monkeypatch.setattr(
        "video_research_mcp.dotenv.DEFAULT_ENV_PATH",
        tmp_path / "nonexistent.env",
    )
```

Redirects dotenv loading to a nonexistent temp path so the user's real `.env` file never leaks into tests.

### `_isolate_upload_cache` (autouse)

```python
@pytest.fixture(autouse=True)
def _isolate_upload_cache(tmp_path, monkeypatch):
    """Point upload cache to a temp directory so tests never share filesystem state."""
    cache_dir = tmp_path / "upload_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(
        "video_research_mcp.tools.video_file._upload_cache_dir",
        lambda: cache_dir,
    )
```

Ensures the File API upload cache uses an isolated temp directory per test.

### Opt-in fixtures

### `mock_gemini_client`

```python
@pytest.fixture()
def mock_gemini_client():
    """Patch GeminiClient.get(), .generate(), and .generate_structured()."""
    with (
        patch("video_research_mcp.client.GeminiClient.get") as mock_get,
        patch("video_research_mcp.client.GeminiClient.generate", new_callable=AsyncMock) as mock_gen,
        patch("video_research_mcp.client.GeminiClient.generate_structured", new_callable=AsyncMock) as mock_structured,
    ):
        client = MagicMock()
        mock_get.return_value = client
        yield {
            "get": mock_get,
            "generate": mock_gen,
            "generate_structured": mock_structured,
            "client": client,
        }
```

Returns a dict with four keys. Usage:

```python
# Mock structured output (returns a Pydantic model instance)
mock_gemini_client["generate_structured"].return_value = VideoResult(title="Test")

# Mock raw text output
mock_gemini_client["generate"].return_value = '{"key": "value"}'

# Mock failure
mock_gemini_client["generate"].side_effect = RuntimeError("API error")

# Access the underlying client mock (for file upload mocking etc.)
mock_gemini_client["client"].aio.files.upload = AsyncMock(return_value=uploaded)
```

### `clean_config`

```python
@pytest.fixture()
def clean_config():
    """Reset the config singleton between tests."""
    import video_research_mcp.config as cfg_mod
    cfg_mod._config = None
    yield
    cfg_mod._config = None
```

Use when testing config behavior or when a test modifies env vars that affect the config singleton.

### `mock_weaviate_client`

```python
@pytest.fixture()
def mock_weaviate_client():
    """Patch WeaviateClient for unit tests."""
    # ... provides mock client + collection
    yield {"client": mock_client, "collection": mock_collection}
```

For testing knowledge tools. Patches the Weaviate singleton and provides pre-configured mocks for common operations (insert, query, aggregate).

### `mock_weaviate_disabled`

```python
@pytest.fixture()
def mock_weaviate_disabled(monkeypatch, clean_config):
    """Ensure Weaviate is disabled — empty WEAVIATE_URL."""
    monkeypatch.delenv("WEAVIATE_URL", raising=False)
    monkeypatch.delenv("WEAVIATE_API_KEY", raising=False)
```

For testing graceful degradation when Weaviate is not configured. Depends on `clean_config` to reset the singleton so the removed env vars take effect.

## Testing Tools

Tool tests follow a consistent pattern:

### Basic structure

```python
# tests/test_my_tools.py
"""Tests for my domain tools."""

from __future__ import annotations

import pytest

from video_research_mcp.models.my_domain import MyResult
from video_research_mcp.tools.my_domain import my_tool


class TestMyTool:
    @pytest.mark.asyncio
    async def test_success_case(self, mock_gemini_client):
        """GIVEN valid input WHEN my_tool called THEN returns structured result."""
        mock_gemini_client["generate_structured"].return_value = MyResult(
            field="value",
        )

        result = await my_tool(input_text="test")

        assert result["field"] == "value"
        mock_gemini_client["generate_structured"].assert_called_once()

    @pytest.mark.asyncio
    async def test_error_case(self, mock_gemini_client):
        """GIVEN API failure WHEN my_tool called THEN returns error dict."""
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("fail")

        result = await my_tool(input_text="test")

        assert "error" in result
        assert "category" in result
        assert "hint" in result

    @pytest.mark.asyncio
    async def test_validation_error(self):
        """GIVEN invalid input WHEN my_tool called THEN returns error without calling Gemini."""
        result = await my_tool()  # missing required param
        assert "error" in result
```

### What to test for each tool

| Scenario | What to assert |
|----------|---------------|
| Happy path (default schema) | Result matches model fields, `generate_structured` called |
| Happy path (custom schema) | Result matches custom schema, `generate` called |
| Invalid input | Returns error dict, Gemini NOT called |
| Gemini failure | Returns error dict with category and hint |
| Edge cases | Empty inputs, boundary values, both/neither sources |

### Real example from the codebase

From `tests/test_video_tools.py`:

```python
class TestVideoAnalyze:
    @pytest.mark.asyncio
    async def test_video_analyze_default_schema(self, mock_gemini_client):
        """video_analyze with no custom schema uses VideoResult via generate_structured."""
        mock_gemini_client["generate_structured"].return_value = VideoResult(
            title="Test Video",
            summary="A test summary",
            key_points=["point 1"],
            topics=["AI"],
        )

        result = await video_analyze(
            url="https://www.youtube.com/watch?v=abc123",
            use_cache=False,
        )

        assert result["title"] == "Test Video"
        assert result["summary"] == "A test summary"
        assert result["source"] == "https://www.youtube.com/watch?v=abc123"
        mock_gemini_client["generate_structured"].assert_called_once()

    @pytest.mark.asyncio
    async def test_video_analyze_custom_schema(self, mock_gemini_client):
        """video_analyze with custom output_schema uses generate() + json.loads."""
        mock_gemini_client["generate"].return_value = '{"recipes": ["pasta", "salad"]}'

        custom_schema = {"type": "object", "properties": {"recipes": {"type": "array"}}}
        result = await video_analyze(
            url="https://www.youtube.com/watch?v=abc123",
            instruction="List all recipes",
            output_schema=custom_schema,
            use_cache=False,
        )

        assert result["recipes"] == ["pasta", "salad"]
        mock_gemini_client["generate"].assert_called_once()
```

## Testing Models

Model tests validate defaults, field types, and roundtrip serialization. They need no fixtures.

```python
# tests/test_models.py

class TestVideoModels:
    def test_video_result_defaults(self):
        r = VideoResult()
        assert r.title == ""
        assert r.key_points == []
        assert r.timestamps == []

    def test_video_result_roundtrip(self):
        r = VideoResult(
            title="Test",
            summary="Summary",
            key_points=["p1"],
            timestamps=[Timestamp(time="0:30", description="intro")],
        )
        d = r.model_dump()
        assert d["title"] == "Test"
        r2 = VideoResult.model_validate(d)
        assert r2.timestamps[0].description == "intro"
```

## Testing Helpers

Pure function tests for URL parsing, content building, etc. No async, no mocking needed.

```python
# tests/test_video_tools.py

class TestUrlHelpers:
    def test_normalize_standard_url(self):
        url = "https://www.youtube.com/watch?v=abc123"
        assert _normalize_youtube_url(url) == "https://www.youtube.com/watch?v=abc123"

    def test_invalid_url(self):
        with pytest.raises(ValueError, match="Could not extract"):
            _normalize_youtube_url("https://example.com/page")

    def test_reject_spoofed_youtube_domains(self):
        with pytest.raises(ValueError):
            _extract_video_id("https://youtube.com.evil.test/watch?v=abc123")
```

## Testing Knowledge Tools

Knowledge tool tests need `mock_weaviate_client` and typically also `clean_config` + `monkeypatch` to set `WEAVIATE_URL`:

```python
class TestKnowledgeSearch:
    async def test_returns_empty_when_disabled(self, mock_weaviate_disabled):
        """knowledge_search returns empty result when Weaviate not configured."""
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="AI research")
        assert result["total_results"] == 0

    async def test_searches_all_collections(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search queries all 12 collections when none specified."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(query="test")
        assert mock_weaviate_client["client"].collections.get.call_count == 12
```

Note the lazy import pattern (`from ... import knowledge_search` inside the test function). This ensures the import happens after fixtures have patched the modules.

## File Naming Convention

| File | What it tests |
|------|---------------|
| `test_<domain>_tools.py` | Tool functions for a domain (e.g., `test_video_tools.py`) |
| `test_models.py` | All Pydantic models |
| `test_<module>.py` | Non-tool modules (e.g., `test_cache.py`, `test_retry.py`, `test_sessions.py`, `test_persistence.py`) |
| `test_video_file.py` | Local video file helpers (MIME detection, hashing, File API upload) |
| `test_video_core.py` | Shared video analysis pipeline (cache check, Gemini call, cache save) |
| `test_weaviate_*.py` | Weaviate client, schema, and store modules |
| `test_knowledge_tools.py` | Knowledge query tools |

## Linting

Run ruff before committing:

```bash
uv run ruff check src/ tests/
```

Configuration (in `pyproject.toml`):

```toml
[tool.ruff]
target-version = "py311"
line-length = 100
```

## Common Patterns

### Testing with tmp_path

For tools that work with local files, use pytest's `tmp_path` fixture:

```python
@pytest.mark.asyncio
async def test_local_file(self, tmp_path, mock_gemini_client):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\x00" * 100)

    mock_gemini_client["generate_structured"].return_value = VideoResult(title="Local")

    result = await video_analyze(file_path=str(f), use_cache=False)
    assert result["title"] == "Local"
```

### Testing config behavior

```python
async def test_custom_config(self, clean_config, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    from video_research_mcp.config import get_config
    cfg = get_config()
    assert cfg.default_model == "gemini-custom"
```

### Asserting Gemini was called with specific args

```python
mock_gemini_client["generate_structured"].assert_called_once()
call_args = mock_gemini_client["generate_structured"].call_args
assert call_args.kwargs["schema"] == MyResult
```

## Reference

- [Adding a New Tool](./ADDING_A_TOOL.md) -- tool conventions and checklist
- [Knowledge Store](./KNOWLEDGE_STORE.md) -- Weaviate integration details
- Source: `tests/conftest.py` -- all shared fixtures
- Source: `tests/test_video_tools.py` -- comprehensive tool test example
- Source: `tests/test_knowledge_tools.py` -- knowledge tool test patterns
