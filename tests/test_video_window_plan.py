"""Strict contiguous requested window plans, exact local commitments and no provider."""

import hashlib
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from video_research_mcp.models.video_windows import WindowAnalysisRequest, WindowRunLimits
from video_research_mcp.video_window_plan import plan_windows, validate_plan


def limits(**changes):
    return WindowRunLimits(
        **{
            "max_calls": 50,
            "max_tokens": 100000,
            "max_output_tokens": 1000,
            "max_frames": 14400,
            "max_windows": 50,
            **changes,
        }
    )


def request(source, **changes):
    return WindowAnalysisRequest(
        **{
            "file_path": str(source),
            "instruction": "Inspect requested intervals",
            "end_ms": 7200000,
            **changes,
        }
    )


def test_two_hour_plan_is_contiguous_exact_and_provider_free(tmp_path, clean_config):
    """GIVEN a synthetic requested two-hour interval WHEN planned THEN 24 windows have no gaps/overlap."""
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"owned source bytes; duration is deliberately not inferred")
    with patch(
        "video_research_mcp.client.GeminiClient.get",
        side_effect=AssertionError("No provider during planning"),
    ):
        plan = plan_windows(request(source), limits())
        validate_plan(plan)
    assert len(plan["windows"]) == 24 and plan["fps"] == 1.0
    assert plan["windows"][0]["start_ms"] == 0 and plan["windows"][-1]["end_ms"] == 7200000
    assert all(a["end_ms"] == b["start_ms"] for a, b in zip(plan["windows"], plan["windows"][1:]))
    assert sum(w["end_ms"] - w["start_ms"] for w in plan["windows"]) == 7200000
    assert 2 * sum(w["requested_frames"] for w in plan["windows"]) <= limits().max_frames
    assert plan["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert plan["source"]["bytes"] == len(source.read_bytes())
    assert plan["preparation"]["provider_calls"] == 0 and not plan["duration_verified"]
    assert plan["observed_coverage"] == "unknown"
    assert plan["response_schema"]["type"] == "object"


def test_partial_final_window_and_adaptive_density_preserve_original_origin(tmp_path, clean_config):
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"owned")
    plan = plan_windows(
        request(source, start_ms=123, end_ms=7200123, window_ms=310000), limits(max_frames=96)
    )
    assert (
        plan["fps"] < 1 and plan["sampling_method"] == "uniform_density_from_initial_frame_budget"
    )
    assert plan["windows"][0]["start_ms"] == 123 and plan["windows"][-1]["end_ms"] == 7200123
    assert "[123, 310123) milliseconds" in plan["windows"][0]["prompt"]
    assert 2 * sum(w["requested_frames"] for w in plan["windows"]) <= 96


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_calls", True),
        ("max_calls", 101),
        ("max_tokens", 0),
        ("max_output_tokens", 100001),
        ("max_frames", 1.5),
        ("max_windows", -1),
    ],
)
def test_strict_limits_reject_invalid_reservations(field, value):
    with pytest.raises(ValidationError):
        limits(**{field: value})


@pytest.mark.parametrize(
    "change",
    [
        {"start_ms": True},
        {"end_ms": 0},
        {"start_ms": 100, "end_ms": 99},
        {"window_ms": 1},
        {"fps": float("nan")},
        {"fps": float("inf")},
        {"fps": True},
        {"fps": 31},
    ],
)
def test_strict_selection_rejects_invalid_or_excessive_windows(change):
    with pytest.raises(ValidationError):
        request("owned.mp4", **change)


@pytest.mark.parametrize(
    "fields", [{"file_path": None}, {"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"}]
)
def test_exactly_one_source_is_required(fields):
    with pytest.raises(ValidationError, match="Exactly one"):
        request("owned.mp4", **fields)


def test_foreign_url_cannot_enter_provider_planning(clean_config):
    with pytest.raises(ValueError, match="Could not extract video ID"):
        plan_windows(
            WindowAnalysisRequest(
                url="https://youtube.com.example.invalid/watch?v=dQw4w9WgXcQ",
                instruction="inspect",
                end_ms=1000,
            ),
            limits(),
        )


def test_plan_source_settings_and_metadata_mutation_fail_closed(
    tmp_path, clean_config, monkeypatch
):
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"owned")
    plan = plan_windows(request(source), limits())
    changed = {**plan, "fps": 2.0}
    with pytest.raises(ValueError, match="commitment"):
        validate_plan(changed)
    source.write_bytes(b"different owned bytes")
    with pytest.raises(ValueError, match="source changed"):
        validate_plan(plan)
    source.write_bytes(b"owned")
    from video_research_mcp.config import update_config

    update_config(gemini_api_key="different-dummy-account")
    with pytest.raises(ValueError, match="settings changed"):
        validate_plan(plan)
