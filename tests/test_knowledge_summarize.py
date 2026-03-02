"""Tests for Flash post-processor (summarize_hits)."""

from __future__ import annotations

from video_research_mcp.models.knowledge import (
    HitSummary,
    HitSummaryBatch,
    KnowledgeHit,
)
from video_research_mcp.prompts.knowledge import KNOWLEDGE_SUMMARIZE_SYSTEM
from video_research_mcp.tools.knowledge.summarize import summarize_hits
from tests.adversarial_inputs import (
    ADVERSARIAL_PROMPT_INJECTION,
    ADVERSARIAL_TOOL_MISUSE,
)


def _make_hit(object_id: str, collection: str = "VideoAnalyses", **props) -> KnowledgeHit:
    return KnowledgeHit(
        collection=collection,
        object_id=object_id,
        score=0.5,
        properties=props,
    )


class TestSummarizeHits:
    """Tests for summarize_hits Flash post-processor."""

    async def test_enriches_hits_with_summary(self, mock_gemini_client):
        """GIVEN Flash returns summaries WHEN summarize_hits THEN hits get summary field."""
        hits = [_make_hit("uuid-1", title="AI Research", abstract="Long text")]
        mock_gemini_client["generate_structured"].return_value = HitSummaryBatch(
            summaries=[HitSummary(
                object_id="uuid-1",
                relevance=0.9,
                summary="Relevant AI research paper",
                useful_properties=["title", "abstract"],
            )],
        )

        result = await summarize_hits(hits, "AI")

        assert len(result) == 1
        assert result[0].summary == "Relevant AI research paper"

    async def test_trims_properties_to_useful(self, mock_gemini_client):
        """GIVEN Flash identifies useful_properties WHEN summarize_hits THEN extra props removed."""
        hits = [_make_hit("uuid-1", title="Keep", extra="Remove", other="Also remove")]
        mock_gemini_client["generate_structured"].return_value = HitSummaryBatch(
            summaries=[HitSummary(
                object_id="uuid-1",
                relevance=0.8,
                summary="Summary",
                useful_properties=["title"],
            )],
        )

        result = await summarize_hits(hits, "test")

        assert "title" in result[0].properties
        assert "extra" not in result[0].properties
        assert "other" not in result[0].properties

    async def test_fallback_on_error(self, mock_gemini_client):
        """GIVEN Flash raises WHEN summarize_hits THEN returns raw hits unchanged."""
        hits = [_make_hit("uuid-1", title="Original")]
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("Flash failed")

        result = await summarize_hits(hits, "test")

        assert len(result) == 1
        assert result[0].summary is None
        assert result[0].properties["title"] == "Original"

    async def test_skips_empty_hits(self, mock_gemini_client):
        """GIVEN empty list WHEN summarize_hits THEN returns empty, no Flash call."""
        result = await summarize_hits([], "test")

        assert result == []
        mock_gemini_client["generate_structured"].assert_not_called()

    async def test_caps_batch_size(self, mock_gemini_client):
        """GIVEN 120 hits WHEN summarize_hits THEN prompt only contains first 100."""
        hits = [_make_hit(f"uuid-{i}", title=f"Hit {i}") for i in range(120)]
        mock_gemini_client["generate_structured"].return_value = HitSummaryBatch(summaries=[])

        await summarize_hits(hits, "test")

        call_args = mock_gemini_client["generate_structured"].call_args
        prompt = call_args[0][0]  # first positional arg (contents)
        # Should contain Hit 0 through Hit 99 but not Hit 100+
        assert "uuid-99" in prompt
        assert "uuid-100" not in prompt

    async def test_preserves_all_props_when_useful_empty(self, mock_gemini_client):
        """GIVEN Flash returns empty useful_properties WHEN summarize_hits THEN all props kept."""
        hits = [_make_hit("uuid-1", title="Keep", extra="Also keep")]
        mock_gemini_client["generate_structured"].return_value = HitSummaryBatch(
            summaries=[HitSummary(
                object_id="uuid-1",
                relevance=0.5,
                summary="Summary",
                useful_properties=[],
            )],
        )

        result = await summarize_hits(hits, "test")

        # Falls back to all properties when useful_properties is empty
        assert "title" in result[0].properties
        assert "extra" in result[0].properties

    async def test_unmatched_hits_pass_through(self, mock_gemini_client):
        """GIVEN Flash returns no summary for a hit WHEN summarize_hits THEN hit unchanged."""
        hits = [_make_hit("uuid-1", title="A"), _make_hit("uuid-2", title="B")]
        mock_gemini_client["generate_structured"].return_value = HitSummaryBatch(
            summaries=[HitSummary(
                object_id="uuid-1",
                relevance=0.9,
                summary="Summary for A",
                useful_properties=["title"],
            )],
        )

        result = await summarize_hits(hits, "test")

        assert result[0].summary == "Summary for A"
        assert result[1].summary is None  # No summary for uuid-2

    async def test_adversarial_query_and_props_are_treated_as_data(self, mock_gemini_client):
        """Prompt-injection text in query/properties should stay untrusted prompt data."""
        malicious_query = f"{ADVERSARIAL_PROMPT_INJECTION} {ADVERSARIAL_TOOL_MISUSE}"
        hits = [
            _make_hit(
                "uuid-1",
                title=ADVERSARIAL_PROMPT_INJECTION,
                notes=ADVERSARIAL_TOOL_MISUSE,
            )
        ]
        mock_gemini_client["generate_structured"].return_value = HitSummaryBatch(
            summaries=[HitSummary(
                object_id="uuid-1",
                relevance=0.7,
                summary="Handled safely",
                useful_properties=["title"],
            )],
        )

        result = await summarize_hits(hits, malicious_query)

        assert result[0].summary == "Handled safely"
        call_args = mock_gemini_client["generate_structured"].call_args
        assert call_args.kwargs["system_instruction"] == KNOWLEDGE_SUMMARIZE_SYSTEM
        prompt = call_args.args[0]
        assert malicious_query in prompt
        assert ADVERSARIAL_PROMPT_INJECTION in prompt
        assert ADVERSARIAL_TOOL_MISUSE in prompt
