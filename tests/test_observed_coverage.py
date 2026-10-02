"""Coverage uses exact observation receipts and retains unavailable stages."""

import time

import pytest
from pydantic import ValidationError

from video_research_mcp.contract.quality import run_quality_gates
from video_research_mcp.contract.render import render_artifacts
from video_research_mcp.models.coverage import MediaCoverage, MediaSpan, summarize_coverage


def receipt(**updates):
    values = {
        "source_id": "owned-test",
        "source_revision": "v1",
        "source_sha256": "a" * 64,
        "measured_duration_ms": 1000,
        "missing_stages": [],
    }
    values.update(updates)
    return MediaCoverage(**values)


def test_union_preserves_gaps_without_double_counting():
    actual = receipt(
        requested=[MediaSpan(start_ms=0, end_ms=1000)],
        extracted=[MediaSpan(start_ms=0, end_ms=1000)],
        observed=[
            MediaSpan(start_ms=100, end_ms=400),
            MediaSpan(start_ms=200, end_ms=500),
            MediaSpan(start_ms=600, end_ms=800),
        ],
    )
    report = summarize_coverage(actual, 0.9)
    assert report.status == "fail"
    assert report.observed_ratio == 0.6
    assert report.observed_ms == 600
    assert [(gap.start_ms, gap.end_ms) for gap in report.gaps] == [
        (0, 100),
        (500, 600),
        (800, 1000),
    ]
    assert MediaCoverage.model_validate_json(actual.model_dump_json()) == actual


def test_requested_extracted_and_sparse_frames_do_not_imply_observed_intervals():
    report = summarize_coverage(
        receipt(
            requested=[MediaSpan(start_ms=0, end_ms=1000)],
            extracted=[MediaSpan(start_ms=0, end_ms=1000)],
            observed_frame_ms=[0, 999],
        ),
        0.9,
    )
    assert report.observed_ratio == 0
    assert report.status == "fail"
    assert report.gaps == [MediaSpan(start_ms=0, end_ms=1000)]


def test_missing_stage_and_unknown_duration_cannot_pass_coverage():
    full = [MediaSpan(start_ms=0, end_ms=1000)]
    assert (
        summarize_coverage(receipt(observed=full, missing_stages=["media_observation"]), 0.9).status
        == "unknown"
    )
    unknown = summarize_coverage(receipt(observed=full, measured_duration_ms=None), 0.9)
    assert unknown.status == "unknown" and unknown.observed_ratio is None
    assert summarize_coverage(receipt(observed=full), 0.9).status == "pass"


@pytest.mark.parametrize(
    "start,end", [(100, 100), (-1, 10), (0, float("inf")), (0, True), (0, 1001)]
)
def test_invalid_or_out_of_media_span_fails_at_boundary(start, end):
    with pytest.raises(ValidationError):
        receipt(observed=[MediaSpan(start_ms=start, end_ms=end)])


def test_observation_requires_original_identity():
    with pytest.raises(ValidationError, match="source revision"):
        receipt(observed=[MediaSpan(start_ms=0, end_ms=1000)], source_sha256=None)


def test_fabricated_late_timestamp_and_model_receipt_cannot_create_coverage(tmp_path):
    from tests.test_video_contract_artifacts import (
        _sample_analysis,
        _sample_concept_map,
        _sample_strategy,
    )

    analysis, strategy, concepts = _sample_analysis(), _sample_strategy(), _sample_concept_map()
    analysis["timestamps"][-1]["time"] = "99:59"
    analysis["coverage"] = receipt(observed=[MediaSpan(start_ms=0, end_ms=1000)]).model_dump()
    render_artifacts(tmp_path, analysis, strategy, concepts, source_label="fixture")
    report = run_quality_gates(
        analysis,
        concepts,
        tmp_path,
        start_time=time.monotonic(),
        observation=MediaCoverage(source_id="fixture"),
    )
    assert report.coverage_ratio is None
    assert report.coverage.status == "unknown"
    assert not report.factual_success
    measured = run_quality_gates(
        analysis,
        concepts,
        tmp_path,
        start_time=time.monotonic(),
        observation=receipt(),
    )
    assert measured.status == "fail"
    assert measured.timestamp_correctness == "pending"
