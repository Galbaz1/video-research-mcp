"""Tests for semantic validation module."""

from __future__ import annotations

from video_research_mcp.validation import (
    validate_analysis,
    validate_concept_edges,
    validate_key_points,
    validate_timestamps,
)


class TestValidateTimestamps:
    def test_valid_ordered_timestamps(self):
        timestamps = [
            {"time": "00:30", "description": "Intro"},
            {"time": "02:15", "description": "Main"},
            {"time": "10:00", "description": "Conclusion"},
        ]
        assert validate_timestamps(timestamps) == []

    def test_out_of_order(self):
        timestamps = [
            {"time": "05:00", "description": "Late"},
            {"time": "01:00", "description": "Early"},
        ]
        issues = validate_timestamps(timestamps)
        assert len(issues) == 1
        assert "out of order" in issues[0]

    def test_invalid_format(self):
        timestamps = [{"time": "invalid", "description": "Bad"}]
        issues = validate_timestamps(timestamps)
        assert len(issues) == 1
        assert "invalid format" in issues[0]

    def test_hh_mm_ss_format(self):
        """HH:MM:SS format is accepted."""
        timestamps = [
            {"time": "1:00:00", "description": "Hour mark"},
            {"time": "1:30:00", "description": "Later"},
        ]
        assert validate_timestamps(timestamps) == []


class TestValidateKeyPoints:
    def test_substantial_points_pass(self):
        points = ["This is a sufficiently long key point about testing"]
        assert validate_key_points(points) == []

    def test_short_points_flagged(self):
        points = ["Too short", "Also short"]
        issues = validate_key_points(points, min_length=20)
        assert len(issues) == 2

    def test_custom_min_length(self):
        points = ["Medium length point"]
        assert validate_key_points(points, min_length=10) == []
        issues = validate_key_points(points, min_length=50)
        assert len(issues) == 1


class TestValidateConceptEdges:
    def test_valid_edges(self):
        nodes = [{"id": "a"}, {"id": "b"}]
        edges = [{"source": "a", "target": "b"}]
        assert validate_concept_edges(nodes, edges) == []

    def test_dangling_source(self):
        nodes = [{"id": "a"}]
        edges = [{"source": "missing", "target": "a"}]
        issues = validate_concept_edges(nodes, edges)
        assert len(issues) == 1
        assert "source" in issues[0]

    def test_dangling_target(self):
        nodes = [{"id": "a"}]
        edges = [{"source": "a", "target": "missing"}]
        issues = validate_concept_edges(nodes, edges)
        assert len(issues) == 1
        assert "target" in issues[0]


class TestValidateAnalysis:
    def test_valid_analysis(self):
        result = {
            "timestamps": [
                {"time": "00:00", "description": "Start"},
                {"time": "05:00", "description": "Middle"},
                {"time": "09:30", "description": "End"},
            ],
            "key_points": [
                "This is a detailed key point about the main topic discussed",
                "Another detailed point covering an important aspect of the video",
            ],
        }
        vr = validate_analysis(result, duration_seconds=600)
        assert vr.passed

    def test_analysis_with_issues(self):
        result = {
            "timestamps": [
                {"time": "05:00", "description": "Late"},
                {"time": "01:00", "description": "Early"},
            ],
            "key_points": ["short"],
        }
        vr = validate_analysis(result)
        assert not vr.passed
        assert len(vr.issues) >= 2


def test_invalid_clock_and_measured_bounds_are_structural_checks():
    assert "invalid clock" in validate_timestamps([{"time": "01:99"}])[0]
    assert (
        "measured duration"
        in validate_timestamps(
            [{"time": "59:59"}],
            duration_seconds=60,
        )[0]
    )
