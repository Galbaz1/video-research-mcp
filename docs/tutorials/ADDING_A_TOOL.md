# Adding a New Tool

How to add a tool to the video-research-mcp server, from choosing a sub-server through writing tests and updating documentation.

## Overview

The server uses a **composite FastMCP** architecture. The root server (`server.py`) mounts sub-servers, each owning a group of related tools:

```
server.py (root)
  +-- tools/video.py      -> video_server    (4 tools)
  +-- tools/youtube.py     -> youtube_server  (2 tools)
  +-- tools/research.py    -> research_server (3 tools)
  +-- tools/content.py     -> content_server  (2 tools)
  +-- tools/search.py      -> search_server   (1 tool)
  +-- tools/infra.py       -> infra_server    (2 tools)
  +-- tools/knowledge.py   -> knowledge_server(4 tools)
```

## Step 1: Choose a Sub-Server

If your tool fits an existing domain, add it to that sub-server's file. If it introduces a new domain, create a new sub-server.

**Decision guide:**

| Tool purpose | Sub-server |
|-------------|------------|
| Analyze video content | `tools/video.py` (video_server) |
| YouTube API data | `tools/youtube.py` (youtube_server) |
| Research/evidence | `tools/research.py` (research_server) |
| Analyze files/URLs/text | `tools/content.py` (content_server) |
| Web search | `tools/search.py` (search_server) |
| Server config/cache | `tools/infra.py` (infra_server) |
| Knowledge store queries | `tools/knowledge.py` (knowledge_server) |
| Something entirely new | Create a new sub-server (see Step 2b) |

## Step 2a: Add to an Existing Sub-Server

Here is a complete example -- adding a `content_compare` tool to the content sub-server.

### Define the output model

Create or extend a model in `models/`. Models serve as both Gemini structured output schemas and response types.

```python
# src/video_research_mcp/models/content.py

class ContentComparison(BaseModel):
    """Structured comparison of two content sources."""

    similarities: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    overall_assessment: str = ""
```

### Write the tool function

Every tool MUST have:

1. `ToolAnnotations` in the decorator
2. `@trace` decorator for optional MLflow tracing
3. `Annotated` params with `Field` constraints
4. A docstring with Args/Returns
5. Structured output via `GeminiClient`

```python
# src/video_research_mcp/tools/content.py

from ..models.content import ContentComparison
from ..tracing import trace

@content_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
@trace(name="content_compare", span_type="TOOL")
async def content_compare(
    text_a: Annotated[str, Field(min_length=1, description="First content to compare")],
    text_b: Annotated[str, Field(min_length=1, description="Second content to compare")],
    instruction: Annotated[str, Field(
        description="Comparison focus -- e.g. 'compare methodologies', 'find contradictions'"
    )] = "Compare these two pieces of content.",
    thinking_level: ThinkingLevel = "medium",
) -> dict:
    """Compare two pieces of content with a given instruction.

    Args:
        text_a: First content source.
        text_b: Second content source.
        instruction: What aspect to compare.
        thinking_level: Gemini thinking depth.

    Returns:
        Dict matching ContentComparison schema.
    """
    try:
        prompt = f"{instruction}\n\n--- Content A ---\n{text_a}\n\n--- Content B ---\n{text_b}"
        result = await GeminiClient.generate_structured(
            prompt,
            schema=ContentComparison,
            thinking_level=thinking_level,
        )
        return result.model_dump()
    except Exception as exc:
        return make_tool_error(exc)
```

### Key conventions

**`@trace` decorator** -- optional MLflow tracing for observability:

```python
from ..tracing import trace

@server.tool(annotations=ToolAnnotations(...))
@trace(name="my_tool", span_type="TOOL")
async def my_tool(...) -> dict:
```

The `@trace` decorator goes **between** `@server.tool` and the function definition. It creates a `TOOL` root span in MLflow that parents any Gemini autolog child spans. When tracing is not configured (`mlflow-tracing` not installed or `GEMINI_TRACING_ENABLED=false`), the decorator is a no-op -- it passes through the function unchanged.

Parameters:
- `name` -- span name (typically matches the tool function name)
- `span_type` -- always `"TOOL"` for MCP tool entrypoints

Source: `src/video_research_mcp/tracing.py`

**ToolAnnotations** -- declare the tool's behavior to MCP clients:

| Hint | Meaning |
|------|---------|
| `readOnlyHint=True` | Tool does not modify state |
| `destructiveHint=True` | Tool deletes or overwrites data (e.g., cache clear) |
| `idempotentHint=True` | Calling twice with same args gives same result |
| `openWorldHint=True` | Tool accesses external services (Gemini, YouTube, web) |

**Parameter types** -- use shared types from `types.py`:

```python
from ..types import ThinkingLevel, Scope, YouTubeUrl, TopicParam
```

These provide schema-level validation (e.g., `YouTubeUrl` requires `min_length=10`).

**Error handling** -- never raise from a tool. Always catch and return `make_tool_error()`:

```python
from ..errors import make_tool_error

try:
    # ... tool logic
except Exception as exc:
    return make_tool_error(exc)
```

This returns a structured error dict with `error`, `category`, `hint`, and `retryable` fields.

## Step 2b: Create a New Sub-Server

If your tool introduces a new domain:

### Create the sub-server file

```python
# src/video_research_mcp/tools/my_domain.py
"""My domain tools -- N tools on a FastMCP sub-server."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import GeminiClient
from ..errors import make_tool_error
from ..tracing import trace
from ..types import ThinkingLevel

logger = logging.getLogger(__name__)
my_domain_server = FastMCP("my-domain")


@my_domain_server.tool(
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True)
)
@trace(name="my_tool", span_type="TOOL")
async def my_tool(
    input_text: Annotated[str, Field(min_length=1, description="Input to process")],
    thinking_level: ThinkingLevel = "medium",
) -> dict:
    """Process input with Gemini.

    Args:
        input_text: The text to process.
        thinking_level: Gemini thinking depth.

    Returns:
        Dict with processed results.
    """
    try:
        result = await GeminiClient.generate(
            input_text,
            thinking_level=thinking_level,
        )
        return {"result": result}
    except Exception as exc:
        return make_tool_error(exc)
```

### Mount in server.py

```python
# src/video_research_mcp/server.py
from .tools.my_domain import my_domain_server

app.mount(my_domain_server)
```

### Add shared types (if needed)

If your tool introduces new Literal types or Annotated aliases, add them to `types.py`:

```python
# src/video_research_mcp/types.py
MyMode = Literal["fast", "thorough", "exhaustive"]
```

## Step 3: GeminiClient Integration

The server provides two entry points:

### `generate_structured()` -- validated Pydantic output (preferred)

Use when you want Gemini to return data matching a Pydantic model:

```python
from ..client import GeminiClient
from ..models.my_domain import MyResult

result = await GeminiClient.generate_structured(
    contents,                      # str, Content, or list[Content]
    schema=MyResult,               # Pydantic model class
    thinking_level="medium",       # optional override
    system_instruction="...",      # optional system prompt
)
# result is a validated MyResult instance
return result.model_dump()
```

Under the hood, this:
1. Extracts the model's JSON schema via `MyResult.model_json_schema()`
2. Passes it as `response_json_schema` to Gemini
3. Validates the raw JSON response with `MyResult.model_validate_json(raw)`

### `generate()` -- raw text or custom schema

Use for unstructured responses or caller-provided schemas:

```python
# Raw text response
text = await GeminiClient.generate(
    "Explain quantum computing",
    thinking_level="high",
)

# Custom JSON schema (dict, not Pydantic)
raw_json = await GeminiClient.generate(
    contents,
    response_schema={"type": "object", "properties": {...}},
    thinking_level="low",
)
result = json.loads(raw_json)
```

### Tools wiring (Google Search, URL context)

```python
from google.genai import types

# Web-grounded response
text = await GeminiClient.generate(
    "Search for: latest AI papers",
    tools=[types.Tool(google_search=types.GoogleSearch())],
)

# URL context
text = await GeminiClient.generate(
    "Analyze this URL: https://example.com",
    tools=[types.Tool(url_context=types.UrlContext())],
)
```

## Step 4: Write-Through Knowledge Store

All 18 existing tools auto-store their results to Weaviate when it is configured. New tools should follow this convention. Add a store function in `weaviate_store.py` and call it from your tool after computing the result:

```python
# In your tool function, after getting the result:
from ..weaviate_store import store_my_result
await store_my_result(result, source, instruction)
```

Store calls are **non-fatal** -- the tool succeeds even if the Weaviate write fails. The import is done inside the function body to avoid circular imports.

If your tool needs a new Weaviate collection, define it in `weaviate_schema.py` and add the collection name to `KnowledgeCollection` in `types.py`.

See [KNOWLEDGE_STORE.md](./KNOWLEDGE_STORE.md) for the full write-through pattern and collection schema guide.

## Step 5: Write Tests

Every new tool needs tests. See [WRITING_TESTS.md](./WRITING_TESTS.md) for the full guide. Here is the minimal pattern:

```python
# tests/test_my_domain_tools.py
"""Tests for my domain tools."""

from __future__ import annotations

import pytest

from video_research_mcp.models.my_domain import MyResult
from video_research_mcp.tools.my_domain import my_tool


class TestMyTool:
    @pytest.mark.asyncio
    async def test_returns_structured_result(self, mock_gemini_client):
        """GIVEN valid input WHEN my_tool is called THEN returns MyResult dict."""
        mock_gemini_client["generate_structured"].return_value = MyResult(
            field="value",
        )

        result = await my_tool(input_text="test input")

        assert result["field"] == "value"
        mock_gemini_client["generate_structured"].assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self, mock_gemini_client):
        """GIVEN Gemini failure WHEN my_tool is called THEN returns error dict."""
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("API error")

        result = await my_tool(input_text="test input")

        assert "error" in result
        assert "category" in result
```

Run your tests:

```bash
uv run pytest tests/test_my_domain_tools.py -v
```

## Step 6: Update CLAUDE.md

Update the tool surface table in `CLAUDE.md` to include your new tool:

```markdown
| `my_tool` | my_domain | input_text + instruction | `MyResult` |
```

## Checklist

Before submitting:

- [ ] Tool has `ToolAnnotations` in the decorator
- [ ] Tool has `@trace(name="tool_name", span_type="TOOL")` decorator
- [ ] All params use `Annotated[type, Field(...)]` with descriptions
- [ ] Docstring has Args and Returns sections
- [ ] Uses `generate_structured()` for default schemas
- [ ] Catches all exceptions and returns `make_tool_error()`
- [ ] Any new URL download flow reuses `url_policy.download_checked()` (no ad hoc redirect-following clients)
- [ ] Output model defined in `models/`
- [ ] Write-through store function added to `weaviate_store.py`
- [ ] Tests written with `mock_gemini_client` fixture
- [ ] Sub-server mounted in `server.py` (if new)
- [ ] CLAUDE.md tool table updated
- [ ] File stays under 300 lines of code

## Reference

- [Architecture Guide](../ARCHITECTURE.md) -- server design and patterns
- [Writing Tests](./WRITING_TESTS.md) -- test fixtures and conventions
- [Knowledge Store](./KNOWLEDGE_STORE.md) -- Weaviate integration
- Source: `src/video_research_mcp/tools/content.py` -- example of a well-structured tool file
- Source: `src/video_research_mcp/client.py` -- GeminiClient API
