"""Tests for installer state matrix export helpers."""

from scripts.export_installer_state_matrix import (
    MIN_SCENARIO_COUNT,
    SCENARIOS,
    _build_scenario_summary,
    _validate_file_map,
)


def test_scenario_inventory_meets_minimum_threshold() -> None:
    """GIVEN baseline scenarios WHEN counted THEN inventory meets minimum quality gate."""
    assert len(SCENARIOS) >= MIN_SCENARIO_COUNT


def test_scenario_summary_matches_inventory() -> None:
    """GIVEN scenario list WHEN summarized THEN totals and counts are consistent."""
    summary = _build_scenario_summary(SCENARIOS)

    assert summary["total"] == len(SCENARIOS)
    assert sum(summary["by_category"].values()) == len(SCENARIOS)
    assert sum(summary["by_risk"].values()) == len(SCENARIOS)


def test_validate_file_map_reports_missing_and_duplicates() -> None:
    """GIVEN invalid FILE_MAP WHEN validated THEN missing and duplicate issues are reported."""
    file_map = {
        "commands/video.md": "commands/gr/video.md",
        "commands/missing.md": "commands/gr/video.md",
    }

    result = _validate_file_map(file_map)

    assert result["missing_source_count"] == 1
    assert result["duplicate_destination_count"] == 1
    assert result["integrity_pass"] is False
