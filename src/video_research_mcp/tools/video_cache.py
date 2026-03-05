"""Cache bridge helpers for video tools — prewarm, lookup, and session caching."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.genai import types

from .. import context_cache
from ..config import get_config
from .video_url import is_youtube_url

logger = logging.getLogger(__name__)


def prewarm_cache(content_id: str, video_url: str) -> None:
    """Fire background cache prewarm for a video.

    Skips YouTube URLs — Gemini's caches.create() rejects them with
    400 INVALID_ARGUMENT. Only File API URIs work for context caching.

    Args:
        content_id: YouTube video ID or file hash.
        video_url: Video URI (YouTube URL or File API URI).
    """
    if is_youtube_url(video_url):
        logger.debug("Skipping cache prewarm for YouTube URL: %s", content_id)
        return
    from google.genai import types

    cfg = get_config()
    warm_parts = [types.Part(file_data=types.FileData(file_uri=video_url))]
    context_cache.start_prewarm(content_id, warm_parts, cfg.default_model)


async def resolve_session_cache(video_id: str) -> tuple[str, str]:
    """Look up pre-warmed cache for session creation.

    Args:
        video_id: YouTube video ID to look up.

    Returns:
        (cache_name, model) — both empty strings if no cache found.
    """
    try:
        cfg = get_config()
        cache_name = await context_cache.lookup_or_await(video_id, cfg.default_model) or ""
        if cache_name:
            return cache_name, cfg.default_model
    except Exception:
        pass
    return "", ""


async def ensure_session_cache(video_id: str, video_url: str) -> tuple[str, str, str]:
    """Look up or create context cache for session use.

    Unlike resolve_session_cache (lookup only), this function creates a cache
    on-demand if no pre-warmed cache exists. This makes cross-tool cache
    sharing reliable instead of depending on the fire-and-forget prewarm
    from video_analyze.

    Skips YouTube URLs — Gemini's caches.create() rejects them with
    400 INVALID_ARGUMENT. Only File API URIs work for context caching.

    Args:
        video_id: YouTube video ID or file hash.
        video_url: Video URI (YouTube URL or File API URI).

    Returns:
        (cache_name, model, reason) — cache_name and model are empty strings
        on failure; reason explains why (empty on success).
    """
    if is_youtube_url(video_url):
        logger.debug("Skipping cache creation for YouTube URL: %s", video_id)
        return "", "", "skipped:youtube_url"

    # Fast path: existing cache from prewarm or previous session
    cache_name, model = await resolve_session_cache(video_id)
    if cache_name:
        return cache_name, model, ""

    # Check for known-unrecoverable failure before slow path
    cfg = get_config()
    early_reason = context_cache.failure_reason(video_id, cfg.default_model)
    if early_reason.startswith("suppressed:"):
        return "", "", early_reason

    # Slow path: create/join cache via start_prewarm (deduplicates against
    # any concurrent prewarm task to avoid creating duplicate caches)
    try:
        from google.genai import types

        video_parts = [types.Part(file_data=types.FileData(file_uri=video_url))]
        task = context_cache.start_prewarm(video_id, video_parts, cfg.default_model)
        cache_name = await asyncio.wait_for(asyncio.shield(task), timeout=60.0) or ""
        if cache_name:
            logger.info("Created context cache on-demand for session: %s", video_id)
            return cache_name, cfg.default_model, ""
    except asyncio.TimeoutError:
        logger.debug("On-demand cache creation timed out for %s", video_id)
        return "", "", "timeout:60s"
    except Exception as exc:
        logger.debug("On-demand cache creation failed for %s", video_id, exc_info=True)
        return "", "", f"error:{type(exc).__name__}"

    # create returned None — check failure_reason for specifics
    reason = context_cache.failure_reason(video_id, cfg.default_model)
    return "", "", reason or "unknown"


async def prepare_cached_request(
    session, prompt: str
) -> tuple[bool, list[types.Content], dict]:
    """Prepare request contents and config for a cached/uncached session continuation.

    Checks cache TTL, builds user content (text-only when cached, video+text
    when uncached), and assembles the GenerateContentConfig kwargs.

    Args:
        session: The active VideoSession.
        prompt: User follow-up question.

    Returns:
        (use_cache, contents, config_kwargs) — ready for generate_content.
    """
    from google.genai import types

    use_cache = False
    if session.cache_name:
        cache_alive = await context_cache.refresh_ttl(session.cache_name)
        if cache_alive:
            use_cache = True
        else:
            session.cache_name = ""

    if use_cache:
        user_parts = [types.Part(text=prompt)]
    else:
        user_parts = [
            types.Part(file_data=types.FileData(file_uri=session.url)),
            types.Part(text=prompt),
        ]
    user_content = types.Content(role="user", parts=user_parts)
    contents = list(session.history) + [user_content]

    cfg = get_config()
    config_kwargs: dict = {
        "thinking_config": types.ThinkingConfig(thinking_level="medium"),
    }
    if use_cache:
        config_kwargs["cached_content"] = session.cache_name

    model = session.model if use_cache and session.model else cfg.default_model
    config_kwargs["_model"] = model  # passed through for caller convenience

    return use_cache, contents, config_kwargs
