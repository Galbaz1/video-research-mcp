"""Original-fixture checks for sparse response views and exact text pagination."""

from __future__ import annotations

from copy import deepcopy

import pytest

from video_research_mcp.output_view import (
    MAX_TRANSCRIPT_LIMIT,
    MAX_TRANSCRIPT_OFFSET,
    project_output,
    validate_output_request,
)


@pytest.fixture
def source() -> dict:
    """Return original custom-schema data with full evidence and a large non-evidence field."""
    return {
        "summary": "Original fixture summary",
        "transcript": "α😀e\u0301\nOriginal line two.\nFinal line.",
        "source": "original-fixture.txt",
        "source_id": "original",
        "content_id": "content-original",
        "source_revision": "fixture-v1",
        "source_sha256": "a" * 64,
        "provenance": {"method": "original-fixture"},
        "coverage": {"status": "unknown"},
        "quality_report": {"factual_success": False},
        "artifacts": {"markdown": "original-fixture/report.md"},
        "local_filepath": "original-fixture.mp4",
        "screenshot_dir": "original-fixture/frames",
        "execution_usage": {"provider_calls": 0, "estimated": False},
        "citations": [{"source_id": "original", "passage_id": "p1", "quote": "Original line"}],
        "evidence_packet": {
            "packet_id": "packet-original",
            "sources": [{"id": "original", "revision": "fixture-v1", "sha256": "a" * 64}],
            "claims": [{"id": "c1", "support": [{"source_id": "original", "passage_id": "p1"}]}],
        },
        "large_details": {"unselected_text": "Original unused detail. " * 50_000},
    }


def test_unselected_view_is_equal_and_independent(source):
    """GIVEN a stored result WHEN no view is requested THEN values remain complete and detached."""
    before = deepcopy(source)
    result = project_output(source)
    assert result == source and result is not source
    result["citations"][0]["quote"] = "Later response edit"
    result["large_details"]["unselected_text"] = "Later response edit"
    assert source == before


def test_sparse_view_preserves_complete_identity_and_evidence(source):
    """GIVEN a sparse request WHEN copied THEN excluded details disappear but all evidence survives."""
    before = deepcopy(source)
    result = project_output(source, fields=["summary"])
    assert set(result) == {
        "summary",
        "source",
        "source_id",
        "content_id",
        "source_revision",
        "source_sha256",
        "citations",
        "evidence_packet",
        "provenance",
        "coverage",
        "quality_report",
        "artifacts",
        "local_filepath",
        "screenshot_dir",
        "execution_usage",
        "output_view",
    }
    for name in set(result) - {"output_view"}:
        assert result[name] == source[name]
    assert result["output_view"] == {
        "requested_fields": ["summary"],
        "returned_fields": list(result),
        "method": "top_level_fields_preserving_provenance",
    }
    result["evidence_packet"]["sources"][0]["revision"] = "Later edit"
    result["citations"].clear()
    assert source == before


def test_nested_citation_carrier_cannot_be_excluded(source):
    source["custom_findings"] = [{"text": "Original claim", "citations": source["citations"]}]
    source["quality_report"] = {"coverage": {"receipt": {"source_revision": "fixture-v1"}}}
    result = project_output(source, fields=[])
    assert result["custom_findings"] == source["custom_findings"]
    assert result["quality_report"] == source["quality_report"]
    assert "summary" not in result and "large_details" not in result


def test_excluded_large_field_is_not_copied():
    class Uncopyable:
        def __deepcopy__(self, memo):
            raise AssertionError("Excluded payload was copied")

    result = project_output(
        {"summary": "Original", "large_payload": Uncopyable()}, fields=["summary"]
    )
    assert result["summary"] == "Original"
    assert result["output_view"]["returned_fields"] == ["summary", "output_view"]
    assert "large_payload" not in result


def test_text_pages_replay_and_concatenate_exactly(source):
    """GIVEN Unicode text WHEN continued by returned offsets THEN exact text replays without gaps."""
    before = deepcopy(source)
    pages, offset = [], 0
    while True:
        result = project_output(
            source, fields=["summary"], transcript_offset=offset, transcript_limit=5
        )
        assert result == project_output(
            source, fields=["summary"], transcript_offset=offset, transcript_limit=5
        )
        page = result["transcript_page"]
        pages.append(result["transcript"])
        assert page == {
            "offset": offset,
            "limit": 5,
            "returned": len(result["transcript"]),
            "total": len(source["transcript"]),
            "next_offset": (
                offset + len(result["transcript"])
                if offset + 5 < len(source["transcript"])
                else None
            ),
            "truncated": bool(offset or offset + 5 < len(source["transcript"])),
            "prefix_omitted": offset,
            "remaining": max(len(source["transcript"]) - offset - 5, 0),
            "unit": "unicode_codepoints",
        }
        assert result["citations"] == source["citations"]
        assert result["evidence_packet"] == source["evidence_packet"]
        assert "large_details" not in result
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert "".join(pages) == source["transcript"]
    assert source == before


@pytest.mark.parametrize("offset", [0, 4, 5, 100, MAX_TRANSCRIPT_OFFSET])
def test_exact_end_empty_and_out_of_range_flags(offset):
    result = project_output({"transcript": "abcd"}, transcript_offset=offset, transcript_limit=4)
    assert result["transcript"] == "abcd"[offset : offset + 4]
    assert result["transcript_page"]["offset"] == offset
    assert result["transcript_page"]["truncated"] is bool(offset)
    assert result["transcript_page"]["prefix_omitted"] == min(offset, 4)
    assert result["transcript_page"]["remaining"] == 0
    assert result["transcript_page"]["next_offset"] is None


def test_empty_present_text_is_a_valid_finished_page():
    result = project_output({"transcript": ""}, transcript_limit=1)
    assert result["transcript"] == ""
    assert result["transcript_page"]["returned"] == result["transcript_page"]["total"] == 0
    assert result["transcript_page"]["truncated"] is False
    assert (
        result["transcript_page"]["prefix_omitted"] == result["transcript_page"]["remaining"] == 0
    )


@pytest.mark.parametrize(
    "offset", [-1, True, False, 0.5, float("inf"), None, "0", MAX_TRANSCRIPT_OFFSET + 1]
)
def test_invalid_offsets_are_rejected(offset):
    with pytest.raises(ValueError, match="transcript_offset"):
        project_output({"transcript": "Original"}, transcript_offset=offset, transcript_limit=1)


@pytest.mark.parametrize(
    "limit", [0, -1, True, False, 0.5, float("nan"), "1", MAX_TRANSCRIPT_LIMIT + 1]
)
def test_invalid_limits_are_rejected(limit):
    with pytest.raises(ValueError, match="transcript_limit"):
        project_output({"transcript": "Original"}, transcript_limit=limit)


def test_nonzero_offset_requires_a_bounded_limit():
    with pytest.raises(ValueError, match="requires transcript_limit"):
        project_output({"transcript": "Original"}, transcript_offset=1)


@pytest.mark.parametrize("transcript", [None, [], [{"text": "Original"}], {}, 1, True])
def test_unsupported_transcript_shapes_are_not_treated_as_empty(transcript):
    with pytest.raises(ValueError, match="top-level transcript string"):
        project_output({"transcript": transcript}, transcript_limit=1)


def test_absent_transcript_and_metadata_collision_are_explicit_errors():
    with pytest.raises(ValueError, match="top-level transcript string"):
        project_output({"summary": "Original"}, transcript_limit=1)
    with pytest.raises(ValueError, match="transcript_page"):
        project_output(
            {"transcript": "Original", "transcript_page": {"original": True}}, transcript_limit=1
        )
    original = {"summary": "Original", "output_view": {"original": True}}
    with pytest.raises(ValueError, match="output_view"):
        project_output(original, fields=["summary"])
    assert project_output(original) == original


def test_requested_fields_metadata_is_detached_and_maximum_page_is_bounded(source):
    fields = ["summary"]
    result = project_output(source, fields=fields, transcript_limit=MAX_TRANSCRIPT_LIMIT)
    fields.clear()
    assert result["output_view"]["requested_fields"] == ["summary"]
    assert result["transcript"] == source["transcript"]
    assert result["transcript_page"]["truncated"] is False
    assert result["transcript_page"]["next_offset"] is None


def test_preflight_validates_without_accessing_a_dynamic_result():
    assert validate_output_request(["not_yet_generated"], 0, 1) is None
    assert validate_output_request(None, 0, None) is None
    with pytest.raises(ValueError, match="transcript_offset"):
        validate_output_request(["summary"], True, 1)
    with pytest.raises(ValueError, match="fields"):
        validate_output_request(["summary", "summary"], 0, 1)


@pytest.mark.parametrize(
    "fields",
    [
        "summary",
        {"summary"},
        [True],
        [""],
        ["summary", "summary"],
        ["absent"],
        ["analysis.summary"],
    ],
)
def test_invalid_explicit_top_level_fields_are_rejected(source, fields):
    before = deepcopy(source)
    with pytest.raises(ValueError, match="fields"):
        project_output(source, fields=fields)
    assert source == before
