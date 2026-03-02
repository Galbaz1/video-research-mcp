"""Content analysis tools — 2 tools on a FastMCP sub-server."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from google.genai import types
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import GeminiClient
from ..tracing import trace
from ..errors import make_tool_error
from ..models.content import ContentResult
from ..local_path_policy import enforce_local_access_root, resolve_path
from ..prompts.content import CONTENT_ANALYSIS_SYSTEM, STRUCTURED_EXTRACT
from ..types import ThinkingLevel, coerce_json_param
from ..url_policy import UrlPolicyError, validate_url

logger = logging.getLogger(__name__)
content_server = FastMCP("content")


def _build_content_parts(
    *,
    file_path: str | None = None,
    url: str | None = None,
    text: str | None = None,
) -> tuple[list[types.Part], str]:
    """Build Gemini parts from the first non-None content source.

    Returns (parts, description) for prompt interpolation.
    """
    parts: list[types.Part] = []
    description = ""

    if file_path:
        p = enforce_local_access_root(resolve_path(file_path))
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        mime = "application/pdf" if p.suffix.lower() == ".pdf" else "text/plain"
        data = p.read_bytes()
        parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        description = f"Document: {p.name}"
    elif url:
        parts.append(types.Part(file_data=types.FileData(file_uri=url)))
        description = f"Content at URL: {url}"
    elif text:
        parts.append(types.Part(text=text))
        description = "Provided text content"
    else:
        raise ValueError("Provide at least one of: file_path, url, or text")

    return parts, description


@content_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="content_analyze", span_type="TOOL")
async def content_analyze(
    instruction: Annotated[str, Field(
        description="What to analyze — e.g. 'summarize key findings', "
        "'extract methodology', 'list all citations'"
    )] = "Provide a comprehensive analysis of this content.",
    file_path: Annotated[str | None, Field(description="Local file path (PDF or text)")] = None,
    url: Annotated[str | None, Field(description="URL to analyze")] = None,
    text: Annotated[str | None, Field(description="Raw text content")] = None,
    output_schema: Annotated[dict | None, Field(
        description="Optional JSON Schema for the response. "
        "If omitted, uses default ContentResult schema."
    )] = None,
    thinking_level: ThinkingLevel = "medium",
) -> dict:
    """Analyze content (file, URL, or text) with any instruction.

    Provide exactly one of file_path, url, or text. Uses Gemini's structured
    output for reliable JSON responses. Pass a custom output_schema to control
    the response shape, or use the default ContentResult schema.

    Args:
        instruction: What to analyze or extract from the content.
        file_path: Path to a local PDF or text file.
        url: URL to fetch and analyze.
        text: Raw text content.
        output_schema: Optional JSON Schema dict for custom output shape.
        thinking_level: Gemini thinking depth.

    Returns:
        Dict matching ContentResult schema (default) or the custom output_schema.
    """
    output_schema = coerce_json_param(output_schema, dict)

    try:
        sources = sum(x is not None for x in (file_path, url, text))
        if sources == 0:
            raise ValueError("Provide exactly one of: file_path, url, or text")
        if sources > 1:
            provided = ", ".join(
                k for k, v in [("file_path", file_path), ("url", url), ("text", text)] if v is not None
            )
            raise ValueError(f"Provide exactly one of: file_path, url, or text — got {provided}")

        if url:
            await validate_url(url)
            use_url_context = True
            prompt_text = f"{instruction}\n\nAnalyze this exact URL:\n{url}"
        else:
            use_url_context = False
            parts, desc = _build_content_parts(file_path=file_path, text=text)
    except (FileNotFoundError, PermissionError, UrlPolicyError, ValueError) as exc:
        return make_tool_error(exc)

    try:
        schema = output_schema or ContentResult.model_json_schema()

        if use_url_context:
            result = await _analyze_url(prompt_text, instruction, schema, output_schema, thinking_level)
        else:
            result = await _analyze_parts(parts, instruction, schema, output_schema, thinking_level)

        from ..weaviate_store import store_content_analysis
        source = url or file_path or "(text)"
        local_filepath = str(Path(file_path).expanduser().resolve()) if file_path else ""
        await store_content_analysis(
            result,
            source,
            instruction,
            local_filepath=local_filepath,
        )
        return result

    except Exception as exc:
        return make_tool_error(exc)


async def _analyze_url(
    prompt_text: str,
    instruction: str,
    schema: dict,
    output_schema: dict | None,
    thinking_level: ThinkingLevel,
) -> dict:
    """Analyze URL content using Gemini's UrlContext tool wiring.

    Attempts structured output with UrlContext first. If that fails (e.g.
    UrlContext and response_json_schema don't compose), falls back to a
    two-step approach: fetch unstructured text, then reshape into schema.
    """
    try:
        raw = await GeminiClient.generate(
            prompt_text,
            thinking_level=thinking_level,
            system_instruction=CONTENT_ANALYSIS_SYSTEM,
            tools=[types.Tool(url_context=types.UrlContext())],
            response_schema=schema,
        )
        return json.loads(raw)
    except Exception:
        # Fallback: two-step — fetch unstructured, then reshape
        unstructured = await GeminiClient.generate(
            prompt_text,
            thinking_level=thinking_level,
            system_instruction=CONTENT_ANALYSIS_SYSTEM,
            tools=[types.Tool(url_context=types.UrlContext())],
        )
        return await _reshape_to_schema(instruction, unstructured, output_schema)


async def _analyze_parts(
    parts: list[types.Part],
    instruction: str,
    schema: dict,
    output_schema: dict | None,
    thinking_level: ThinkingLevel,
) -> dict:
    """Analyze file/text content from pre-built Gemini parts.

    Appends the instruction as a text part, then routes to either
    ``generate`` (custom schema) or ``generate_structured`` (ContentResult).
    """
    parts.append(types.Part(text=instruction))
    contents = types.Content(parts=parts)

    if output_schema:
        raw = await GeminiClient.generate(
            contents,
            thinking_level=thinking_level,
            system_instruction=CONTENT_ANALYSIS_SYSTEM,
            response_schema=output_schema,
        )
        return json.loads(raw)

    result = await GeminiClient.generate_structured(
        contents,
        schema=ContentResult,
        thinking_level=thinking_level,
        system_instruction=CONTENT_ANALYSIS_SYSTEM,
    )
    return result.model_dump(mode="json")


async def _reshape_to_schema(
    instruction: str,
    unstructured: str,
    output_schema: dict | None,
) -> dict:
    """Reshape unstructured Gemini text into the target schema via a second LLM call."""
    if output_schema:
        raw = await GeminiClient.generate(
            f"{instruction}\n\nContent:\n{unstructured}",
            thinking_level="low",
            system_instruction=CONTENT_ANALYSIS_SYSTEM,
            response_schema=output_schema,
        )
        return json.loads(raw)

    result = await GeminiClient.generate_structured(
        f"{instruction}\n\nContent:\n{unstructured}",
        schema=ContentResult,
        thinking_level="low",
        system_instruction=CONTENT_ANALYSIS_SYSTEM,
    )
    return result.model_dump(mode="json")


@content_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="content_extract", span_type="TOOL")
async def content_extract(
    content: Annotated[str, Field(min_length=1, description="Text content to extract from")],
    schema: Annotated[dict, Field(description="JSON Schema defining the extraction structure")],
) -> dict:
    """Extract structured data from content using a JSON Schema.

    Uses Gemini's response_json_schema for guaranteed structured output.

    Args:
        content: Source text to extract data from.
        schema: JSON Schema describing the desired output structure.

    Returns:
        Dict matching the provided schema, or error dict on parse failure.
    """
    schema = coerce_json_param(schema, dict)

    try:
        prompt = STRUCTURED_EXTRACT.format(
            content=content,
            schema_description=json.dumps(schema, indent=2),
        )
        resp = await GeminiClient.generate(
            prompt,
            thinking_level="low",
            system_instruction=CONTENT_ANALYSIS_SYSTEM,
            response_schema=schema,
        )
        return json.loads(resp)
    except json.JSONDecodeError:
        return {"raw_response": resp, "error": "Failed to parse JSON from model response"}
    except Exception as exc:
        return make_tool_error(exc)


def _ensure_batch_tool() -> None:
    """Import content_batch to register its tool on content_server.

    Deferred to avoid circular import — content_batch imports from this module.
    Called by server.py after content_server is fully initialised.
    """
    from . import content_batch  # noqa: F401
