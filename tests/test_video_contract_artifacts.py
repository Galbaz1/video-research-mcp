"""Tests for contract artifact rendering and quality gates."""

from __future__ import annotations

import time

from video_research_mcp.contract.quality import (
    _check_artifacts_exist,
    _check_html_parseable,
    _check_links_valid,
    run_quality_gates,
)
from video_research_mcp.contract.render import render_artifacts


def _sample_analysis():
    return {
        "title": "Test Video",
        "summary": "A comprehensive summary of the test video content.",
        "key_points": ["First important point with details", "Second important point expanded", "Third important point expanded"],
        "timestamps": [
            {"time": "00:00", "description": "Introduction"},
            {"time": "05:00", "description": "Main discussion"},
            {"time": "09:30", "description": "Conclusion"},
        ],
        "topics": ["testing", "videos"],
        "sentiment": "positive",
        "duration_seconds": 600,
    }


def _sample_strategy():
    return {
        "title": "Strategy Report",
        "sections": [{"heading": "Overview", "content": "Detailed overview content here."}],
        "strategic_notes": ["Key takeaway"],
    }


def _sample_concept_map():
    return {
        "nodes": [
            {"id": "a", "label": "Testing", "category": "core"},
            {"id": "b", "label": "Videos", "category": "media"},
        ],
        "edges": [{"source": "a", "target": "b", "label": "analyzes"}],
    }


class TestRenderArtifacts:
    def test_all_artifacts_created(self, tmp_path):
        """Rendering creates all expected files."""
        paths = render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="https://youtube.com/test",
        )
        assert (tmp_path / "analysis.md").exists()
        assert (tmp_path / "strategy.md").exists()
        assert (tmp_path / "concept-map.html").exists()
        assert len(paths) == 3

    def test_analysis_contains_source(self, tmp_path):
        """Analysis markdown includes source label."""
        render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="https://youtube.com/test",
        )
        content = (tmp_path / "analysis.md").read_text()
        assert "https://youtube.com/test" in content

    def test_analysis_contains_cross_links(self, tmp_path):
        """Analysis markdown links to strategy and concept map."""
        render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="test",
        )
        content = (tmp_path / "analysis.md").read_text()
        assert "strategy.md" in content
        assert "concept-map.html" in content

    def test_html_is_valid(self, tmp_path):
        """Concept map HTML contains required structure."""
        render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="test",
        )
        html = (tmp_path / "concept-map.html").read_text()
        assert "<html" in html
        assert "</html>" in html
        assert "<svg" in html


class TestQualityChecks:
    def test_empty_or_out_of_scope_artifact_fails(self, tmp_path):
        render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="test",
        )
        analysis_path = tmp_path / "analysis.md"
        analysis_path.write_text("")
        assert not _check_artifacts_exist(tmp_path).passed
        outside = tmp_path.parent / "outside.md"
        outside.write_text("unrelated evidence")
        analysis_path.unlink()
        analysis_path.symlink_to(outside)
        assert not _check_artifacts_exist(tmp_path).passed

    def test_artifacts_exist_pass(self, tmp_path):
        """All artifacts present → pass."""
        render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="test",
        )
        check = _check_artifacts_exist(tmp_path)
        assert check.passed

    def test_artifacts_exist_fail(self, tmp_path):
        """Missing artifacts → fail."""
        check = _check_artifacts_exist(tmp_path)
        assert not check.passed
        assert "Missing" in check.detail

    def test_links_valid_pass(self, tmp_path):
        """Valid relative links → pass."""
        render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="test",
        )
        check = _check_links_valid(tmp_path)
        assert check.passed

    def test_links_valid_fail(self, tmp_path):
        """Broken relative link → fail."""
        md = tmp_path / "test.md"
        md.write_text("[broken](nonexistent.html)")
        check = _check_links_valid(tmp_path)
        assert not check.passed
        assert "broken link" in check.detail

    def test_html_parseable_pass(self, tmp_path):
        """Well-formed HTML → pass."""
        render_artifacts(
            tmp_path, _sample_analysis(), _sample_strategy(), _sample_concept_map(),
            source_label="test",
        )
        check = _check_html_parseable(tmp_path)
        assert check.passed

    def test_html_parseable_fail(self, tmp_path):
        """Malformed HTML → fail."""
        (tmp_path / "bad.html").write_text("<div>no html tags</div>")
        check = _check_html_parseable(tmp_path)
        assert not check.passed

    def test_full_quality_gates_pass(self, tmp_path):
        """All quality gates pass with valid artifacts."""
        analysis = _sample_analysis()
        strategy = _sample_strategy()
        concept_map = _sample_concept_map()

        render_artifacts(tmp_path, analysis, strategy, concept_map, source_label="test")

        report = run_quality_gates(
            analysis, strategy, concept_map, tmp_path,
            coverage_min_ratio=0.90,
            start_time=time.monotonic(),
        )
        assert report.status == "pass"
        assert report.duration_seconds >= 0
