"""Shared video analysis pipeline — cache check, Gemini call, cache save."""

from __future__ import annotations

import json
import logging

from google.genai import types

from ..cache import load as cache_load, save as cache_save
from ..client import GeminiClient
from ..config import get_config
from ..models.video import VideoResult

logger = logging.getLogger(__name__)

_ANALYSIS_PREAMBLE = (
    "Analyze this video thoroughly. For timestamps, use PRECISE times from the "
    "actual video (not rounded estimates). Extract AT LEAST 5-10 key points. "
    "Include specific details, quotes, or data mentioned in the video. "
    "For each timestamp, describe what is happening at that exact moment."
)


def _enrich_prompt(contents: types.Content, new_text: str) -> types.Content:
    """Return a new Content with every text part replaced by ``new_text``.

    Non-text parts (e.g. file data) are preserved as-is.
    """
    new_parts = []
    for part in contents.parts:
        if part.text:
            new_parts.append(types.Part(text=new_text))
        else:
            new_parts.append(part)
    return types.Content(parts=new_parts)


async def analyze_video(
    contents: types.Content,
    *,
    instruction: str,
    content_id: str,
    source_label: str,
    output_schema: dict | None = None,
    thinking_level: str = "high",
    use_cache: bool = True,
    metadata_context: str | None = None,
    local_filepath: str = "",
    screenshot_dir: str = "",
) -> dict:
    """Run the video analysis pipeline shared by video_analyze and video_batch_analyze.

    Args:
        contents: Gemini Content with video part + text prompt.
        instruction: The analysis instruction (used for cache keying).
        content_id: Unique ID for caching (video_id or file hash).
        source_label: Human-readable source (URL or file path) added to result.
        output_schema: Optional custom JSON Schema for the response.
        thinking_level: Gemini thinking depth.
        use_cache: Whether to check/save cache.
        metadata_context: Optional video metadata context to prepend to the prompt.
        local_filepath: Local filesystem path to the analyzed/downloaded video.
        screenshot_dir: Local filesystem path to extracted screenshots.

    Returns:
        Dict matching VideoResult schema (default) or the custom output_schema.
    """
    cfg = get_config()

    if use_cache:
        cached = cache_load(content_id, "video_analyze", cfg.default_model, instruction=instruction)
        if cached:
            cached["cached"] = True
            return cached

    if output_schema:
        raw = await GeminiClient.generate(
            contents,
            thinking_level=thinking_level,
            response_schema=output_schema,
        )
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Gemini returned non-JSON for custom schema: {raw[:200]!r}"
            ) from exc
    else:
        if metadata_context:
            enriched = (
                f"{_ANALYSIS_PREAMBLE}\n\n{metadata_context}\n\n"
                f"User instruction: {instruction}"
            )
        else:
            enriched = f"{_ANALYSIS_PREAMBLE}\n\nUser instruction: {instruction}"
        contents = _enrich_prompt(contents, enriched)
        model_result = await GeminiClient.generate_structured(
            contents,
            schema=VideoResult,
            thinking_level=thinking_level,
        )
        result = model_result.model_dump(mode="json")

    result["source"] = source_label
    if use_cache:
        cache_save(content_id, "video_analyze", cfg.default_model, result, instruction=instruction)
    from ..weaviate_store import store_video_analysis, extract_and_store_graph
    await store_video_analysis(
        result,
        content_id,
        instruction,
        source_label,
        local_filepath=local_filepath,
        screenshot_dir=screenshot_dir,
    )
    await extract_and_store_graph(
        result, source_label, source_tool="video_analyze", source_category="video",
    )
    return result
