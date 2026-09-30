---
paths: "src/**/*.py"
---

# FastMCP Patterns (v4.x)

## Server & Tool Registration

- One `FastMCP` instance per sub-server, mounted onto root via `app.mount(sub_server)`
- Tools use `@server.tool(annotations=ToolAnnotations(...))` — always include annotations
- `ToolAnnotations` imported from `mcp.types`, NOT from `fastmcp`
- Lifespan via `@asynccontextmanager` passed to `FastMCP(lifespan=...)`

## Tool Functions

- Tools are plain async functions — FastMCP 4.x preserves callability (no FunctionTool wrapping)
- Never write compatibility code for FastMCP 2.x — our constraint is `>=4.0.10,<5`
- Return `dict`, not Pydantic models — serialize via `model.model_dump()` before returning
- Never raise exceptions from tools — return `make_tool_error()` dicts
- All tools must have `@trace(name="tool_name", span_type="TOOL")` decorator (from `...tracing import trace`) — no-op when mlflow not installed

## Parameters

- All params use `Annotated[type, Field(description="...")]`
- `ThinkingLevel` type alias for thinking depth params
- Optional params with defaults, not required params with None
