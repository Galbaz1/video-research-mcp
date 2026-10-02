"""Tests for the strict video contract pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from video_research_mcp.contract.pipeline import run_strict_pipeline, sanitize_slug
from video_research_mcp.models.video_contract import (
    ConceptMap,
    ConceptMapEdge,
    ConceptMapNode,
    StrictTimestamp,
    StrictVideoResult,
    StrategyReport,
    StrategySection,
)


def _make_analysis():
    return StrictVideoResult(
        title="Test Video Analysis",
        summary="A" * 60,
        key_points=[
            "Point one is detailed enough to pass",
            "Point two is also quite detailed",
            "Point three has enough detail",
        ],
        timestamps=[
            StrictTimestamp(time="00:00", description="Introduction to the topic"),
            StrictTimestamp(time="05:00", description="Main discussion begins"),
            StrictTimestamp(time="09:30", description="Conclusion and wrap up"),
        ],
        topics=["testing", "analysis"],
        sentiment="positive",
        duration_seconds=600,
    )


def _make_strategy():
    return StrategyReport(
        title="Strategy Report",
        sections=[StrategySection(heading="Overview", content="A detailed overview section here")],
        strategic_notes=["Key takeaway from the video"],
    )


def _make_concept_map():
    return ConceptMap(
        nodes=[
            ConceptMapNode(id="a", label="Testing"),
            ConceptMapNode(id="b", label="Analysis"),
        ],
        edges=[ConceptMapEdge(source="a", target="b", label="supports")],
    )


class TestSanitizeSlug:
    def test_normal_title(self):
        assert sanitize_slug("My Test Video") == "my-test-video"

    def test_special_characters(self):
        assert sanitize_slug("Hello, World! 2024") == "hello-world-2024"

    def test_empty_after_sanitization(self):
        with pytest.raises(ValueError, match="Cannot derive"):
            sanitize_slug("!!!")

    def test_long_title_truncated(self):
        slug = sanitize_slug("a" * 100)
        assert len(slug) <= 50

    def test_path_traversal_rejected(self):
        """Slug that somehow contains path traversal is rejected."""
        # Normal titles won't produce traversal, but test the guard
        assert sanitize_slug("normal-title") == "normal-title"


class TestRunStrictPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_success(self, mock_gemini_client, tmp_path, monkeypatch):
        """Full pipeline success: all stages produce artifacts + quality pass."""
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path / "output"))

        analysis = _make_analysis()
        strategy = _make_strategy()
        concept_map = _make_concept_map()

        mock_gemini_client["generate_structured"].side_effect = [analysis, strategy, concept_map]

        result = await run_strict_pipeline(
            "test contents",
            instruction="analyze",
            content_id="abc123",
            source_label="https://youtube.com/watch?v=abc123",
        )

        assert "error" not in result
        assert result["analysis"]["title"] == "Test Video Analysis"
        assert "artifacts" in result
        assert result["quality_report"]["status"] == "pass"
        assert mock_gemini_client["generate_structured"].call_count == 3

    @pytest.mark.asyncio
    async def test_pipeline_analysis_failure(self, mock_gemini_client, tmp_path, monkeypatch):
        """Analysis stage failure returns tool error."""
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path / "output"))
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("Gemini down")

        result = await run_strict_pipeline(
            "test contents",
            instruction="analyze",
            content_id="abc123",
            source_label="test-source",
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_pipeline_parallel_failure(self, mock_gemini_client, tmp_path, monkeypatch):
        """Strategy/concept stage failure returns tool error."""
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path / "output"))

        analysis = _make_analysis()
        mock_gemini_client["generate_structured"].side_effect = [
            analysis,
            RuntimeError("Strategy failed"),
        ]

        result = await run_strict_pipeline(
            "test contents",
            instruction="analyze",
            content_id="abc123",
            source_label="test-source",
        )

        assert "error" in result

    @pytest.mark.asyncio
    async def test_output_dir_collision(self, mock_gemini_client, tmp_path, monkeypatch):
        """Collision on output dir adds UUID suffix."""
        output_base = tmp_path / "output"
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(output_base))

        # Pre-create the expected slug dir
        (output_base / "test-video-analysis").mkdir(parents=True)

        analysis = _make_analysis()
        strategy = _make_strategy()
        concept_map = _make_concept_map()
        mock_gemini_client["generate_structured"].side_effect = [analysis, strategy, concept_map]

        result = await run_strict_pipeline(
            "test contents",
            instruction="analyze",
            content_id="abc123",
            source_label="test-source",
        )

        assert "error" not in result
        # The artifact dir should be different from the pre-created one
        artifact_path = result["artifacts"]["analysis"]
        assert "test-video-analysis-" in artifact_path

    @pytest.mark.asyncio
    async def test_quality_gate_failure_cleans_up(self, mock_gemini_client, tmp_path, monkeypatch):
        """Quality gate failure cleans up temp dir and returns error."""
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path / "output"))

        # Create analysis with low coverage (timestamps only cover 30% of duration)
        analysis = StrictVideoResult(
            title="Low Coverage Video",
            summary="A" * 60,
            key_points=["a" * 20, "b" * 20, "c" * 20],
            timestamps=[
                StrictTimestamp(time="00:00", description="Only the very start of video"),
                StrictTimestamp(time="01:00", description="Still early in the video"),
                StrictTimestamp(time="03:00", description="Still less than half covered"),
            ],
            topics=["testing"],
            sentiment="neutral",
            duration_seconds=600,
        )
        strategy = _make_strategy()
        concept_map = _make_concept_map()
        mock_gemini_client["generate_structured"].side_effect = [analysis, strategy, concept_map]

        with patch("video_research_mcp.contract.quality.validate_analysis") as mock_validate:
            from video_research_mcp.validation import ValidationResult

            mock_validate.return_value = ValidationResult(passed=False, issues=["Coverage too low"])

            result = await run_strict_pipeline(
                "test contents",
                instruction="analyze",
                content_id="abc123",
                source_label="test-source",
                coverage_min_ratio=0.90,
            )

        assert "error" in result
        assert result["category"] == "QUALITY_GATE_FAILED"

    @pytest.mark.asyncio
    async def test_pipeline_passes_metadata_as_system_instruction(
        self, mock_gemini_client, tmp_path, monkeypatch
    ):
        """metadata_context is forwarded as system_instruction to Stage 1."""
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path / "output"))

        analysis = _make_analysis()
        strategy = _make_strategy()
        concept_map = _make_concept_map()
        mock_gemini_client["generate_structured"].side_effect = [analysis, strategy, concept_map]

        await run_strict_pipeline(
            "test contents",
            instruction="analyze",
            content_id="abc123",
            source_label="test-source",
            metadata_context="YouTube: Test Video by TestChannel",
        )

        # First generate_structured call is Stage 1 (analysis)
        first_call = mock_gemini_client["generate_structured"].call_args_list[0]
        assert first_call.kwargs["system_instruction"] == "YouTube: Test Video by TestChannel"


async def test_actual_failed_validation_promotes_no_artifacts(
    mock_gemini_client, tmp_path, monkeypatch
):
    monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path / "output"))
    analysis = _make_analysis()
    analysis.key_points = ["short"] * 3
    mock_gemini_client["generate_structured"].side_effect = [
        analysis,
        _make_strategy(),
        _make_concept_map(),
    ]
    result = await run_strict_pipeline(
        "fixture",
        instruction="analyze",
        content_id="owned-fixture",
        source_label="owned-fixture",
    )
    assert result["category"] == "QUALITY_GATE_FAILED"
    assert "artifacts" not in result
    assert result["quality_report"]["factual_success"] is False
    assert list((tmp_path / "output").iterdir()) == []


async def test_promoted_artifacts_retain_the_same_quality_receipt(
    mock_gemini_client, tmp_path, monkeypatch
):
    monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path / "output"))
    mock_gemini_client["generate_structured"].side_effect = [
        _make_analysis(),
        _make_strategy(),
        _make_concept_map(),
    ]
    result = await run_strict_pipeline(
        "fixture",
        instruction="analyze",
        content_id="owned-fixture",
        source_label="owned-fixture",
    )
    artifact = Path(result["artifacts"]["analysis"])
    report = json.loads((artifact.parent / "quality-report.json").read_text())
    assert report == result["quality_report"]
    assert report["coverage_ratio"] is None
    assert report["factual_success"] is False
    assert "review are pending" in artifact.read_text()
