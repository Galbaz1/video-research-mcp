# Adding a New Tool

Add a tool to the domain that owns its behavior, give it a clear result contract,
and test its success and failure paths without contacting providers. The root
server mounts domain servers, so most additions do not need a new server.

This walkthrough uses a hypothetical `content_compare` tool. It is an extension
example, not part of the installed tool surface. The
[tool manifest](../metrics/tool-contract-manifest.json) lists registered tools;
the [architecture guide](../ARCHITECTURE.md) explains their shared services.

## Step 1: Choose a Sub-Server

| Behavior | Owner |
| --- | --- |
| Video analysis or conversation | `tools/video.py` and its helper modules |
| YouTube metadata, comments, or playlists | `tools/youtube.py` |
| Research, document analysis, or academic metadata | `tools/research.py` and its registered modules |
| Text/file/URL analysis and extraction | `tools/content.py` and `content_batch.py` |
| Grounded web search | `tools/search.py` |
| Configuration or cache operations | `tools/infra.py` |
| Knowledge retrieval, ingestion, or schemas | `tools/knowledge/` |

Keep provider work in the existing clients. Keep output models in `models/`,
shared parameter aliases in `types.py`, and substantive prompts in `prompts/`
when they warrant a separate module. A new domain server is appropriate when its
responsibilities differ from all existing domains.

## Step 2a: Add to an Existing Sub-Server

### Define the output model

Add this model to `src/video_research_mcp/models/content.py`, using that module's
existing Pydantic imports:

```python
from pydantic import BaseModel, Field


class ContentComparison(BaseModel):
    """Comparison of two supplied texts."""

    similarities: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    overall_assessment: str = ""
```

The model describes the structured output Gemini should return and validates the
response locally. Its defaults are deliberate: empty lists are acceptable when
no similarities or differences are found.

### Write the tool function

Add the following imports and function to `tools/content.py`. The existing
`content_server` handles registration; no change to `server.py` is needed for a
function defined directly in that module.

```python
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import GeminiClient
from ..errors import make_tool_error
from ..models.content import ContentComparison
from ..prompts.content import CONTENT_ANALYSIS_SYSTEM
from ..tracing import trace
from ..types import ThinkingLevel


@content_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
@trace(name="content_compare", span_type="TOOL")
async def content_compare(
    text_a: Annotated[str, Field(min_length=1, description="First text")],
    text_b: Annotated[str, Field(min_length=1, description="Second text")],
    instruction: Annotated[str, Field(description="Comparison focus")] = (
        "Compare the claims and supporting evidence in these texts."
    ),
    thinking_level: ThinkingLevel = "medium",
) -> dict:
    """Compare two supplied texts under the requested focus.

    Args:
        text_a: First text to compare.
        text_b: Second text to compare.
        instruction: What the comparison should examine.
        thinking_level: Gemini thinking depth.

    Returns:
        ContentComparison fields, or a structured tool error.
    """
    try:
        if not text_a.strip() or not text_b.strip():
            raise ValueError("Both texts must contain content")
        prompt = (
            f"{instruction}\n\n"
            f"--- Text A ---\n{text_a}\n\n"
            f"--- Text B ---\n{text_b}"
        )
        result = await GeminiClient.generate_structured(
            prompt,
            schema=ContentComparison,
            thinking_level=thinking_level,
            system_instruction=CONTENT_ANALYSIS_SYSTEM,
        )
        return result.model_dump(mode="json")
    except Exception as exc:
        return make_tool_error(exc)
```

The trace decorator sits between FastMCP registration and the function. Imports
come from `mcp.types` for annotations and the project wrapper for tracing.
Annotations describe behavior to MCP clients; they do not enforce permissions.
A generated comparison is not marked idempotent because repeated model calls can
produce different output.

The explicit whitespace check protects the workflow even when called directly
from Python. FastMCP enforces `Field` constraints on MCP calls, but those
constraints do not run just because a test calls the coroutine. Missing required
Python arguments raise `TypeError` before the function body runs.

The content system instruction keeps supplied texts in the role of source data.
A new workflow needs an instruction suited to its own inputs and must preserve it
through any fallback or reshaping call.

## Step 2b: Create a New Sub-Server

For a new domain, define `domain_server = FastMCP("domain")` in its tool module,
register functions there, then import and mount that instance in `server.py`:

```python
from .tools.my_domain import domain_server

app.mount(domain_server)
```

Each registered function still needs annotations, tracing, described parameters,
a Google-style docstring, and an error boundary. Keep the function callable for
unit tests and do not add compatibility paths for old FastMCP majors.

If you split a tool into a module that imports its domain server, registration
must happen after that server exists. Follow `_ensure_document_tool()` and
`_ensure_batch_tool()` for deferred registration; then verify root tool discovery.
Defining a decorated function in a module that the app never imports does not
expose it to MCP clients.

## Step 3: GeminiClient Integration

Use `GeminiClient.generate_structured()` for a known Pydantic result model. It
supplies the model schema to Gemini, validates the JSON response, and returns a
model instance. Use `generate()` when the result is intentionally text or when a
workflow only needs provider-constrained JSON plus parsing.

For a caller-supplied schema that needs local validation, use:

```python
result = await GeminiClient.generate_json_validated(
    "Extract names from this text: Ada wrote the report.",
    schema={
        "type": "object",
        "properties": {"names": {"type": "array", "items": {"type": "string"}}},
        "required": ["names"],
    },
    strict=True,
)
```

Dictionary schema validation requires the `strict` extra (`jsonschema`). Without
`strict=True`, this helper can return parsed but unvalidated data. Choose that
behavior explicitly; do not describe `json.loads()` as schema validation.

Use `GeminiClient.get()` for shared SDK facilities such as uploads, cache APIs,
or Interactions. Ordinary generation belongs in the shared generation methods
so config resolution and retry behavior remain consistent. Google Search and URL
Context tool wiring can be passed through `generate()` or `generate_structured()`
where the provider supports the combination. See
[client.py](../../src/video_research_mcp/client.py) for exact signatures.

## Step 4: Write-Through Knowledge Store

Decide whether the result belongs in the knowledge store. Analytical workflows
usually persist useful results, while extraction, diagnostics, and launch-only
operations may have no write-through result. The comparison example above
returns its output without defining a new storage contract.

For persisted output, choose or define a collection in `weaviate_schema/`, add a
matching helper in `weaviate_store/`, and call that helper after the primary result
is ready. Helpers must check whether storage is enabled, catch storage errors,
and preserve the primary result when storage fails. Reuse existing property,
provenance, and UUID conventions rather than inserting arbitrary model output.

A new collection also needs its entry in `ALL_COLLECTIONS`, the
`KnowledgeCollection` alias, and the knowledge helper mappings that apply to it.
See [Knowledge Store](KNOWLEDGE_STORE.md) for collection and ingestion contracts.
Graph extraction is a separate model call; include it only when its derived
concepts and relationships serve the workflow.

## Step 5: Write Tests

After adding the example model and tool, place this test in
`tests/test_content_compare.py`:

```python
from video_research_mcp.models.content import ContentComparison
from video_research_mcp.tools.content import content_compare


async def test_comparison_returns_validated_fields(mock_gemini_client):
    """GIVEN two texts WHEN compared THEN return the model's fields."""
    mock_gemini_client["generate_structured"].return_value = ContentComparison(
        similarities=["Both texts report the same sample size."],
        differences=["Only the second text reports uncertainty."],
        overall_assessment="The second text provides more evidence.",
    )

    result = await content_compare(text_a="First report", text_b="Second report")

    assert result["overall_assessment"] == "The second text provides more evidence."
    call = mock_gemini_client["generate_structured"].call_args
    assert call.kwargs["schema"] is ContentComparison


async def test_blank_text_stops_before_generation(mock_gemini_client):
    result = await content_compare(text_a=" ", text_b="Second report")

    assert result["error"] == "Both texts must contain content"
    mock_gemini_client["generate_structured"].assert_not_called()


async def test_provider_failure_returns_tool_error(mock_gemini_client):
    mock_gemini_client["generate_structured"].side_effect = RuntimeError("429 quota")

    result = await content_compare(text_a="First report", text_b="Second report")

    assert result["category"] == "API_QUOTA_EXCEEDED"
    assert result["retryable"] is True
```

Async tests need no marker because the project sets `asyncio_mode = "auto"`.
Return concrete Pydantic instances from structured-output mocks. Add tests for
any behavior the example does not cover: custom schemas, source selection,
policy rejection, partial results, persistence, or registration as applicable.
[Writing Tests](WRITING_TESTS.md) explains the shared fixtures and mock boundaries.

## Step 6: Update Documentation and Verify Discovery

Update the user-facing guide and relevant instruction-file tool inventory when
the capability changes. Regenerate the manifest from the mounted app and inspect
the new entry's input schema and annotations. Avoid adding another manually
maintained table of every parameter.

Run focused tests while developing, then the project's required checks:

```bash
uv run --locked --extra dev pytest tests/test_content_compare.py -v
uv run --locked --extra dev ruff check src/ tests/
uv run --locked --extra dev pytest tests/ -q
PYTHONPATH=src uv run --locked --extra dev python scripts/export_tool_contract_manifest.py
```

Before handing off, confirm that the tool is discoverable from the root app,
returns its documented result and error shapes, and cannot bypass the policies
for its inputs. New local reads must apply `local_path_policy`; server-side URL
downloads must reuse `url_policy.download_checked()`.
