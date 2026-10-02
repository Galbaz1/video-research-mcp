"""Deep Research tools — Gemini Interactions API (4 tools on research_server).

Provides research_web (launch), research_web_status (poll/retrieve),
research_web_followup (conversational follow-up), and research_web_cancel
(abort running task) tools that wrap the Gemini Deep Research Agent for
autonomous web-grounded research.
"""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..models.research_web import (
    DeepResearchSource,
)
from ..tracing import trace
from .research import research_server

logger = logging.getLogger(__name__)


def _extract_report(interaction) -> tuple[str, list[DeepResearchSource]]:
    """Extract trailing model output text and unique sources from current SDK steps.

    Args:
        interaction: A google.genai Interaction object.

    Returns:
        Tuple of (report_text, sources_list).
    """
    sources: dict[str, DeepResearchSource] = {}

    for step in interaction.steps or []:
        if step.type == "model_output":
            for content in step.content or []:
                if content.type != "text":
                    continue
                for annotation in content.annotations or []:
                    if annotation.type == "url_citation" and annotation.url:
                        sources[annotation.url] = DeepResearchSource(
                            url=annotation.url,
                            title=annotation.title or "",
                        )
        elif step.type in {"google_search_result", "url_context_result"}:
            for result in step.result or []:
                url = getattr(result, "url", "")
                if url:
                    sources.setdefault(
                        url,
                        DeepResearchSource(
                            url=url,
                            title=getattr(result, "title", "") or "",
                            status=getattr(result, "status", "") or "",
                        ),
                    )

    return interaction.output_text or "", list(sources.values())


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
    topic: Annotated[
        str,
        Field(
            min_length=10,
            max_length=10000,
            description="Precise research brief — the more detailed, the better results",
        ),
    ],
    output_format: Annotated[
        str,
        Field(
            description="Report structure/format instructions (e.g. 'executive summary + data tables')",
        ),
    ] = "",
    job_id: Annotated[
        str | None, Field(description="Resume a recorded launch without resubmitting provider work")
    ] = None,
) -> dict:
    """Launch a Gemini Deep Research Agent for autonomous web-grounded research.

    The agent plans its own research, searches the web (~80-160 queries),
    reads sources, and produces a cited markdown report. Runs in background;
    poll with research_web_status. Provider usage is billed; runtime varies.

    Args:
        topic: Research brief — include specific questions, scope, hypotheses.
        output_format: Optional report structure instructions.
        job_id: Optional stable identity for recovering a prior launch.

    Returns:
        Dict with interaction_id and status, or error via make_tool_error().
    """
    from ..research_operations import launch

    return await launch(topic, output_format, job_id)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_web_status", span_type="TOOL")
async def research_web_status(
    interaction_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Interaction ID returned by research_web",
        ),
    ],
) -> dict:
    """Poll or retrieve a Deep Research task.

    Returns the full report with sources when completed, or current status
    if still in progress. Auto-stores completed reports to Weaviate.

    Args:
        interaction_id: The interaction ID from research_web.

    Returns:
        Dict with status and report (if completed), or error.
    """
    from ..research_operations import poll

    return await poll(interaction_id)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
@trace(name="research_web_followup", span_type="TOOL")
async def research_web_followup(
    interaction_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Completed interaction ID to follow up on",
        ),
    ],
    question: Annotated[
        str,
        Field(
            min_length=3,
            max_length=5000,
            description="Follow-up question about the research report",
        ),
    ],
    job_id: Annotated[
        str | None, Field(description="Resume a recorded follow-up without repeating inference")
    ] = None,
) -> dict:
    """Ask a follow-up question about a completed Deep Research report.

    Uses previous_interaction_id to maintain context from the original
    research. Synchronous — follow-ups are fast (no background needed).

    Args:
        interaction_id: The completed interaction ID.
        question: Follow-up question.
        job_id: Optional stable identity for recovering a prior follow-up.

    Returns:
        Dict with new interaction_id, previous_interaction_id, and response.
    """
    from ..research_operations import followup

    return await followup(interaction_id, question, job_id)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
@trace(name="research_web_cancel", span_type="TOOL")
async def research_web_cancel(
    interaction_id: Annotated[
        str,
        Field(
            min_length=1,
            description="Interaction ID to cancel",
        ),
    ],
) -> dict:
    """Cancel a running Deep Research task.

    Sends a cancel request to the Interactions API and cleans up local
    tracking state. Useful for stopping a task before further provider usage.

    Args:
        interaction_id: The interaction ID from research_web.

    Returns:
        Dict with interaction_id and status, or error via make_tool_error().
    """
    from ..research_operations import cancel

    return await cancel(interaction_id)
