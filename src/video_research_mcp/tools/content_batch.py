"""Batch content analysis tool — directory or file list with compare/individual modes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated, Literal

from google.genai import types
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..local_path_policy import enforce_local_access_root, resolve_path
from ..models.content_batch import BatchContentItem, BatchContentResult
from ..tracing import trace
from ..types import ThinkingLevel, coerce_json_param
from ..weaviate_store import store_content_analysis
from .content import _analyze_parts, _build_content_parts, content_server

logger = logging.getLogger(__name__)

SUPPORTED_CONTENT_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".html": "text/html",
    ".xml": "text/xml",
    ".json": "application/json",
    ".csv": "text/csv",
}


def _resolve_files(
    directory: str | None,
    file_paths: list[str] | None,
    glob_pattern: str,
    max_files: int,
) -> list[Path]:
    """Resolve content files from a directory scan or explicit path list.

    Args:
        directory: Directory to scan for content files.
        file_paths: Explicit list of file paths.
        glob_pattern: Glob pattern for directory filtering.
        max_files: Maximum number of files to return.

    Returns:
        Sorted list of resolved Path objects.

    Raises:
        ValueError: If both or neither sources provided.
        FileNotFoundError: If a specified file does not exist.
    """
    if directory and file_paths:
        raise ValueError("Provide either directory or file_paths, not both")
    if not directory and not file_paths:
        raise ValueError("Provide either directory or file_paths")

    if directory:
        dir_path = enforce_local_access_root(resolve_path(directory))
        if not dir_path.is_dir():
            raise FileNotFoundError(f"Not a directory: {directory}")
        files = sorted(
            f for f in dir_path.glob(glob_pattern)
            if f.is_file() and f.suffix.lower() in SUPPORTED_CONTENT_EXTENSIONS
        )
        return files[:max_files]

    resolved: list[Path] = []
    for fp in file_paths:  # type: ignore[union-attr]
        p = enforce_local_access_root(resolve_path(fp))
        if not p.exists():
            raise FileNotFoundError(f"File not found: {fp}")
        if p.suffix.lower() in SUPPORTED_CONTENT_EXTENSIONS:
            resolved.append(p)
    return resolved[:max_files]


def _build_file_parts(path: Path) -> list[types.Part]:
    """Build Gemini parts for a single content file.

    Args:
        path: Path to the content file.

    Returns:
        List of Gemini Part objects (label + file data).
    """
    mime = SUPPORTED_CONTENT_EXTENSIONS.get(path.suffix.lower(), "text/plain")
    return [
        types.Part(text=f"--- File: {path.name} ---"),
        types.Part.from_bytes(data=path.read_bytes(), mime_type=mime),
    ]


async def _compare_files(
    files: list[Path],
    instruction: str,
    output_schema: dict | None,
    thinking_level: ThinkingLevel,
) -> dict:
    """Analyze all files in a single Gemini call for cross-document comparison.

    Args:
        files: Content files to compare.
        instruction: Analysis instruction.
        output_schema: Optional JSON Schema for the response.
        thinking_level: Gemini thinking depth.

    Returns:
        Parsed result dict from Gemini.
    """
    from ..models.content import ContentResult

    all_parts: list[types.Part] = []
    for f in files:
        all_parts.extend(_build_file_parts(f))

    schema = output_schema or ContentResult.model_json_schema()
    return await _analyze_parts(all_parts, instruction, schema, output_schema, thinking_level)


async def _individual_files(
    files: list[Path],
    instruction: str,
    output_schema: dict | None,
    thinking_level: ThinkingLevel,
) -> list[BatchContentItem]:
    """Analyze each file individually with bounded concurrency.

    Args:
        files: Content files to analyze.
        instruction: Analysis instruction.
        output_schema: Optional JSON Schema for each response.
        thinking_level: Gemini thinking depth.

    Returns:
        List of BatchContentItem with per-file results or errors.
    """
    from ..models.content import ContentResult

    semaphore = asyncio.Semaphore(3)
    schema = output_schema or ContentResult.model_json_schema()

    async def _process(path: Path) -> BatchContentItem:
        async with semaphore:
            try:
                parts, _ = _build_content_parts(file_path=str(path))
                result = await _analyze_parts(
                    parts, instruction, schema, output_schema, thinking_level,
                )
                return BatchContentItem(
                    file_name=path.name, file_path=str(path), result=result,
                )
            except Exception as exc:
                return BatchContentItem(
                    file_name=path.name, file_path=str(path), error=str(exc),
                )

    return list(await asyncio.gather(*[_process(f) for f in files]))


@content_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="content_batch_analyze", span_type="TOOL")
async def content_batch_analyze(
    instruction: Annotated[str, Field(
        description="What to analyze — e.g. 'compare methodologies', "
        "'summarize each document', 'extract key findings'"
    )] = "Provide a comprehensive analysis of these documents.",
    directory: Annotated[str | None, Field(
        description="Directory to scan for content files"
    )] = None,
    file_paths: Annotated[list[str] | None, Field(
        description="Explicit list of file paths to analyze"
    )] = None,
    glob_pattern: Annotated[str, Field(
        description="Glob pattern to filter files within directory"
    )] = "*",
    mode: Annotated[Literal["compare", "individual"], Field(
        description="'compare' for cross-document analysis in one call, "
        "'individual' for separate per-file analysis"
    )] = "compare",
    output_schema: Annotated[dict | None, Field(
        description="Optional JSON Schema for each result"
    )] = None,
    thinking_level: ThinkingLevel = "high",
    max_files: Annotated[int, Field(ge=1, le=50, description="Maximum files to process")] = 20,
) -> dict:
    """Analyze multiple content files from a directory or explicit file list.

    Supports two modes: 'compare' sends all files to Gemini in a single call
    for cross-document analysis, 'individual' analyzes each file separately
    with bounded concurrency (3 parallel calls).

    Args:
        instruction: What to analyze or extract from the content.
        directory: Directory to scan for content files.
        file_paths: Explicit list of file paths to analyze.
        glob_pattern: Glob to filter files in directory mode.
        mode: 'compare' or 'individual' analysis mode.
        output_schema: Optional JSON Schema dict for custom output shape.
        thinking_level: Gemini thinking depth.
        max_files: Maximum number of files to process.

    Returns:
        Dict with file counts, per-file items, and optional comparison result.
    """
    file_paths = coerce_json_param(file_paths, list)
    output_schema = coerce_json_param(output_schema, dict)

    try:
        files = _resolve_files(directory, file_paths, glob_pattern, max_files)
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        return make_tool_error(exc)

    if not files:
        return BatchContentResult(
            directory=str(directory or ""),
            total_files=0, successful=0, failed=0, mode=mode,
        ).model_dump(mode="json")

    try:
        if mode == "compare":
            comparison = await _compare_files(files, instruction, output_schema, thinking_level)
            items = [BatchContentItem(file_name=f.name, file_path=str(f)) for f in files]
            result = BatchContentResult(
                directory=str(directory or ""),
                total_files=len(files), successful=len(files), failed=0,
                mode=mode, items=items, comparison=comparison,
            )
        else:
            items = await _individual_files(files, instruction, output_schema, thinking_level)
            successful = sum(1 for i in items if not i.error)
            result = BatchContentResult(
                directory=str(directory or ""),
                total_files=len(items), successful=successful,
                failed=len(items) - successful, mode=mode, items=items,
            )

        for item in result.items:
            if item.result or result.comparison:
                data = item.result if mode == "individual" else result.comparison
                await store_content_analysis(
                    data,
                    item.file_path,
                    instruction,
                    local_filepath=item.file_path,
                )

        return result.model_dump(mode="json")
    except Exception as exc:
        return make_tool_error(exc)
