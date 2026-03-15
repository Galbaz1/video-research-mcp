"""Research tools — 3 tools on a FastMCP sub-server."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import GeminiClient
from ..tracing import trace
from ..errors import make_tool_error
from ..models.research import (
    EvidenceAssessment,
    FindingsContainer,
    Phase,
    ResearchPlan,
    ResearchReport,
    ResearchSynthesis,
)
from ..prompts.research import (
    DEEP_RESEARCH_SYSTEM,
    EVIDENCE_ASSESSMENT,
    EVIDENCE_COLLECTION,
    RESEARCH_PLAN,
    SCOPE_DEFINITION,
    SYNTHESIS,
)
from ..types import Scope, ThinkingLevel, TopicParam, coerce_string_list_param

logger = logging.getLogger(__name__)
research_server = FastMCP("research")


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_deep", span_type="TOOL")
async def research_deep(
    topic: TopicParam,
    scope: Scope = "moderate",
    thinking_level: ThinkingLevel = "high",
) -> dict:
    """Run multi-phase deep research with evidence-tier labeling.

    Phases: Scope Definition -> Evidence Collection -> Synthesis.
    Every claim is labeled CONFIRMED, STRONG INDICATOR, INFERENCE,
    SPECULATION, or UNKNOWN.

    Args:
        topic: Research question or subject area.
        scope: Research depth — "quick", "moderate", "deep", or "comprehensive".
        thinking_level: Gemini thinking depth.

    Returns:
        Dict with topic, scope, executive_summary, findings, open_questions.
    """
    try:
        # Phase 1: Scope (unstructured — produces context text)
        scope_prompt = SCOPE_DEFINITION.format(topic=topic, scope=scope)
        scope_text = await GeminiClient.generate(
            scope_prompt,
            system_instruction=DEEP_RESEARCH_SYSTEM,
            thinking_level=thinking_level,
        )

        # Phase 2: Evidence collection (structured)
        evidence_prompt = EVIDENCE_COLLECTION.format(topic=topic, context=scope_text)
        findings_result = await GeminiClient.generate_structured(
            evidence_prompt,
            schema=FindingsContainer,
            system_instruction=DEEP_RESEARCH_SYSTEM,
            thinking_level=thinking_level,
        )
        findings = findings_result.findings

        # Phase 3: Synthesis (structured)
        findings_text = (
            "\n".join(f"- [{f.evidence_tier}] {f.claim}" for f in findings)
            or scope_text
        )
        synth_prompt = SYNTHESIS.format(topic=topic, findings_text=findings_text)
        synthesis = await GeminiClient.generate_structured(
            synth_prompt,
            schema=ResearchSynthesis,
            system_instruction=DEEP_RESEARCH_SYSTEM,
            thinking_level=thinking_level,
        )

        report = ResearchReport(
            topic=topic,
            scope=scope,
            executive_summary=synthesis.executive_summary,
            findings=findings,
            open_questions=synthesis.open_questions,
            methodology_critique=synthesis.methodology_critique,
        ).model_dump(mode="json")
        from ..weaviate_store import store_research_finding
        await store_research_finding(report)
        return report

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_plan", span_type="TOOL")
async def research_plan(
    topic: TopicParam,
    scope: Scope = "moderate",
    available_agents: Annotated[int, Field(ge=1, le=50, description="Number of agents available")] = 10,
) -> dict:
    """Generate a multi-agent research orchestration plan.

    Returns a phased blueprint with task decomposition and model assignments.
    Does NOT spawn agents — provides the blueprint for the caller.

    Args:
        topic: Research question or subject area.
        scope: Research depth.
        available_agents: Number of agents the caller can deploy (1-50).

    Returns:
        Dict with topic, scope, phases, and task_decomposition.
    """
    try:
        prompt = RESEARCH_PLAN.format(
            topic=topic, scope=scope, available_agents=available_agents
        )
        plan = await GeminiClient.generate_structured(
            prompt,
            schema=ResearchPlan,
            system_instruction=DEEP_RESEARCH_SYSTEM,
            thinking_level="high",
        )
        result = plan.model_dump(mode="json")
        from ..weaviate_store import store_research_plan
        await store_research_plan(result)
        return result

    except Exception as exc:
        # Fallback: unstructured generate for minimal plan
        try:
            raw = await GeminiClient.generate(
                prompt,
                system_instruction=DEEP_RESEARCH_SYSTEM,
                thinking_level="high",
            )
            fallback = ResearchPlan(
                topic=topic,
                scope=scope,
                phases=[Phase(name="Full Plan", description=raw[:2000], tasks=[])],
                task_decomposition=[raw],
            ).model_dump(mode="json")
            from ..weaviate_store import store_research_plan
            await store_research_plan(fallback)
            return fallback
        except Exception:
            return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_assess_evidence", span_type="TOOL")
async def research_assess_evidence(
    claim: Annotated[str, Field(min_length=3, description="The claim to assess")],
    sources: Annotated[list[str], Field(min_length=1, description="Evidence sources to evaluate against")],
    context: Annotated[str, Field(description="Additional context for assessment")] = "",
) -> dict:
    """Assess a claim against sources, returning evidence tier and confidence.

    Args:
        claim: Statement to verify.
        sources: List of evidence sources.
        context: Optional background for the assessment.

    Returns:
        Dict with claim, tier, confidence, and reasoning.
    """
    try:
        sources = coerce_string_list_param(
            sources,
            param_name="sources",
            allow_empty=False,
        )
    except ValueError as exc:
        return make_tool_error(exc)

    try:
        sources_text = "\n".join(f"- {s}" for s in sources)
        prompt = EVIDENCE_ASSESSMENT.format(
            claim=claim, sources_text=sources_text, context=context
        )
        assessment = await GeminiClient.generate_structured(
            prompt,
            schema=EvidenceAssessment,
            system_instruction=DEEP_RESEARCH_SYSTEM,
            thinking_level="high",
        )
        result = assessment.model_dump(mode="json")
        from ..weaviate_store import store_evidence_assessment
        await store_evidence_assessment(result)
        return result

    except Exception as exc:
        return make_tool_error(exc)



def _ensure_document_tool() -> None:
    """Import research_document to register its tool on research_server.

    Deferred to avoid circular import -- research_document imports from this module.
    Called by server.py after research_server is fully initialised.
    """
    from . import research_document  # noqa: F401
