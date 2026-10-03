"""Four task workflows through real budget/client code and mocked SDK/native preparation."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock

from google.genai import types
from google.genai.errors import APIError
from pydantic import ValidationError
import pytest

from tests.test_av_event_support import occurrence, window_fixture
from video_research_mcp.av_events import analyze_music, caption_events, count_events, ground_events
from video_research_mcp.client import GeminiClient
from video_research_mcp.config import update_config
from video_research_mcp.models.av_events import (AnalyzeMusicRequest, AVEventsFailure, AVEventsResponse,
    CaptionEventsRequest, CountEventsRequest, GroundEventsRequest)
from video_research_mcp.models.media_perception import AVPerceptionRequest


def request(kind=CountEventsRequest, **values):
    """Fix exact source and selection independent of task result population."""
    data = {"file_path": "/synthetic/source.mp4", "expected_source_sha256": "a" * 64, "start_seconds": 10,
            "end_seconds": 14, "window_seconds": 2, "dry_run": False, "authorize_submission": True}
    if kind is CountEventsRequest:
        data["target"] = "cue"
    if kind is GroundEventsRequest:
        data["query"] = "cue"
    return kind(**(data | values))


@pytest.mark.parametrize("kind", [CaptionEventsRequest, CountEventsRequest, GroundEventsRequest, AnalyzeMusicRequest])
@pytest.mark.parametrize("fps", [0.1, 4.5, 30])
def test_inherited_frame_rate_contract_and_public_schema(kind, fps):
    selected = request(kind, fps=fps)
    assert selected.fps == fps
    field = kind.model_json_schema()["properties"]["fps"]
    assert (field["minimum"], field["maximum"], field["default"]) == (0.1, 30, 1)
    assert request(kind).fps == 1
    base = AVPerceptionRequest.model_validate(request(CaptionEventsRequest, fps=fps).model_dump())
    assert base.fps == fps and AVPerceptionRequest.model_json_schema()["properties"]["fps"] == field


@pytest.mark.parametrize("run,kind", [(caption_events, CaptionEventsRequest), (count_events, CountEventsRequest),
    (ground_events, GroundEventsRequest), (analyze_music, AnalyzeMusicRequest)])
@pytest.mark.parametrize("fps", [30.01, 0.09, float("nan"), float("inf"), -float("inf"), True, "30"])
async def test_invalid_rate_rejected_before_source_or_provider(run, kind, fps, sdk, preparation):
    values = request(kind).model_dump() | {"fps": fps}
    with pytest.raises(ValidationError):
        await run(values)
    assert preparation["requests"] == []
    sdk.aio.models.count_tokens.assert_not_awaited()
    sdk.aio.models.generate_content.assert_not_awaited()


def value(field="occurrences", **values):
    """Use one fused occurrence as the independent record-count oracle."""
    return {"summary": "One synthetic AV cue", "outcome": "events", field: [occurrence()], "abstentions": []} | values


def response(answer=None, *, finish="STOP", usage=True):
    """Mock only SDK replies, retaining genuine schema parsing, finish and accounting gates."""
    result = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
        parts=[types.Part(text=json.dumps(value() if answer is None else answer))]), finish_reason=finish)])
    if usage:
        result.usage_metadata = types.GenerateContentResponseUsageMetadata(prompt_token_count=12,
            candidates_token_count=5, total_token_count=17)
    return result


@pytest.fixture
def sdk(monkeypatch, clean_config):
    """Keep real client and bounded reservation code; no provider/network transport."""
    client = MagicMock()
    client.aio.models.count_tokens = AsyncMock(return_value=types.CountTokensResponse(total_tokens=12))
    client.aio.models.generate_content = AsyncMock(return_value=response())
    monkeypatch.setattr(GeminiClient, "get", MagicMock(return_value=client))
    return client


@pytest.fixture
def preparation(monkeypatch):
    """Declare exact synthetic preparation and verify immutable buffers plus current source."""
    import video_research_mcp.media_perception_prepare as module

    state = {"verified": 0, "closed": False, "requests": [], "windows": [window_fixture(0, 10), window_fixture(1, 12)],
             "source": {"sha256": "a" * 64, "bytes": 100, "path": "/synthetic/source.mp4",
                        "has_video": True, "has_audio": True}, "mutation": False, "close_mutation": False}

    async def verify():
        state["verified"] += 1
        if state["mutation"]:
            raise ValueError("Synthetic source revision changed")
        for window in state["windows"]:
            for part in window["parts"]:
                if len(part["data"]) != part["bytes"] or hashlib.sha256(part["data"]).hexdigest() != part["sha256"]:
                    raise ValueError("Retained payload bytes changed")

    @asynccontextmanager
    async def prepared(selected_request):
        state["requests"].append(selected_request)
        try:
            yield state["source"], state["windows"], verify
            if state["close_mutation"]:
                raise ValueError("Source revision changed during final snapshot join")
            await verify()
        finally:
            state["closed"] = True

    monkeypatch.setattr(module, "prepare_media", prepared)
    return state


async def test_count_fused_records_once_and_retain_cross_window_boundaries(sdk, preparation):
    result = await count_events(request())
    AVEventsResponse.model_validate(result)
    assert result["count"] == result["count_so_far"] == 2
    assert [r["start_seconds"] for r in result["records"]] == [10.25, 12.25]
    assert len({r["record_id"] for r in result["records"]}) == 2
    assert all(r["basis"] == "both" and r["audio_support"] and r["visual_support"] for r in result["records"])
    assert result["execution"]["provider_calls"] == 4 and preparation["closed"]
    assert result["provenance"]["cross_window_identity_merge"] is False
    assert result["provenance"]["count_is_physical_event_truth"] is False


async def test_overlapping_events_are_not_merged_or_dropped(sdk, preparation):
    sdk.aio.models.generate_content.return_value = response(value(occurrences=[occurrence(),
        occurrence(start_seconds=0.3, description="Separate overlapping cue")]))
    result = await count_events(request())
    assert result["count"] == 4 and len(result["records"]) == 4


async def test_second_window_failure_retains_completed_count_and_all_planned_windows(sdk, preparation):
    sdk.aio.models.generate_content.side_effect = [response(), APIError(403, {"error": {"message": "raw secret"}})]
    result = await count_events(request())
    AVEventsFailure.model_validate(result)
    assert result["status"] == result["outcome"] == "partial" and result["count"] is None
    assert result["count_so_far"] == 1 and len(result["records"]) == 1
    assert [w["status"] for w in result["windows"]] == ["complete", "failed"]
    assert result["execution"]["prepared_windows"] == 2 and result["execution"]["completed_windows"] == 1
    assert result["category"] == "API_PERMISSION_DENIED" and "raw secret" not in json.dumps(result)


@pytest.mark.parametrize("outcome,reasons,count", [("empty", [], 0), ("abstained", ["Cue is ambiguous"], None)])
async def test_valid_empty_and_explicit_abstention_have_different_count_meanings(outcome, reasons, count, sdk, preparation):
    sdk.aio.models.generate_content.return_value = response(value(occurrences=[], outcome=outcome, abstentions=reasons))
    result = await count_events(request())
    assert result["status"] == "complete" and result["outcome"] == outcome
    assert result["count"] == count and result["records"] == []
    assert len(result["abstentions"]) == 2 * len(reasons)


@pytest.mark.parametrize("dry,grant", [(True, False), (True, True), (False, False)])
async def test_dry_plan_and_missing_grant_block_all_provider_work(dry, grant, sdk, preparation):
    result = await count_events(request(dry_run=dry, authorize_submission=grant))
    assert result["count"] is None and result["records"] == []
    assert result["status"] == ("planned" if dry else "failed")
    assert result["execution"]["provider_calls"] == 0 and preparation["closed"]
    sdk.aio.models.count_tokens.assert_not_awaited()
    sdk.aio.models.generate_content.assert_not_awaited()


async def test_missing_configured_account_fails_before_network(sdk, preparation, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    update_config(gemini_api_key="")
    result = await count_events(request())
    assert result["category"] == "PERMISSION_DENIED" and result["count"] is None
    sdk.aio.models.count_tokens.assert_not_awaited()


async def test_grounding_preserves_all_records_and_explicit_top_k_population(sdk, preparation):
    matches = [occurrence(score=0.2), occurrence(score=0.8, description="Higher scored cue")]
    sdk.aio.models.generate_content.return_value = response(value("matches", matches=matches))
    result = await ground_events(request(GroundEventsRequest, top_k=1))
    assert len(result["records"]) == 4 and len(result["matches"]) == 1
    assert result["matches"][0]["score"] == 0.8
    assert result["grounding_population"]["available"] == 4
    assert result["grounding_population"]["retained"] == 1 and result["grounding_population"]["truncated"] == 3
    assert len(result["grounding_population"]["truncated_ids"]) == 3
    assert result["count"] is None and result["provenance"]["scores_calibrated"] is False


async def test_caption_is_a_distinct_schema_and_keeps_nonspeech_label(sdk, preparation):
    sdk.aio.models.generate_content.return_value = response(value("events", events=[
        occurrence(basis="audio", frame_indices=[], description="A nonspeech click")]))
    result = await caption_events(request(CaptionEventsRequest))
    assert result["operation"] == "media_caption_events" and result["count"] is None
    assert [r["description"] for r in result["records"]] == ["A nonspeech click"] * 2
    assert all(r["visual_support"] == [] for r in result["records"])


async def test_music_from_video_uses_audio_only_and_keeps_inferred_section_properties(sdk, preparation):
    preparation["windows"] = [window_fixture(0, 10, visual=False), window_fixture(1, 12, visual=False)]
    section = occurrence(basis="audio", frame_indices=[], label="Pulse", properties={
        "instruments": ["tone"], "moods": ["steady"], "tags": ["synthetic"], "tempo_bpm": 120})
    sdk.aio.models.generate_content.return_value = response(value("sections", sections=[section]))
    result = await analyze_music(request(AnalyzeMusicRequest))
    assert preparation["requests"][0].media_type == "audio"
    assert result["source"]["has_video"] is True and result["task"] == "music"
    assert all(r["basis"] == "audio" and r["music"]["properties"]["tempo_bpm"] == 120 for r in result["records"])
    for call in sdk.aio.models.generate_content.call_args_list:
        parts = call.kwargs["contents"].parts
        assert [p.inline_data.mime_type for p in parts if p.inline_data] == ["audio/wav"]
        assert parts[0].text.startswith("Audio evidence:") and "Spoken audio" not in parts[0].text


@pytest.mark.parametrize("missing", [True, False])
async def test_music_refuses_missing_audio_and_visual_payload_before_dispatch(missing, sdk, preparation):
    preparation["windows"] = [window_fixture(audio=not missing, visual=True)]
    result = await analyze_music(request(AnalyzeMusicRequest))
    assert result["status"] == "failed" and result["records"] == []
    sdk.aio.models.count_tokens.assert_not_awaited()


@pytest.mark.parametrize("change", ["source", "buffer", "account"])
async def test_changed_bound_inputs_or_account_after_count_blocks_generation(change, sdk, preparation):
    async def counted(**_):
        if change == "source":
            preparation["mutation"] = True
        elif change == "buffer":
            preparation["windows"][0]["parts"][0]["data"] = b"different"
        else:
            update_config(gemini_api_key="different-fake-account")
        return types.CountTokensResponse(total_tokens=12)
    sdk.aio.models.count_tokens.side_effect = counted
    result = await count_events(request())
    assert "error" in result and result["count"] is None and result["records"] == []
    sdk.aio.models.generate_content.assert_not_awaited()
    assert preparation["closed"]


async def test_final_snapshot_join_failure_does_not_promote_total(sdk, preparation):
    preparation["close_mutation"] = True
    result = await count_events(request())
    assert result["status"] == "partial" and result["count"] is None
    assert result["count_so_far"] == 2 and preparation["closed"]


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY", None])
async def test_unfinished_or_refused_generation_never_repaired_or_counted(finish, sdk, preparation):
    sdk.aio.models.generate_content.return_value = response(finish=finish)
    result = await count_events(request())
    assert result["status"] == "failed" and result["records"] == [] and result["count"] is None
    assert sdk.aio.models.generate_content.await_count == 1 and len(result["execution"]["attempts"]) == 1


async def test_cancel_joins_preparation_without_swallowing_cancellation(sdk, preparation):
    entered = asyncio.Event()
    async def blocked(**_):
        entered.set()
        await asyncio.Future()
    sdk.aio.models.generate_content.side_effect = blocked
    task = asyncio.create_task(count_events(request()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert preparation["closed"]


async def test_deadline_closes_owned_preparation_and_retains_unknown_usage(sdk, preparation):
    async def blocked(**_):
        await asyncio.Future()
    sdk.aio.models.generate_content.side_effect = blocked
    result = await count_events(request(limits={"timeout_seconds": 0.05}))
    assert result["category"] == "NETWORK_ERROR" and result["count"] is None
    assert preparation["closed"] and result["execution"]["usage_complete"] is False
    assert result["execution"]["calls"][-1]["status"] == "usage_unknown"


async def test_config_secret_and_provider_details_are_redacted(sdk, preparation):
    update_config(gemini_api_key="private-unit-secret")
    sdk.aio.models.generate_content.return_value = response(value(summary="private-unit-secret",
        occurrences=[occurrence(description="private-unit-secret")]))
    result = await count_events(request())
    assert "private-unit-secret" not in json.dumps(result)
    assert result["records"][0]["description"] == "[redacted]"
