"""C3: bounded nearby frame/crop escalation at the mocked native decode boundary."""

import asyncio
from pathlib import Path

import pytest
from jsonschema import validate

from tests.test_grounding_support import cite, claim, grounding_request, index_corpus, sha
from tests.test_temporal_ocr_mcp import scene_fixture as scene_fixture
from video_research_mcp import grounding_escalation
from video_research_mcp.tools.grounding import _SCHEMA, grounded_answer

WEAK = [claim("c1", "Something is overheating", cite("ocr-1", 0.1, 0.9))]


@pytest.fixture
async def case(scene_fixture, tmp_path):
    """Corpus observations bound to the authored source digest used by the decode mock."""
    corpus = await index_corpus(tmp_path, sha(scene_fixture["source"].read_bytes()))
    return scene_fixture, corpus


def escalation(env, digest=None, **budget) -> dict:
    return {"file_path": str(env["source"]),
            "expected_source_sha256": digest or sha(env["source"].read_bytes()),
            "crop_box": [20, 10, 80, 40], "max_pixels": 4000, "budget": budget}


async def run(case, claims=WEAK, **budget):
    env, corpus = case
    result = await grounded_answer(request=grounding_request(
        corpus, "overheating", claims, escalation=escalation(env, **budget)))
    validate(result, _SCHEMA)
    return result


async def test_attempt_limit_keeps_source_crop_and_pts_actual_time(case):
    """GIVEN a weak claim WHEN escalated THEN decoded PTS, not requests, define observed time."""
    env, corpus = case
    result = await run(case, max_attempts=2)
    report = result["escalation"]
    assert report["status"] == "stopped" and report["stop_reason"] == "attempt_limit"
    first, second = report["attempts"]
    assert [a["requested_seconds"] for a in (first, second)] == [0.1, 0.5]
    assert [a["actual_seconds"] for a in (first, second)] == pytest.approx([0.2, 0.8])
    assert [a["original_pts"] for a in (first, second)] == [7200, 7800]
    assert first["time_base"] == "1/1000" and first["crop_box"] == [20, 10, 80, 40]
    assert first["within_cited_span"] is True and first["interpretation"] == "not_performed"
    assert first["source"]["sha256"] == corpus["digest"]
    artifact = Path(first["artifact"]["path"])
    assert sha(artifact.read_bytes()) == first["artifact"]["sha256"]
    assert report["bytes_used"] == first["artifact"]["bytes"] + second["artifact"]["bytes"]
    assert result["limits"]["auxiliary_calls"] == 2 and result["limits"]["provider_calls"] == 0
    assert result["claims"][0]["support"] == "citation_available_semantics_unverified"
    assert result["status"] == "partially_grounded"


async def test_complete_plan_reports_actual_time_outside_cited_span(case):
    report = (await run(case))["escalation"]
    assert report["status"] == "complete" and report["stop_reason"] is None
    last = report["attempts"][-1]
    assert last["requested_seconds"] == 0.9 and last["actual_seconds"] == pytest.approx(1.4)
    assert last["within_cited_span"] is False


async def test_byte_budget_stops_before_any_decode(case):
    env, _ = case
    report = (await run(case, max_bytes=65536))["escalation"]
    assert report["status"] == "stopped" and report["stop_reason"] == "byte_budget"
    assert report["attempts"] == [] and env["commands"] == []


async def test_oversized_observation_is_discarded_and_stops(case, monkeypatch, tmp_path):
    real = grounding_escalation.frame_at

    async def inflated(*args, **kwargs):
        metadata = await real(*args, **kwargs)
        metadata["frames"][0]["bytes"] = 5 * 1024 * 1024
        return metadata

    monkeypatch.setattr(grounding_escalation, "frame_at", inflated)
    report = (await run(case))["escalation"]
    assert report["stop_reason"] == "byte_budget" and report["bytes_used"] == 0
    (attempt,) = report["attempts"]
    assert attempt["status"] == "discarded_byte_budget" and attempt["artifact"] is None
    assert list((tmp_path / "cache/media/views").iterdir()) == []


async def test_deadline_stops_and_retains_in_flight_attempt(case, monkeypatch):
    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(grounding_escalation, "frame_at", blocked)
    report = (await run(case, deadline_seconds=0.05))["escalation"]
    assert report["status"] == "stopped" and report["stop_reason"] == "deadline"
    (attempt,) = report["attempts"]
    assert attempt["status"] == "failed" and attempt["requested_seconds"] == 0.1


async def test_failed_decodes_are_retained_without_reporting_requested_time(case):
    env, _ = case
    env["bad_pts"] = 79999
    result = await run(case)
    report = result["escalation"]
    assert [a["status"] for a in report["attempts"]] == ["failed"] * 3
    assert all(a["actual_seconds"] is None and a["error"]["category"] for a in report["attempts"])
    assert result["limits"]["auxiliary_calls"] == 3


async def test_other_source_revision_is_refused_before_decode(case):
    env, corpus = case
    result = await grounded_answer(request=grounding_request(
        corpus, "overheating", WEAK, escalation=escalation(env, digest="b" * 64)))
    report = result["escalation"]
    assert report["status"] == "refused" and report["attempts"] == []
    assert report["refusals"][0]["reason"] == "source_digest_differs_from_cited_observation"
    assert env["commands"] == []


async def test_verbatim_supported_claim_needs_no_escalation(case):
    env, _ = case
    claims = [claim("c1", "ERROR B", cite("ocr-1", 0.1, 0.9, "ERROR B"))]
    result = await run(case, claims=claims)
    assert result["escalation"]["status"] == "not_needed" and env["commands"] == []
    assert result["status"] == "grounded"
