"""Tests for research tools — structured output."""

from __future__ import annotations

import pytest

from video_research_mcp.models.research import (
    EvidenceAssessment,
    Finding,
    FindingsContainer,
    Phase,
    ResearchPlan,
    ResearchSynthesis,
)
from video_research_mcp.tools.research import (
    research_assess_evidence,
    research_deep,
    research_plan,
)


class TestResearchDeep:
    @pytest.mark.asyncio
    async def test_research_deep_returns_report(self, mock_gemini_client):
        """research_deep uses generate() for scope, generate_structured() for findings+synthesis."""
        # Phase 1: scope (unstructured)
        mock_gemini_client["generate"].return_value = "Scope: AI safety is a broad field..."

        # Phase 2 & 3: structured
        findings = FindingsContainer(
            findings=[
                Finding(claim="AI risk is real", evidence_tier="CONFIRMED", supporting=["Source A"]),
                Finding(claim="Timelines uncertain", evidence_tier="INFERENCE"),
            ]
        )
        synthesis = ResearchSynthesis(
            executive_summary="AI safety is a critical concern",
            open_questions=["What about alignment?"],
            methodology_critique="Good coverage",
            recommendations=["Invest in alignment research"],
        )
        mock_gemini_client["generate_structured"].side_effect = [findings, synthesis]

        result = await research_deep("AI safety", scope="moderate")

        assert result["topic"] == "AI safety"
        assert result["scope"] == "moderate"
        assert result["executive_summary"] == "AI safety is a critical concern"
        assert len(result["findings"]) == 2
        assert result["findings"][0]["claim"] == "AI risk is real"
        assert result["findings"][0]["evidence_tier"] == "CONFIRMED"
        assert result["findings"][1]["evidence_tier"] == "INFERENCE"
        assert result["open_questions"] == ["What about alignment?"]
        assert result["methodology_critique"] == "Good coverage"

        # Verify call count: 1 generate (scope) + 2 generate_structured (findings, synthesis)
        assert mock_gemini_client["generate"].call_count == 1
        assert mock_gemini_client["generate_structured"].call_count == 2

    @pytest.mark.asyncio
    async def test_research_deep_empty_findings_uses_scope_text(self, mock_gemini_client):
        """GIVEN no findings WHEN building synthesis prompt THEN scope_text is used as fallback."""
        mock_gemini_client["generate"].return_value = "Scope text for fallback"
        mock_gemini_client["generate_structured"].side_effect = [
            FindingsContainer(findings=[]),
            ResearchSynthesis(
                executive_summary="Summary from scope fallback",
                open_questions=[],
            ),
        ]

        result = await research_deep("empty topic")

        assert result["executive_summary"] == "Summary from scope fallback"
        assert result["findings"] == []

    @pytest.mark.asyncio
    async def test_research_deep_error_returns_tool_error(self, mock_gemini_client):
        """research_deep returns tool error on exception."""
        mock_gemini_client["generate"].side_effect = RuntimeError("API down")

        result = await research_deep("test topic")

        assert "error" in result
        assert "API down" in result["error"]


class TestResearchPlan:
    @pytest.mark.asyncio
    async def test_research_plan_structured(self, mock_gemini_client):
        """research_plan uses generate_structured as primary approach."""
        mock_gemini_client["generate_structured"].return_value = ResearchPlan(
            topic="Quantum ML",
            scope="moderate",
            phases=[
                Phase(
                    name="Scan",
                    description="Scan papers",
                    tasks=["Find papers"],
                    recommended_model="haiku",
                ),
            ],
            task_decomposition=["Scan literature", "Analyze methods"],
        )

        result = await research_plan("Quantum ML")

        assert result["topic"] == "Quantum ML"
        assert len(result["phases"]) == 1
        assert result["phases"][0]["name"] == "Scan"
        assert result["task_decomposition"] == ["Scan literature", "Analyze methods"]
        mock_gemini_client["generate_structured"].assert_called_once()

    @pytest.mark.asyncio
    async def test_research_plan_fallback_on_structured_failure(self, mock_gemini_client):
        """research_plan falls back to generate() if generate_structured() fails."""
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("Schema mismatch")
        mock_gemini_client["generate"].return_value = "Phase 1: Do scanning. Phase 2: Analyze."

        result = await research_plan("Test topic")

        assert result["topic"] == "Test topic"
        assert len(result["phases"]) == 1
        assert result["phases"][0]["name"] == "Full Plan"
        assert "Phase 1: Do scanning" in result["phases"][0]["description"]

    @pytest.mark.asyncio
    async def test_research_plan_both_fail_returns_error(self, mock_gemini_client):
        """GIVEN both structured and fallback fail THEN tool error is returned."""
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("Structured fail")
        mock_gemini_client["generate"].side_effect = RuntimeError("Generate fail")

        result = await research_plan("broken topic")

        assert "error" in result


    async def test_research_plan_fallback_preserves_long_text(self, mock_gemini_client):
        """GIVEN structured generation fails WHEN fallback THEN description preserves up to 2000 chars."""
        long_text = "A" * 2500
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("Schema fail")
        mock_gemini_client["generate"].return_value = long_text

        result = await research_plan("test topic")

        # Fallback should truncate at 2000, not 500
        desc = result["phases"][0]["description"]
        assert len(desc) == 2000
        assert result["task_decomposition"][0] == long_text  # full text preserved

    def test_topic_param_accepts_long_topics(self):
        """TopicParam max_length=2000 allows detailed research questions."""
        from video_research_mcp.types import TopicParam
        from pydantic import TypeAdapter

        adapter = TypeAdapter(TopicParam)
        long_topic = "A" * 1500
        result = adapter.validate_python(long_topic)
        assert result == long_topic


class TestResearchAssessEvidence:
    @pytest.mark.asyncio
    async def test_assess_evidence_structured(self, mock_gemini_client):
        """research_assess_evidence uses generate_structured."""
        mock_gemini_client["generate_structured"].return_value = EvidenceAssessment(
            claim="Earth is round",
            tier="CONFIRMED",
            confidence=0.99,
            supporting=["Satellite imagery"],
            reasoning="Overwhelming evidence",
        )

        result = await research_assess_evidence(
            claim="Earth is round",
            sources=["NASA satellite data"],
        )

        assert result["tier"] == "CONFIRMED"
        assert result["confidence"] == 0.99
        assert result["supporting"] == ["Satellite imagery"]
        assert result["reasoning"] == "Overwhelming evidence"
        mock_gemini_client["generate_structured"].assert_called_once()

    @pytest.mark.asyncio
    async def test_assess_evidence_with_context(self, mock_gemini_client):
        """GIVEN context is provided THEN it is passed to the prompt."""
        mock_gemini_client["generate_structured"].return_value = EvidenceAssessment(
            claim="Claim X",
            tier="INFERENCE",
            confidence=0.6,
            reasoning="Based on context",
        )

        result = await research_assess_evidence(
            claim="Claim X",
            sources=["Source 1"],
            context="Extra background info",
        )

        assert result["tier"] == "INFERENCE"
        # Verify prompt includes context
        call_args = mock_gemini_client["generate_structured"].call_args
        assert "Extra background info" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_assess_evidence_error(self, mock_gemini_client):
        """research_assess_evidence returns tool error on exception."""
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("fail")

        result = await research_assess_evidence(
            claim="test claim",
            sources=["source"],
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_assess_evidence_rejects_non_list_sources(self, mock_gemini_client):
        """GIVEN sources is a plain string WHEN calling THEN validation error is returned."""
        result = await research_assess_evidence(
            claim="test claim",
            sources="single-source",
        )
        assert "error" in result
        assert "list of strings" in result["error"]
