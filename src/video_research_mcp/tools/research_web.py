"""Deep Research tools — Gemini Interactions API (4 tools on research_server).

Provides research_web (launch), research_web_status (poll/retrieve),
research_web_followup (conversational follow-up), and research_web_cancel
(abort running task) tools that wrap the Gemini Deep Research Agent for
autonomous web-grounded research.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import GeminiClient
from ..config import get_config
from ..errors import make_tool_error
from ..models.research_web import (
    DeepResearchFollowup,
    DeepResearchLaunch,
    DeepResearchResult,
    DeepResearchSource,
)
from ..tracing import trace
from .research import research_server

logger = logging.getLogger(__name__)

# In-memory tracker for launch metadata (interaction_id -> {time, topic})
_launch_times: dict[str, dict] = {}
_MAX_TRACKED = 100
_TTL_SECONDS = 7200  # 2 hours


_ACTIVE_TTL_SECONDS = 1800  # 30 min — max reasonable Deep Research runtime


def _evict_stale() -> None:
    """Remove launch entries older than TTL and cap total size."""
    now = time.time()
    stale = [k for k, v in _launch_times.items() if now - v["time"] > _TTL_SECONDS]
    for k in stale:
        _launch_times.pop(k, None)
    while len(_launch_times) > _MAX_TRACKED:
        oldest = min(_launch_times, key=lambda k: _launch_times[k]["time"])
        _launch_times.pop(oldest)


def _find_active_interaction() -> str | None:
    """Return interaction_id of a likely-active task, or None."""
    now = time.time()
    for iid, meta in _launch_times.items():
        if now - meta["time"] < _ACTIVE_TTL_SECONDS:
            return iid
    return None


def _extract_report(interaction) -> tuple[str, list[DeepResearchSource]]:
    """Extract report text and sources from Interaction outputs.

    Args:
        interaction: A google.genai Interaction object.

    Returns:
        Tuple of (report_text, sources_list).
    """
    report_parts: list[str] = []
    sources: list[DeepResearchSource] = []

    for turn in getattr(interaction, "outputs", []) or []:
        # Check direct text field (Deep Research format)
        direct_text = getattr(turn, "text", "")
        if direct_text:
            report_parts.append(direct_text)
        # Also check content array (standard Interactions format)
        for content in getattr(turn, "content", []) or []:
            content_type = getattr(content, "type", "")
            if content_type == "text":
                text = getattr(content, "text", "")
                if text:
                    report_parts.append(text)
            elif content_type == "googleSearchResult":
                result = getattr(content, "result", None)
                if result:
                    sources.append(DeepResearchSource(
                        url=getattr(result, "url", ""),
                        title=getattr(result, "title", ""),
                    ))
            elif content_type == "urlContextResult":
                result = getattr(content, "result", None)
                if result:
                    sources.append(DeepResearchSource(
                        url=getattr(result, "url", ""),
                        status=getattr(result, "status", ""),
                    ))

    return "\n\n".join(report_parts), sources


def _extract_usage(interaction) -> dict:
    """Extract token usage from Interaction.usage into a plain dict."""
    usage = getattr(interaction, "usage", None)
    if not usage:
        return {}
    return {
        "total_input_tokens": getattr(usage, "total_input_tokens", None),
        "total_output_tokens": getattr(usage, "total_output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "total_thought_tokens": getattr(usage, "total_thought_tokens", None),
    }


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
@trace(name="research_web", span_type="TOOL")
async def research_web(
    topic: Annotated[str, Field(
        min_length=10, max_length=10000,
        description="Precise research brief — the more detailed, the better results",
    )],
    output_format: Annotated[str, Field(
        description="Report structure/format instructions (e.g. 'executive summary + data tables')",
    )] = "",
) -> dict:
    """Launch a Gemini Deep Research Agent for autonomous web-grounded research.

    The agent plans its own research, searches the web (~80-160 queries),
    reads sources, and produces a cited markdown report. Runs in background;
    poll with research_web_status. Costs $2-5 per task, takes 10-20 minutes.

    Args:
        topic: Research brief — include specific questions, scope, hypotheses.
        output_format: Optional report structure instructions.

    Returns:
        Dict with interaction_id and status, or error via make_tool_error().
    """
    try:
        _evict_stale()

        # API allows only 1 concurrent Deep Research task per key
        active = _find_active_interaction()
        if active:
            return make_tool_error(RuntimeError(
                f"Deep Research task already in progress: {active}. "
                "Poll with research_web_status or cancel with research_web_cancel first."
            ))

        prompt = topic
        if output_format:
            prompt = f"{topic}\n\nOutput format:\n{output_format}"

        cfg = get_config()
        client = GeminiClient.get()

        interaction = await client.aio.interactions.create(
            input=prompt,
            agent=cfg.deep_research_agent,
            background=True,
        )

        interaction_id = interaction.id
        _launch_times[interaction_id] = {"time": time.time(), "topic": topic}
        logger.info("Deep Research launched: %s", interaction_id)

        return DeepResearchLaunch(
            interaction_id=interaction_id,
            status=getattr(interaction, "status", "in_progress") or "in_progress",
        ).model_dump(mode="json")

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_web_status", span_type="TOOL")
async def research_web_status(
    interaction_id: Annotated[str, Field(
        min_length=1,
        description="Interaction ID returned by research_web",
    )],
) -> dict:
    """Poll or retrieve a Deep Research task.

    Returns the full report with sources when completed, or current status
    if still in progress. Auto-stores completed reports to Weaviate.

    Args:
        interaction_id: The interaction ID from research_web.

    Returns:
        Dict with status and report (if completed), or error.
    """
    try:
        client = GeminiClient.get()

        # Retry on transient 403s (API occasionally returns 403 during polling)
        interaction = None
        for attempt in range(3):
            try:
                interaction = await client.aio.interactions.get(interaction_id)
                break
            except Exception as exc:
                if "403" in str(exc).lower() and attempt < 2:
                    logger.warning(
                        "Transient 403 on status poll (attempt %d/3), retrying...",
                        attempt + 1,
                    )
                    await asyncio.sleep(5 * (attempt + 1))
                else:
                    raise

        status = getattr(interaction, "status", "unknown") or "unknown"

        # Pop launch metadata on any non-transient status to prevent unbounded growth.
        # Only "in_progress" keeps the entry; terminal statuses (completed, failed,
        # cancelled, unknown) always clear it.
        if status != "in_progress":
            launch_meta = _launch_times.pop(interaction_id, None)
        else:
            launch_meta = _launch_times.get(interaction_id)

        if status != "completed":
            return {"interaction_id": interaction_id, "status": status}

        report_text, sources = _extract_report(interaction)
        usage = _extract_usage(interaction)

        launch_time = launch_meta.get("time") if launch_meta else None
        original_topic = launch_meta.get("topic", "") if launch_meta else ""
        duration = int(time.time() - launch_time) if launch_time else None

        result = DeepResearchResult(
            interaction_id=interaction_id,
            status="completed",
            topic=original_topic,
            report_text=report_text,
            sources=sources,
            source_count=len(sources),
            duration_seconds=duration,
            usage=usage,
        ).model_dump(mode="json")

        from ..weaviate_store import store_deep_research
        await store_deep_research(result)

        return result

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
@trace(name="research_web_followup", span_type="TOOL")
async def research_web_followup(
    interaction_id: Annotated[str, Field(
        min_length=1,
        description="Completed interaction ID to follow up on",
    )],
    question: Annotated[str, Field(
        min_length=3, max_length=5000,
        description="Follow-up question about the research report",
    )],
) -> dict:
    """Ask a follow-up question about a completed Deep Research report.

    Uses previous_interaction_id to maintain context from the original
    research. Synchronous — follow-ups are fast (no background needed).

    Args:
        interaction_id: The completed interaction ID.
        question: Follow-up question.

    Returns:
        Dict with new interaction_id, previous_interaction_id, and response.
    """
    try:
        cfg = get_config()
        client = GeminiClient.get()

        followup = await client.aio.interactions.create(
            input=question,
            model=cfg.default_model,
            previous_interaction_id=interaction_id,
        )

        response_text = ""
        for turn in getattr(followup, "outputs", []) or []:
            for content in getattr(turn, "content", []) or []:
                if getattr(content, "type", "") == "text":
                    text = getattr(content, "text", "")
                    if text:
                        response_text += text + "\n"

        result = DeepResearchFollowup(
            interaction_id=followup.id,
            previous_interaction_id=interaction_id,
            response=response_text.strip(),
        ).model_dump(mode="json")

        from ..weaviate_store import store_deep_research_followup
        await store_deep_research_followup(
            interaction_id, followup.id,
            question=question, response=response_text.strip(),
        )

        return result

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
@trace(name="research_web_cancel", span_type="TOOL")
async def research_web_cancel(
    interaction_id: Annotated[str, Field(
        min_length=1,
        description="Interaction ID to cancel",
    )],
) -> dict:
    """Cancel a running Deep Research task.

    Sends a cancel request to the Interactions API and cleans up local
    tracking state. Useful for aborting expensive ($2-5) tasks early.

    Args:
        interaction_id: The interaction ID from research_web.

    Returns:
        Dict with interaction_id and status, or error via make_tool_error().
    """
    try:
        client = GeminiClient.get()
        await client.aio.interactions.cancel(interaction_id)
        _launch_times.pop(interaction_id, None)
        logger.info("Deep Research cancelled: %s", interaction_id)
        return {"interaction_id": interaction_id, "status": "cancelled"}
    except Exception as exc:
        return make_tool_error(exc)
