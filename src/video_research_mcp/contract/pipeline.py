"""Strict video contract pipeline — orchestrates analysis, rendering, and quality gates.

Entry point: run_strict_pipeline() — called by video_analyze when strict_contract=True.
Stages: analysis → strategy + concept map (parallel) → render → quality gates → finalize.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from ..client import GeminiClient
from ..errors import ErrorCategory, make_tool_error
from ..models.coverage import MediaCoverage
from ..models.video_contract import ConceptMap, StrategyReport, StrictVideoResult
from .quality import run_quality_gates
from .render import render_artifacts

logger = logging.getLogger(__name__)

_STRATEGY_PROMPT = (
    "Based on the following video analysis, create a strategic report with "
    "actionable sections and key strategic takeaways.\n\n"
    "Analysis:\nTitle: {title}\nSummary: {summary}\n"
    "Key Points:\n{key_points}\n"
)

_CONCEPT_MAP_PROMPT = (
    "Based on the following video analysis, create a concept map showing "
    "the relationships between key ideas. Each node should have a unique id, "
    "label, and category. Edges should show how concepts relate.\n\n"
    "Analysis:\nTitle: {title}\nTopics: {topics}\n"
    "Key Points:\n{key_points}\n"
)


def sanitize_slug(title: str) -> str:
    """Derive a filesystem-safe slug from a title.

    Args:
        title: Human-readable title to slugify.

    Returns:
        Lowercase, hyphen-separated slug (max 50 chars).

    Raises:
        ValueError: If the title cannot produce a valid slug.
    """
    slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))
    slug = re.sub(r"-+", "-", slug).strip("-")[:50]
    if not slug:
        raise ValueError(f"Cannot derive safe slug from title: {title!r}")
    if Path(slug).name != slug:
        raise ValueError(f"Slug contains path traversal: {slug!r}")
    return slug


def _resolve_output_dir(slug: str) -> Path:
    """Determine the output directory, using atomic mkdir to avoid races.

    Always appends a short UUID suffix so concurrent requests with the
    same slug never collide. os.makedirs is atomic on POSIX — if two
    processes race, exactly one succeeds and the other gets FileExistsError.
    """
    base = Path(os.environ.get("VIDEO_OUTPUT_DIR", "output"))
    target = base / f"{slug}-{uuid.uuid4().hex[:8]}"
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        target = base / f"{slug}-{uuid.uuid4().hex[:8]}"
        target.mkdir(parents=True, exist_ok=True)
    return target


async def run_strict_pipeline(
    contents,
    *,
    instruction: str,
    content_id: str,
    source_label: str,
    thinking_level: str = "high",
    report_language: str = "en",
    coverage_min_ratio: float = 0.90,
    metadata_context: str | None = None,
) -> dict:
    """Run the strict contract pipeline: analyze → render → quality gate.

    Args:
        contents: Gemini Content with video part + text prompt.
        instruction: Analysis instruction.
        content_id: Unique video ID for caching.
        source_label: Human-readable source (URL or path).
        thinking_level: Gemini thinking depth for main analysis.
        report_language: ISO 639-1 language code.
        coverage_min_ratio: Minimum coverage ratio for quality gate.
        metadata_context: Optional YouTube metadata context.

    Returns:
        Dict with analysis results, artifact paths, and quality report.
    """
    start_time = time.monotonic()

    # Stage 1: Main analysis (with metadata context when available)
    try:
        analysis_model = await GeminiClient.generate_structured(
            contents,
            schema=StrictVideoResult,
            thinking_level=thinking_level,
            system_instruction=metadata_context,
        )
        analysis = analysis_model.model_dump(mode="json")
    except Exception as exc:
        return make_tool_error(exc)

    # Stage 2+3: Strategy report + concept map (parallel)
    key_points_text = "\n".join(f"- {p}" for p in analysis.get("key_points", []))
    topics_text = ", ".join(analysis.get("topics", []))

    strategy_prompt = _STRATEGY_PROMPT.format(
        title=analysis.get("title", ""),
        summary=analysis.get("summary", ""),
        key_points=key_points_text,
    )
    concept_prompt = _CONCEPT_MAP_PROMPT.format(
        title=analysis.get("title", ""),
        topics=topics_text,
        key_points=key_points_text,
    )

    try:
        strategy_task = GeminiClient.generate_structured(
            strategy_prompt, schema=StrategyReport, thinking_level="medium"
        )
        concept_task = GeminiClient.generate_structured(
            concept_prompt, schema=ConceptMap, thinking_level="medium"
        )
        strategy_model, concept_model = await asyncio.gather(strategy_task, concept_task)
        strategy = strategy_model.model_dump(mode="json")
        concept_map = concept_model.model_dump(mode="json")
    except Exception as exc:
        return make_tool_error(exc)

    # Stage 4: Render artifacts to temp dir
    try:
        slug = sanitize_slug(analysis.get("title", content_id))
    except ValueError:
        slug = sanitize_slug(content_id) if content_id else f"video-{uuid.uuid4().hex[:8]}"

    output_dir = _resolve_output_dir(slug)
    tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=output_dir.parent))

    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        artifact_paths = render_artifacts(
            tmp_dir,
            analysis,
            strategy,
            concept_map,
            source_label=source_label,
            report_language=report_language,
        )

        # Stage 5: Quality gates
        quality_report = run_quality_gates(
            analysis,
            concept_map,
            tmp_dir,
            coverage_min_ratio=coverage_min_ratio,
            start_time=start_time,
            observation=MediaCoverage(
                source_id=content_id or source_label,
                missing_stages=[
                    "media_observation",
                    "claim_support",
                    "timestamp_verification",
                    "human_review",
                ],
            ),
        )

        if quality_report.status != "pass":
            logger.warning("Quality gates failed for %s: %s", content_id, quality_report.checks)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)
            return {
                "error": "Quality gates failed",
                "category": ErrorCategory.QUALITY_GATE_FAILED.value,
                "hint": "Review quality report for specific failures.",
                "retryable": True,
                "quality_report": quality_report.model_dump(mode="json"),
                "analysis": analysis,
            }

        (tmp_dir / "quality-report.json").write_text(
            json.dumps(quality_report.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )

        # Stage 6: Atomic rename on success
        # Remove the placeholder dir created by _resolve_output_dir so
        # shutil.move replaces it rather than nesting inside it.
        output_dir.rmdir()
        shutil.move(str(tmp_dir), str(output_dir))

        # Update paths to final location
        final_paths = {k: str(output_dir / Path(v).name) for k, v in artifact_paths.items()}

    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
        return make_tool_error(exc)

    return {
        "analysis": analysis,
        "strategy": strategy,
        "concept_map": concept_map,
        "artifacts": final_paths,
        "quality_report": quality_report.model_dump(mode="json"),
        "source": source_label,
        "content_id": content_id,
    }
