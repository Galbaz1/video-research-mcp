"""Batch video analysis tool — directory scanning with bounded concurrency."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..local_path_policy import enforce_local_access_root, resolve_path
from ..models.video_batch import BatchVideoItem, BatchVideoResult
from ..types import ThinkingLevel, VideoDirectoryPath, coerce_json_param
from .video import video_server
from .video_core import analyze_video
from .video_file import SUPPORTED_VIDEO_EXTENSIONS, _video_file_content

from video_research_mcp.tracing import trace


@video_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
@trace(name="video_batch_analyze", span_type="TOOL")
async def video_batch_analyze(
    directory: VideoDirectoryPath,
    instruction: Annotated[str, Field(
        description="What to analyze in each video"
    )] = "Provide a comprehensive analysis of this video.",
    glob_pattern: Annotated[str, Field(
        description="Glob pattern to filter files within the directory"
    )] = "*",
    output_schema: Annotated[dict | None, Field(
        description="Optional JSON Schema for each video's response"
    )] = None,
    thinking_level: ThinkingLevel = "high",
    max_files: Annotated[int, Field(ge=1, le=50, description="Maximum files to process")] = 20,
) -> dict:
    """Analyze all video files in a directory concurrently.

    Scans the directory for supported video files (mp4, webm, mov, avi, mkv,
    mpeg, wmv, 3gpp), then analyzes each with the given instruction using
    bounded concurrency (3 parallel Gemini calls).

    Args:
        directory: Path to a directory containing video files.
        instruction: What to analyze in each video.
        glob_pattern: Glob to filter files (default "*" matches all).
        output_schema: Optional JSON Schema dict for each result.
        thinking_level: Gemini thinking depth.
        max_files: Maximum number of files to process.

    Returns:
        Dict with directory, counts, and per-file results.
    """
    output_schema = coerce_json_param(output_schema, dict)

    try:
        dir_path = enforce_local_access_root(resolve_path(directory))
        if not dir_path.is_dir():
            return make_tool_error(ValueError(f"Not a directory: {directory}"))
    except PermissionError as exc:
        return make_tool_error(exc)

    video_files = sorted(
        f for f in dir_path.glob(glob_pattern)
        if f.is_file() and f.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    )[:max_files]

    if not video_files:
        return BatchVideoResult(
            directory=str(dir_path),
            total_files=0,
            successful=0,
            failed=0,
        ).model_dump(mode="json")

    semaphore = asyncio.Semaphore(3)

    async def _process(fp: Path) -> BatchVideoItem:
        async with semaphore:
            try:
                contents, content_id, _ = await _video_file_content(str(fp), instruction)
                result = await analyze_video(
                    contents,
                    instruction=instruction,
                    content_id=content_id,
                    source_label=str(fp),
                    output_schema=output_schema,
                    thinking_level=thinking_level,
                    use_cache=True,
                    local_filepath=str(fp.resolve()),
                )
                return BatchVideoItem(file_name=fp.name, file_path=str(fp), result=result)
            except Exception as exc:
                return BatchVideoItem(file_name=fp.name, file_path=str(fp), error=str(exc))

    items = await asyncio.gather(*[_process(f) for f in video_files])
    successful = sum(1 for i in items if not i.error)
    return BatchVideoResult(
        directory=str(dir_path),
        total_files=len(items),
        successful=successful,
        failed=len(items) - successful,
        items=list(items),
    ).model_dump(mode="json")
