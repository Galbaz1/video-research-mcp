"""Shared video analysis with complete deterministic cache contracts."""

from __future__ import annotations

import hashlib
import json
import os

from google.genai import types

from ..cache import invalidate_source, load as cache_load, save as cache_save
from ..client import GeminiClient, _resolve_thinking_level
from ..config import get_config, supports_sampling, validate_model_thinking
from ..media_identity import SourceIdentity, identify_source
from ..models.video import VideoResult

_ANALYSIS_PREAMBLE = (
    "Analyze this video thoroughly. For timestamps, use PRECISE times from the "
    "actual video (not rounded estimates). Extract AT LEAST 5-10 key points. "
    "Include specific details, quotes, or data mentioned in the video. "
    "For each timestamp, describe what is happening at that exact moment."
)


def _enrich_prompt(contents: types.Content, new_text: str) -> types.Content:
    """Replace text parts while preserving the prepared media parts."""
    return types.Content(
        parts=[types.Part(text=new_text) if part.text else part for part in contents.parts]
    )


def _json_identity(value):
    """Represent opaque bytes by exact SHA256 instead of embedding source payloads."""
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "byte_length": len(value)}
    if isinstance(value, dict):
        return {key: _json_identity(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_identity(child) for child in value]
    return value


def _request_contract(
    contents: types.Content,
    source: SourceIdentity,
    cfg,
    instruction: str,
    schema: dict,
    thinking: str,
    metadata: str | None,
) -> dict:
    """Freeze actual provider, credential scope and prepared request semantics."""
    preprocessing, window = [], []
    for part in contents.parts:
        data = part.model_dump(mode="python", exclude_none=True)
        if "file_data" in data and source.state == "fresh":
            data["file_data"].pop("file_uri", None)
        preprocessing.append(_json_identity(data))
        if part.video_metadata is not None:
            window.append(part.video_metadata.model_dump(mode="json", exclude_none=True))
    credential = cfg.gemini_api_key or os.getenv("GEMINI_API_KEY", "")
    sampling = (
        {"temperature": cfg.default_temperature} if supports_sampling(cfg.default_model) else {}
    )
    return {
        "source_digest": source.digest,
        "source_revision": source.revision,
        "provider": types.__name__.removesuffix(".types"),
        "account_scope": "credential-sha256:" + hashlib.sha256(credential.encode()).hexdigest(),
        "model": cfg.default_model,
        "tool_name": "video_analyze",
        "output_schema": schema,
        "thinking_level": thinking,
        "prompt": {"instruction": instruction, "role": contents.role},
        "metadata": metadata,
        "preprocessing": preprocessing,
        "window": window,
        "sampling": sampling,
        "retrieval_revision": None,
    }


def _check_prepared_media(contents: types.Content, source: SourceIdentity) -> SourceIdentity:
    """Bind inline original bytes; an opaque URI cannot prove immutable upload identity."""
    has_inline = False
    if source.state == "fresh":
        for part in contents.parts:
            if part.inline_data is not None and part.inline_data.data is not None:
                has_inline = True
                if hashlib.sha256(part.inline_data.data).hexdigest() != source.digest:
                    raise ValueError("Prepared video bytes changed from the original source")
        if not has_inline or any(part.file_data is not None for part in contents.parts):
            return SourceIdentity(alias=source.alias, aliases=source.aliases)
    return source


async def _generate_result(
    contents: types.Content, schema: dict | None, cfg, thinking: str
) -> dict:
    """Use the existing client with the frozen effective model/sampling settings."""
    options = {"model": cfg.default_model, "thinking_level": thinking}
    if supports_sampling(cfg.default_model):
        options["temperature"] = cfg.default_temperature
    if schema:
        raw = await GeminiClient.generate(contents, response_schema=schema, **options)
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Gemini returned non-JSON for custom schema: {raw[:200]!r}"
            ) from error
        if not isinstance(result, dict):
            raise ValueError("Custom video schema must return a JSON object")
        return result
    result = await GeminiClient.generate_structured(contents, schema=VideoResult, **options)
    return result.model_dump(mode="json")


async def _optional_storage(
    result: dict,
    content_id: str,
    instruction: str,
    source_label: str,
    local_filepath: str,
    screenshot_dir: str,
) -> None:
    """Bounded comparison calls omit optional external enrichment and writes."""
    from ..execution_budget import current_budget
    from ..weaviate_store import extract_and_store_graph, store_video_analysis

    if current_budget() is None:
        await store_video_analysis(
            result,
            content_id,
            instruction,
            source_label,
            local_filepath=local_filepath,
            screenshot_dir=screenshot_dir,
        )
        await extract_and_store_graph(
            result, source_label, source_tool="video_analyze", source_category="video"
        )


def _cache_options(content_id, model, instruction, contract, source) -> dict:
    """Use exactly the same frozen binding for cache reads and writes."""
    return {
        "content_id": content_id,
        "tool_name": "video_analyze",
        "model": model,
        "instruction": instruction,
        "contract": contract,
        "source": source,
    }


def _bind_source_metadata(result: dict, source: SourceIdentity, label: str) -> dict:
    """Overwrite model fields with local prepared commitments or explicit unknown."""
    fresh = source.state == "fresh"
    result.update(
        source=label,
        source_sha256=source.digest if fresh else None,
        source_revision=source.revision if fresh else None,
        source_freshness=source.state,
    )
    return result


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
    """Analyze using exact fresh contracts; comparison bypass avoids cache I/O.

    Args:
        contents: Prepared original video parts and prompt.
        instruction: User instruction preserved in request identity.
        content_id: Complete prepared SHA256 for local bytes; URL IDs remain unknown.
        source_label: Current caller label, relabeled safely on a same-byte alias hit.
        output_schema: Optional existing custom response schema.
        thinking_level: Effective provider thinking depth.
        use_cache: Whether to read/write result and identity cache metadata.
        metadata_context: Original metadata text included in request identity.
        local_filepath: Original local bytes to recheck before reuse and after inference.
        screenshot_dir: Existing optional storage field.

    Returns:
        Existing VideoResult/custom dictionary; cached responses retain current labels.
    """
    cfg = get_config()
    thinking = _resolve_thinking_level(thinking_level)
    validate_model_thinking(cfg.default_model, thinking)
    source = identify_source(
        local_filepath or source_label, expected_digest=content_id, persist=use_cache
    )
    if source.state in {"stale", "deleted"}:
        raise ValueError("Original video source changed or was deleted after preparation")
    source = _check_prepared_media(contents, source)
    if not output_schema:
        prefix = _ANALYSIS_PREAMBLE + ("\n\n" + metadata_context if metadata_context else "")
        contents = _enrich_prompt(contents, prefix + "\n\nUser instruction: " + instruction)
    schema = output_schema or VideoResult.model_json_schema()
    contract = _request_contract(
        contents, source, cfg, instruction, schema, thinking, metadata_context
    )
    cache_options = _cache_options(content_id, cfg.default_model, instruction, contract, source)
    if use_cache and source.state == "fresh":
        cached = cache_load(**cache_options)
        if cached is not None:
            cached["cached"] = True
            return _bind_source_metadata(cached, source, source_label)
    result = await _generate_result(contents, output_schema, cfg, thinking)
    if source.state == "fresh":
        current = identify_source(source.alias, expected_digest=source.digest, persist=False)
        if current.state != "fresh":
            if use_cache:
                invalidate_source(source.digest)
            raise ValueError("Original video source changed during analysis")
    _bind_source_metadata(result, source, source_label)
    if use_cache and source.state == "fresh":
        cache_save(analysis=result, **cache_options)
    await _optional_storage(
        result, content_id, instruction, source_label, local_filepath, screenshot_dir
    )
    return result
