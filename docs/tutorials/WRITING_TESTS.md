# Writing Tests

The test suite verifies tool workflows, result models, provider adapters, and
local state without making real provider calls. Mock the external boundary and
exercise the internal behavior that changed. A test that replaces the behavior
under examination cannot establish that behavior.

The root package uses pytest with `asyncio_mode = "auto"`. Its test dependencies
and configuration live in [pyproject.toml](../../pyproject.toml); shared fixtures
live in [tests/conftest.py](../../tests/conftest.py). Companion packages have their
own test directories and lockfiles.

## Running Tests

Run commands from the root checkout:

```bash
# All root Python tests
uv run --locked --extra dev pytest tests/ -q

# One workflow or one test
uv run --locked --extra dev pytest tests/test_content_tools.py -v
uv run --locked --extra dev pytest tests/test_content_tools.py::TestContentAnalyze::test_text_default_schema -v

# Select by name; show captured output while diagnosing
uv run --locked --extra dev pytest tests/ -k "content_analyze" -v
uv run --locked --extra dev pytest tests/test_content_tools.py -v -s

# Python lint and installer tests
uv run --locked --extra dev ruff check src/ tests/
npm test
```

Async test functions run automatically; new tests do not need
`@pytest.mark.asyncio`. Add `PYTHONPATH=src` if the runner needs an explicit source
path, as in the project's test instructions. Use focused checks during repair,
then the required final suite. Avoid documenting a fixed test count or runtime;
both change as the repository evolves.

## Conftest Fixtures

### Autouse fixtures (run automatically)

| Fixture | Boundary it isolates |
| --- | --- |
| `_set_dummy_api_key` | Sets a non-real Gemini key |
| `_disable_tracing` | Disables tracing configuration for tests |
| `_isolate_dotenv` | Prevents loading the user's real config file |
| `_isolate_upload_cache` | Redirects upload cache files to a temporary directory |
| `_isolate_durable_jobs` | Points `VRM_JOB_DB` at a temporary SQLite database |
| `_disable_graph_extraction` | Patches graph enrichment at its source and package export |
| `_unwrap_fastmcp_tools` | Keeps imported tool entry points directly callable for tests |

The dummy key is not a network mock. Tests still need to patch every provider
operation they invoke. These fixtures also do not automatically isolate every
result cache, context cache, session, or environment setting; use the fixtures
and temporary paths required by the scenario.

### Opt-in fixtures

| Fixture | Supplied behavior |
| --- | --- |
| `mock_gemini_client` | Patches `get()`, `generate()`, `generate_structured()`, and `generate_json_validated()` |
| `clean_config` | Clears the config singleton before and after the test |
| `mock_weaviate_client` | Supplies a mock client/collection and patches singleton access and availability |
| `mock_weaviate_disabled` | Removes Weaviate settings and resets config through `clean_config` |

`mock_gemini_client` returns a dictionary with `get`, `generate`,
`generate_structured`, `generate_json_validated`, and `client` entries. Return a
concrete Pydantic model from `generate_structured`; return text from `generate`;
return a dictionary from `generate_json_validated` when testing its callers.
For direct SDK calls, configure the relevant method on `client` as an
`AsyncMock`, such as `client.aio.files.upload` or `client.aio.interactions.create`.

Patch the name the implementation resolves. Imports inside a tool often resolve
through a package export, while a module-level import may need a patch on that
module. The graph fixture patches both locations for that reason. Do not copy
its suppression into a test whose purpose is to verify graph extraction.

## Testing Tools

Use a small input that reaches the branch under test. This complete text-analysis
example avoids URL resolution and File API uploads:

```python
from video_research_mcp.models.content import ContentResult
from video_research_mcp.tools.content import content_analyze


async def test_text_analysis_returns_structured_result(
    mock_gemini_client, mock_weaviate_disabled,
):
    """GIVEN text WHEN analyzed THEN return validated content fields."""
    mock_gemini_client["generate_structured"].return_value = ContentResult(
        title="Study notes",
        summary="The sample contains ten observations.",
        key_points=["The study reports its sample size."],
    )

    result = await content_analyze(
        text="The study contains ten observations.",
        instruction="Summarize the evidence.",
    )

    assert result["title"] == "Study notes"
    call = mock_gemini_client["generate_structured"].call_args
    assert call.kwargs["schema"] is ContentResult
    assert "Summarize the evidence." in call.args[0].parts[-1].text


async def test_missing_source_stops_before_generation(
    mock_gemini_client, mock_weaviate_disabled,
):
    result = await content_analyze()

    assert "Provide exactly one" in result["error"]
    mock_gemini_client["generate"].assert_not_called()
    mock_gemini_client["generate_structured"].assert_not_called()


async def test_quota_failure_returns_recovery_fields(
    mock_gemini_client, mock_weaviate_disabled,
):
    mock_gemini_client["generate_structured"].side_effect = RuntimeError("429 quota")

    result = await content_analyze(text="Study notes")

    assert result["category"] == "API_QUOTA_EXCEEDED"
    assert result["retryable"] is True
    assert result["retry_after_seconds"] == 60
```

Choose additional cases from the actual contract:

| Changed behavior | Useful assertion |
| --- | --- |
| Custom schema | Schema reaches the provider adapter; malformed output takes the documented failure path |
| Source selection | Both/neither sources stop before generation |
| Policy checks | Rejected URL/path makes no downstream provider call |
| Fallback | Each step retains the system instruction and consumes the previous step's actual output |
| Batch processing | Input order, success/failure counts, and failed items are retained |
| Storage | Provenance and UUID arguments are correct; storage failure preserves the primary result |
| Registration | Root discovery exposes the intended name, schema, and annotations |

Direct Python calls bypass FastMCP's parameter-schema validation. A missing
required argument raises `TypeError` before the function body, and a `Field`
constraint does not validate an ordinary coroutine call. Test explicit tool
invariants directly; test MCP parameter validation through the registered tool
when that is the behavior being changed.

### Provider adapters and validation

When testing `GeminiClient.generate()`, mock the SDK method it calls and inspect
the constructed config. When testing `generate_structured()` or
`generate_json_validated()`, mock `generate()` and let local parsing and validation
run. Using `mock_gemini_client["generate_json_validated"]` would bypass the
validator itself.

See [test_client.py](../../tests/test_client.py) for SDK response handling,
[test_client_validated.py](../../tests/test_client_validated.py) for strict and
lenient JSON behavior, and [test_config.py](../../tests/test_config.py) for model
compatibility. Provider-retry tests should patch waits so failure cases do not
sleep in real time.

## Testing Models

Model tests check a meaningful constraint, default, or roundtrip. They usually
need no service fixtures:

```python
from video_research_mcp.models.content import ContentResult


def test_content_result_roundtrip():
    original = ContentResult(title="Report", key_points=["Reported finding"])

    restored = ContentResult.model_validate(original.model_dump(mode="json"))

    assert restored.title == "Report"
    assert restored.key_points == ["Reported finding"]
    assert restored.entities == []
```

Use invalid inputs to test validation rules that matter to the caller. Schema
conformance and semantic checks are separate: strict video tests also verify
quality-gate behavior and actual artifact files.

## Testing Helpers

Pure transformations can run directly. Filesystem helpers should use `tmp_path`
and assert the relevant file content or state. For a file-analysis workflow,
write a text file under `tmp_path`, mock generation, and inspect the parts or
provenance passed to the adapter/store.

Config tests need `clean_config` so environment changes take effect:

```python
from video_research_mcp.config import get_config


def test_model_override(clean_config, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "medium")

    assert get_config().default_model == "test-model"
```

For URL policy tests, patch DNS and HTTP transport boundaries. Calling a public
HTTPS URL can perform real DNS resolution even when Gemini generation is mocked.
See [test_url_policy.py](../../tests/test_url_policy.py) for redirects, peer IPs,
and size limits; do not bypass the policy helper in a test intended to prove it.

For context caches, reset `_registry`, `_pending`, `_suppressed`, `_last_failure`,
and `_loaded` as appropriate, redirect `_registry_path` to `tmp_path`, and mock
cache API operations. Cancel or await background tasks created by the test.
[test_context_cache.py](../../tests/test_context_cache.py) and
[test_cache_bridge.py](../../tests/test_cache_bridge.py) demonstrate isolated state.
Use a temporary `SessionStore`/database for session and persistence tests rather
than the user's session database.

## Testing Knowledge Tools

To test disabled storage, request `mock_weaviate_disabled` and assert the tool's
documented response: search, related-object, and stats tools return empty models;
fetch, ingest, and QueryAgent tools return configuration errors. To test a query,
request `mock_weaviate_client`, enable storage in isolated config, and disable
unrelated enrichment:

```python
from video_research_mcp.tools.knowledge import knowledge_search


async def test_search_dispatches_to_selected_collection(
    mock_weaviate_client, clean_config, monkeypatch,
):
    monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    monkeypatch.setenv("FLASH_SUMMARIZE", "false")

    result = await knowledge_search(query="sample size", collections=["VideoAnalyses"])

    mock_weaviate_client["client"].collections.get.assert_called_once_with("VideoAnalyses")
    mock_weaviate_client["collection"].query.hybrid.assert_called_once()
    assert result["total_results"] == 0
```

Configure `near_text` or `bm25` mocks when testing those modes; the shared fixture
preconfigures common operations, not every possible query. Use concrete result
properties and metadata when verifying rerank ordering, score conversion, filter
handling, or Flash summaries. QueryAgent tests must mock the agent and use the
async-client boundary where the implementation does.

## File Naming Convention

| File group | Coverage |
| --- | --- |
| `test_<domain>_tools.py` | Public tool workflows |
| `test_models.py`, `test_*_models.py` | Model contracts |
| `test_client*.py`, `test_config.py` | Provider/config adapters |
| `test_cache*.py`, `test_sessions.py`, `test_persistence.py` | Local and provider state ownership |
| `test_video_contract*.py`, `test_validation.py` | Strict output, quality checks, and artifacts |
| `test_weaviate_*.py`, `test_knowledge_*.py` | Knowledge storage, schemas, and retrieval |
| `test_url_policy.py`, `test_video_url.py` | URL and source boundaries |
| `installer.test.js`, installer export tests | Plugin installation behavior and tracked state matrix |

For a new tool, follow [Adding a Tool](ADDING_A_TOOL.md). Before delivery, run the
focused checks and required gates for the affected package. Passing mocked tests
establishes the local contract; authenticated provider behavior needs a separate,
explicitly authorized live validation.
