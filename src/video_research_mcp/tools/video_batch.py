"""Batch video analysis tool — directory scanning with bounded concurrency."""

from __future__ import annotations

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..local_path_policy import enforce_local_access_root, resolve_path
from ..media_identity import identify_source
from ..video_jobs import execute_batch, runtime_settings
from ..types import ThinkingLevel, VideoDirectoryPath, coerce_json_param
from .video import video_server
from .video_file import SUPPORTED_VIDEO_EXTENSIONS

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
    instruction: Annotated[
        str, Field(description="What to analyze in each video")
    ] = "Provide a comprehensive analysis of this video.",
    glob_pattern: Annotated[
        str, Field(description="Glob pattern to filter files within the directory")
    ] = "*",
    output_schema: Annotated[
        dict | None, Field(description="Optional JSON Schema for each video's response")
    ] = None,
    thinking_level: ThinkingLevel = "high",
    max_files: Annotated[int, Field(ge=1, le=50, description="Maximum files to process")] = 20,
    job_id: Annotated[
        str | None,
        Field(
            description="Resume this exact batch without repeating completed or ambiguous submissions"
        ),
    ] = None,
    max_concurrency: Annotated[
        int, Field(ge=1, le=3, strict=True, description="Maximum concurrent item submissions")
    ] = 3,
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
        job_id: Optional durable batch identity for safe recovery.
        max_concurrency: Bounded concurrent item submissions.

    Returns:
        Dict with directory, counts, and per-file results.
    """
    output_schema = coerce_json_param(output_schema, dict)

    try:
        dir_path = enforce_local_access_root(resolve_path(directory))
        if not dir_path.is_dir():
            return make_tool_error(ValueError(f"Not a directory: {directory}"))
        video_files = sorted(
            f
            for f in dir_path.glob(glob_pattern)
            if f.is_file() and f.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        )[:max_files]
        items = []
        for path in video_files:
            source = identify_source(str(path), persist=False)
            items.append(
                {
                    "file_name": path.name,
                    "file_path": str(path.resolve()),
                    "source_sha256": source.digest,
                    "status": "queued" if source.state == "fresh" else "failed",
                    "result": {},
                    "error": "" if source.state == "fresh" else "Original source unavailable",
                }
            )
        return await execute_batch(
            {
                "directory": str(dir_path),
                "instruction": instruction,
                "glob_pattern": glob_pattern,
                "max_files": max_files,
                "output_schema": output_schema,
                "thinking_level": thinking_level,
                "max_concurrency": max_concurrency,
                "items": items,
                "runtime": runtime_settings(),
            },
            job_id,
        )
    except Exception as exc:
        return make_tool_error(exc)
