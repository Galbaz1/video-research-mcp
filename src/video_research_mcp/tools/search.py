"""Web search tool — Google Search grounding via Gemini."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import GeminiClient
from ..retry import with_retry
from ..config import get_config
from ..tracing import trace
from ..errors import make_tool_error

logger = logging.getLogger(__name__)
search_server = FastMCP("search")


@search_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="web_search", span_type="TOOL")
async def web_search(
    query: Annotated[str, Field(min_length=2, description="Search query")],
    num_results: Annotated[int, Field(ge=1, le=20, description="Number of results")] = 5,
) -> dict:
    """Search the web using Gemini's built-in Google Search grounding.

    Args:
        query: Search terms.
        num_results: How many results to return (1-20).

    Returns:
        Dict with query, response text, and grounding sources.
    """
    try:
        from google.genai import types

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
        client = GeminiClient.get()
        cfg = get_config()
        response = await with_retry(
            lambda: client.aio.models.generate_content(
                model=cfg.flash_model,
                contents=f"Search for: {query}\n\nReturn the top {num_results} most relevant results with title, URL, and a brief snippet for each.",
                config=config,
            )
        )
        text = response.text or ""

        grounding = {}
        if response.candidates:
            cand = response.candidates[0]
            gm = getattr(cand, "grounding_metadata", None)
            if gm:
                chunks = getattr(gm, "grounding_chunks", []) or []
                grounding["sources"] = [
                    {
                        "title": getattr(getattr(c, "web", None), "title", ""),
                        "url": getattr(getattr(c, "web", None), "uri", ""),
                    }
                    for c in chunks
                ]

        result = {"query": query, "response": text, **grounding}
        from ..weaviate_store import store_web_search
        await store_web_search(query, text, grounding.get("sources", []))
        return result

    except Exception as exc:
        return make_tool_error(exc)
