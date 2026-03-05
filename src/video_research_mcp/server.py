"""Main FastMCP server — mounts all sub-servers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .client import GeminiClient
from . import context_cache, tracing
from .config import get_config
from .weaviate_client import WeaviateClient
from .tools.video import video_server
from .tools.research import research_server, _ensure_document_tool, _ensure_web_tools
from .tools.content import content_server, _ensure_batch_tool
from .tools.search import search_server
from .tools.infra import infra_server
from .tools.youtube import youtube_server
from .tools.knowledge import knowledge_server

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(server: FastMCP):
    """Startup/shutdown hook — sets up tracing, tears down shared clients."""
    tracing.setup()
    yield {}
    tracing.shutdown()
    if get_config().clear_cache_on_shutdown:
        await context_cache.clear()
    await WeaviateClient.aclose()
    closed = await GeminiClient.close_all()
    logger.info("Lifespan shutdown: closed %d client(s)", closed)


app = FastMCP(
    "video-research",
    instructions=(
        "Unified Gemini research partner — video analysis, deep research, "
        "content extraction. Powered by Gemini 3.1 Pro with thinking support."
    ),
    lifespan=_lifespan,
)

app.mount(video_server)
_ensure_document_tool()  # register research_document on research_server
_ensure_web_tools()  # register Deep Research tools on research_server
app.mount(research_server)
_ensure_batch_tool()  # register content_batch_analyze on content_server
app.mount(content_server)
app.mount(search_server)
app.mount(infra_server)
app.mount(youtube_server)
app.mount(knowledge_server)


def main() -> None:
    """Entry-point for ``video-research-mcp`` console script."""
    app.run()


if __name__ == "__main__":
    main()
