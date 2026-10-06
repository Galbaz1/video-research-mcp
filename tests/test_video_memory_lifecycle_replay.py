"""Bounded source-only watch/replay checks; mocked AV client, no actual media or providers."""

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

from pydantic import ValidationError
import pytest

from video_research_mcp.models.video_memory_lifecycle import Checkpoint
from video_research_mcp.tools.video_memory_lifecycle import video_memory_lifecycle
from video_research_mcp.video_memory import av_build, lifecycle_inputs, replay

from tests.test_video_memory_lifecycle import REQUEST, request, source, state

CONFIG = {"av_route": {"authorize_submission": True, "max_calls": 8}}


def event(src, start=0.0):
    """Return a complete typed caller-authored AV fixture, without speaker labels or speech."""
    digest = src["expected_source_sha256"]
    return {"operation": "media_caption_events", "task": "caption", "status": "complete", "outcome": "events",
            "source": {"sha256": digest, "bytes": src["expected_source_bytes"],
                       "presentation_end_seconds": src["duration_seconds"]},
            "backend": {}, "request_sha256": "b" * 64, "windows": [],
            "records": [{"record_id": "av_" + "c" * 64, "source_sha256": digest, "window_index": 0,
                         "start_seconds": start + 1.0, "end_seconds": start + 2.0, "local_start_seconds": 1.0,
                         "local_end_seconds": 2.0, "basis": "visual", "description": "Dummy caption: red object.",
                         "frame_indices": [0], "visual_support": [], "audio_support": None}],
            "matches": [], "grounding_population": None, "count": None, "count_so_far": None,
            "target": None, "query": None, "summaries": [], "abstentions": [],
            "execution": {"fixture_only": True}, "provenance": {"basis": "caller_authored_fixture"}}


def clips(tmp, src):
    """Prepare explicitly retained dummy clips; no slicing, encoding or media execution."""
    result = []
    for window in range(3):
        path = tmp / f"clip-{window}.dummy"
        data = f"dummy-clip-{window}".encode()
        path.write_bytes(data)
        result.append({"window": window, "path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                       "bytes": len(data)})
    src["clips"] = result
    return result


def route_mock(monkeypatch, sources):
    """Mock only the external native-client boundary; actual admission and folding remain real."""
    by_hash = {s["expected_source_sha256"]: s for s in sources}

    async def respond(native_request):
        return event(by_hash[native_request.expected_source_sha256], native_request.start_seconds)

    mocked = AsyncMock(side_effect=respond)
    monkeypatch.setattr(av_build, "caption_events", mocked)
    return mocked


async def test_watch_unavailable_before_hashing_or_endpoint_work(tmp_path, monkeypatch):
    src = source(tmp_path)

    def unexpected(*args):
        raise AssertionError("unconfigured watch must do no media work")

    monkeypatch.setattr(lifecycle_inputs, "verify_source", unexpected)
    mocked = AsyncMock(side_effect=AssertionError("no route"))
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(REQUEST.validate_python({"action": "watch", "source": src}))
    assert result["status"] == "unavailable" and result["failure"] == "config"
    assert result["complete"] is False and result["costs"]["route_calls"] == []
    mocked.assert_not_awaited()


@pytest.mark.parametrize("limit, reason", [({"max_payload_bytes": 1}, "payload_limit"),
                                          ({"max_duration_seconds": 1}, "duration_limit")])
async def test_watch_declared_limits_refuse_before_acquisition(tmp_path, monkeypatch, limit, reason):
    src = source(tmp_path)
    mocked = AsyncMock()
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(REQUEST.validate_python(
        {"action": "watch", "source": src, "config": CONFIG, "limits": limit}))
    assert result["status"] == "rejected" and result["failure"] == "reject"
    assert result["dropped_clips"] == [{"clip_id": "first", "reason": reason}]
    mocked.assert_not_awaited()


async def test_watch_returns_actual_admitted_fixture_observations_not_speech_or_answers(tmp_path, monkeypatch):
    src = source(tmp_path)
    mocked = route_mock(monkeypatch, [src])
    result = await video_memory_lifecycle(REQUEST.validate_python({"action": "watch", "source": src, "config": CONFIG}))
    assert result["status"] == "complete" and result["watched_clips"] == ["first"]
    assert result["wire_payload_bytes"] is None and "answer" not in result
    assert result["observations"][0]["records"][0]["person_id"] is None
    assert result["observations"][0]["records"][0]["kind"] == "visual"
    assert result["observations"][0]["records"][0]["basis"] == "inferred"
    mocked.assert_awaited_once()


@pytest.mark.parametrize("status, failure", [(400, "reject"), (401, "config"), (403, "config"),
                                           (404, "config"), (429, "rate")])
async def test_structured_endpoint_failures_are_classified_without_retry_or_raw_message(tmp_path, monkeypatch, status, failure):
    src = source(tmp_path)

    class EndpointFailure(Exception):
        status_code = status

    mocked = AsyncMock(side_effect=EndpointFailure("SECRET_PROVIDER_ECHO"))
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(REQUEST.validate_python({"action": "watch", "source": src, "config": CONFIG}))
    assert result["failure"] == failure and result["complete"] is False
    assert result["costs"]["route_calls"][0]["status"] == "failed"
    assert "SECRET_PROVIDER_ECHO" not in json.dumps(result)
    mocked.assert_awaited_once()


async def test_hung_route_times_out_once_and_preserves_attempt(tmp_path, monkeypatch):
    src = source(tmp_path)

    async def hung(*args):
        await asyncio.Future()

    mocked = AsyncMock(side_effect=hung)
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(REQUEST.validate_python(
        {"action": "watch", "source": src, "config": CONFIG, "limits": {"timeout_seconds": 0.01}}))
    assert result["failure"] == "timeout" and len(result["costs"]["route_calls"]) == 1
    mocked.assert_awaited_once()


async def test_replay_names_missing_dropped_duplicate_clips_and_reuses_stored_evidence(tmp_path, monkeypatch):
    """GIVEN retained clips, WHEN bounded replay runs, THEN exact identities and omissions are returned."""
    src = source(tmp_path)
    retained = clips(tmp_path, src)
    clip_sources = [{"segment_id": "first", "file_path": c["path"], "expected_source_sha256": c["sha256"],
                     "expected_source_bytes": c["bytes"], "duration_seconds": min(30.0, 65.0 - c["window"] * 30)}
                    for c in retained]
    mocked = route_mock(monkeypatch, [src, *clip_sources])
    built = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    Path(retained[1]["path"]).unlink()
    mocked.reset_mock()
    result = await video_memory_lifecycle(request(tmp_path, src, "replay", av_route=CONFIG["av_route"],
                                                    clips=["first:0", "first:1", "missing:7", "first:2", "first:0"],
                                                    limits={"max_clips": 2}))
    assert result["status"] == "partial" and result["watched_clips"] == ["first:0"]
    assert result["missing_clips"] == ["missing:7", "first:1"]
    assert result["dropped_clips"] == [{"clip_id": "first:2", "reason": "clip_limit"},
                                       {"clip_id": "first:0", "reason": "duplicate"}]
    assert result["stored_evidence"]["evidence_record_ids"]
    assert state(tmp_path, src).revision == built["revision"]
    mocked.assert_awaited_once()


async def test_replay_preserves_completed_observations_when_later_clip_fails(tmp_path, monkeypatch):
    src = source(tmp_path)
    retained = clips(tmp_path, src)
    mocked = route_mock(monkeypatch, [src])
    await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src], config=CONFIG))
    calls = []

    async def partially_failing(native_request):
        calls.append(native_request.file_path)
        if len(calls) == 2:
            raise TimeoutError()
        c = retained[0]
        clip_source = {"expected_source_sha256": c["sha256"], "expected_source_bytes": c["bytes"],
                       "duration_seconds": 30.0}
        return event(clip_source)

    mocked.side_effect = partially_failing
    result = await video_memory_lifecycle(request(tmp_path, src, "replay", config=CONFIG, av_route=CONFIG["av_route"],
                                                    clips=["first:0", "first:1", "first:2"]))
    assert result["failure"] == "timeout" and result["watched_clips"] == ["first:0"]
    assert result["stopped_clips"] == ["first:1", "first:2"]
    assert len(result["observations"]) == 1 and len(calls) == 2


async def test_native_route_failure_checkpoint_retains_attempt_and_stops_later_windows(tmp_path, monkeypatch):
    src = source(tmp_path)
    failure = av_build.ProviderFailure("native client refused", {"costs": {"route_calls": [
        {"status": "failed", "error": {"category": "API_QUOTA_EXCEEDED"}, "execution": None}]}})
    mocked = AsyncMock(side_effect=failure)
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src], config=CONFIG))
    assert result["complete"] is False and result["extracted"] == 0 and result["planned"] == 3
    assert result["failure"]["kind"] == "rate"
    assert len(result["costs"]["route_calls"]) == 1
    assert result["failure"]["report"] == failure.report
    mocked.assert_awaited_once()


async def test_av_captions_never_invent_transcript_speakers_or_names(tmp_path):
    src = source(tmp_path)
    value = event(src)
    artifact = tmp_path / "caption.json"
    data = json.dumps(value).encode()
    artifact.write_bytes(data)
    src["artifacts"] = [{"kind": "av_events", "path": str(artifact), "sha256": hashlib.sha256(data).hexdigest()}]
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    saved = state(tmp_path, src)
    assert result["complete"] is True and result["planned"] == 3
    assert saved.persons == [] and saved.suggestions == []
    assert all(r.person_id is None and r.kind == "visual" for r in saved.records)


def test_checkpoint_denominator_and_order_validation():
    segment = {"source": {"segment_id": "s", "file_path": "/dummy", "expected_source_sha256": "a" * 64,
                           "expected_source_bytes": 1, "duration_seconds": 60},
               "offset_seconds": 0, "planned_windows": 2}
    with pytest.raises(ValidationError, match="chronological"):
        Checkpoint(config_sha256="b" * 64, segments=[segment], extracted=["s:1"])
    with pytest.raises(ValidationError, match="chronological"):
        Checkpoint(config_sha256="b" * 64, segments=[segment], extracted=["s:0", "s:0"])
    with pytest.raises(ValidationError, match="denominator"):
        Checkpoint(config_sha256="b" * 64, segments=[{**segment, "planned_windows": 1}])
    with pytest.raises(ValidationError, match="timeline"):
        Checkpoint(config_sha256="b" * 64, segments=[{**segment, "offset_seconds": 1}])


def test_public_request_rejects_nonfinite_unknown_and_boolean_limits(tmp_path):
    src = source(tmp_path)
    for limits in ({"timeout_seconds": float("inf")}, {"max_clips": True}, {"extra": 1}):
        with pytest.raises(ValidationError):
            REQUEST.validate_python({"action": "watch", "source": src, "limits": limits})


async def test_response_payload_ceiling_returns_reject_without_publishing_oversized_records(tmp_path, monkeypatch):
    src = source(tmp_path, duration=5)
    mocked = route_mock(monkeypatch, [src])
    result = await replay.run(REQUEST.validate_python({"action": "watch", "source": src, "config": CONFIG,
                                                       "limits": {"max_payload_bytes": 128}}))
    assert result["failure"] == "reject" and result["observations"] == []
    mocked.assert_awaited_once()


async def test_replay_uses_frozen_memory_config_with_separate_route_and_chronological_submission(tmp_path, monkeypatch):
    src = source(tmp_path)
    retained = clips(tmp_path, src)
    await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    clip_sources = [{"expected_source_sha256": c["sha256"], "expected_source_bytes": c["bytes"],
                     "duration_seconds": min(30.0, 65.0 - c["window"] * 30)} for c in retained]
    mocked = route_mock(monkeypatch, clip_sources)
    result = await video_memory_lifecycle(request(tmp_path, src, "replay", av_route=CONFIG["av_route"],
                                                    clips=["first:2", "first:0"]))
    assert result["complete"] is True and result["watched_clips"] == ["first:0", "first:2"]
    assert [c.args[0].expected_source_sha256 for c in mocked.await_args_list] == [retained[0]["sha256"], retained[2]["sha256"]]


async def test_replay_changed_clip_bytes_are_rejected_without_endpoint_work(tmp_path, monkeypatch):
    src = source(tmp_path)
    retained = clips(tmp_path, src)
    await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    Path(retained[0]["path"]).write_bytes(b"changed clip")
    mocked = AsyncMock()
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(request(tmp_path, src, "replay", av_route=CONFIG["av_route"], clips=["first:0"]))
    assert result["failure"] == "reject" and result["report"]["stale"] is True
    mocked.assert_not_awaited()


async def test_build_rejects_native_records_outside_the_requested_window(tmp_path, monkeypatch):
    src = source(tmp_path)
    mocked = AsyncMock(return_value=event(src, 31.0))
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src], config=CONFIG))
    assert result["complete"] is False and result["extracted"] == 0
    assert result["failure"]["kind"] == "reject" and state(tmp_path, src).records == []
    mocked.assert_awaited_once()


def test_decimal_source_offsets_survive_append_without_recomputing_prior_positions(tmp_path):
    sources = [REQUEST.validate_python({"action": "watch", "source": source(tmp_path, str(i), duration)}).source
               for i, duration in enumerate((5.1, 5.2, 5.3, 5.4))]
    planned = lifecycle_inputs.plan(sources[:3])
    appended = lifecycle_inputs.plan(sources[3:], planned)
    checked = Checkpoint(config_sha256="b" * 64, segments=appended)
    assert checked.segments[3].offset_seconds == planned[-1].offset_seconds + planned[-1].source.duration_seconds


async def test_stored_retrieval_payload_is_bounded_together_with_replay_observations(tmp_path, monkeypatch):
    src = source(tmp_path)
    retained = clips(tmp_path, src)
    await video_memory_lifecycle(request(tmp_path, src, "build", segments=[src]))
    c = retained[0]
    route_mock(monkeypatch, [{"expected_source_sha256": c["sha256"], "expected_source_bytes": c["bytes"],
                              "duration_seconds": 30.0}])
    result = await video_memory_lifecycle(request(tmp_path, src, "replay", av_route=CONFIG["av_route"],
                                                    clips=["first:0"], limits={"max_payload_bytes": 1000}))
    assert result["observations"] and result["watched_clips"] == ["first:0"]
    assert result["complete"] is False and result["failure"] == "reject"
    assert result["stored_evidence"]["reason"] == "response_payload_limit"


@pytest.mark.parametrize("category, failure", [("API_QUOTA_EXCEEDED", "rate"),
                                               ("PERMISSION_DENIED", "config"),
                                               ("API_INVALID_ARGUMENT", "reject"),
                                               ("NETWORK_ERROR", "timeout")])
async def test_real_native_failure_shape_retains_category_and_execution(tmp_path, monkeypatch, category, failure):
    src = source(tmp_path)
    value = {"status": "failed", "error": "diagnostics withheld", "category": category,
             "hint": "bounded native fixture", "retryable": False, "execution": {"fixture_only": True}}
    if category == "NETWORK_ERROR":
        value["error"] = "AV event submission/result failed (TimeoutError); diagnostics withheld"
    mocked = AsyncMock(return_value=value)
    monkeypatch.setattr(av_build, "caption_events", mocked)
    result = await video_memory_lifecycle(REQUEST.validate_python({"action": "watch", "source": src, "config": CONFIG}))
    assert result["failure"] == failure
    retained = result["report"]["costs"]["route_calls"][0]
    assert retained["error"]["category"] == category and retained["execution"] == value["execution"]
    mocked.assert_awaited_once()
