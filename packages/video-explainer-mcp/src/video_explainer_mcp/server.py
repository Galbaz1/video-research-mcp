"""Main FastMCP server — mounts all sub-servers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .config import get_config
from .tools.audio import audio_server
from .tools.planning import planning_server
from .tools.pipeline import cancel_background_renders, pipeline_server
from .tools.render_jobs import recover_render_jobs
from .tools.project import project_server
from .tools.quality import quality_server

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(server: FastMCP):
    """Startup/shutdown hook."""
    try:
        get_config()
        await recover_render_jobs()
        yield {}
    finally:
        await cancel_background_renders()
    logger.info("Lifespan shutdown: video-explainer-mcp")


app = FastMCP(
    "video-explainer",
    instructions=(
        "Video explainer synthesis — create, generate, and render "
        "explainer videos from research content. Wraps the "
        "video_explainer CLI for pipeline orchestration."
    ),
    lifespan=_lifespan,
)

app.mount(project_server)
app.mount(pipeline_server)
app.mount(quality_server)
app.mount(audio_server)
app.mount(planning_server)


def main() -> None:
    """Entry-point for ``video-explainer-mcp`` console script."""
    app.run()


if __name__ == "__main__":
    main()
