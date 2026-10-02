# AGENTS.md (src scope)

Applies to source files under `src/`.

## FastMCP Patterns (v4.x)

- Use one `FastMCP` instance per sub-server, mounted on the root app.
- Register tools with `@server.tool(annotations=ToolAnnotations(...))`.
- Import `ToolAnnotations` from `mcp.types` (not from `fastmcp`).
- Use lifespan via `@asynccontextmanager` when needed.

## Tool Function Rules

- Tools are async functions and should stay directly callable.
- Do not add FastMCP 2.x compatibility code.
- Generative tools return `dict` values; serialize Pydantic models using `model_dump()`.
- Native media tools may return `mcp.types.CallToolResult` with typed
  `structuredContent`, a JSON text block, and bounded `ImageContent`. Declare an
  explicit success/error output schema and offer the same metadata without images.
  Existing tools keep their published return contracts.
- Never let tool exceptions escape; return `make_tool_error()` instead.
- All tools must have `@trace(name="tool_name", span_type="TOOL")` decorator — no-op when mlflow not installed.

## Parameter Rules

- Use `Annotated[type, Field(description="...")]` for parameters.
- Use `ThinkingLevel` alias for thinking depth fields.
- Prefer optional params with defaults over required params set to `None`.

## Google GenAI SDK Patterns

- Use the singleton `GeminiClient.get()`; do not instantiate `genai.Client()` directly.
- Route generation through `GeminiClient.generate()`, `.generate_structured()`, or `.generate_json_validated()`.
- Deterministic local operations validate typed inputs/results directly and do not
  invoke Gemini. Optional external MCPs run separately and use their own schemas;
  they must not add provider/runtime requirements to core startup.
- Use async generation via `client.aio.models.generate_content()`.
- Import SDK types from `google.genai import types`.

Key usage:
- `types.Part`, `types.Content`, `types.GenerateContentConfig`, `types.ThinkingConfig`
- Video parts via `types.Part.from_uri(file_uri=..., mime_type=...)`

## Thinking and Caching

- Include `ThinkingConfig(thinking_level=...)` through project config.
- The default model supports `low`, `medium`, `high`; reject unsupported `minimal` with an actionable validation error.
- Keep defensive attribute checks such as `getattr(..., "thought", False)` and grounding metadata checks.
- Use cached content in `GenerateContentConfig`; prewarm and lookup through context cache helpers.
