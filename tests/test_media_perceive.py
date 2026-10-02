"""Joint timeline and retry contracts with the actual Gemini client and mocked SDK."""

import asyncio
from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock, MagicMock

from fastmcp import Client
from google.genai import types
from google.genai.errors import APIError
from jsonschema import validate
import pytest
from pydantic import ValidationError

from video_research_mcp.client import GeminiClient
from video_research_mcp.config import update_config
from video_research_mcp.media_perception import perceive_media
from video_research_mcp.models.media_perception import AVPerceptionRequest
from video_research_mcp.tools.media_perceive import media_perceive_server


def request(**values):
    """Use fixed synthetic transport inputs; this helper does not claim media decoding."""
    return AVPerceptionRequest(**({"file_path": "/synthetic/source.mp4", "expected_source_sha256": "a" * 64,
        "instruction": "Describe independently what is seen and spoken", "start_seconds": 10,
        "end_seconds": 14, "window_seconds": 2, "dry_run": False,
        "authorize_submission": True} | values))


def answer(**values):
    """Keep model labels fixed independently of SDK payload construction."""
    return {"summary": "Separate observed-looking claims", "events": [
        {"modality": "visible", "start_seconds": 0.4, "end_seconds": 0.6,
         "description": "A red marker", "frame_indices": [0]},
        {"modality": "spoken", "start_seconds": 1.0, "end_seconds": 1.5,
         "description": "The word marker is spoken", "frame_indices": []}], "abstentions": []} | values


def response(value=None, finish="STOP", usage=True):
    """Supply concrete SDK responses so real counting, parsing and validation execute."""
    result = types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(parts=[types.Part(text=json.dumps(answer() if value is None else value))]),
        finish_reason=finish)])
    if usage:
        result.usage_metadata = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=12, candidates_token_count=5, total_token_count=17)
    return result


@pytest.fixture
def sdk(monkeypatch, clean_config):
    """Mock only provider SDK transport, leaving budget and client implementation active."""
    client = MagicMock()
    client.aio.models.count_tokens = AsyncMock(return_value=types.CountTokensResponse(total_tokens=12))
    client.aio.models.generate_content = AsyncMock(return_value=response())
    monkeypatch.setattr(GeminiClient, "get", MagicMock(return_value=client))
    return client


@pytest.fixture
def synthetic_preparation(monkeypatch):
    """Isolate provider/timeline contracts from the separately tested native preparation."""
    import video_research_mcp.media_perception_prepare as preparation

    state = {"verified": 0, "closed": False}

    async def verify():
        state["verified"] += 1

    @asynccontextmanager
    async def prepared(_):
        windows = []
        for index, start in enumerate([10, 12]):
            frame = {"actual_seconds": start + 0.5, "original_pts": 105 + index * 20,
                     "time_base": "1/10", "sha256": "b" * 64, "bytes": 3}
            windows.append({"index": index, "start_seconds": start, "end_seconds": start + 2,
                "frames": [frame], "audio": {"selected_window": {"start_seconds": start, "end_seconds": start + 2}},
                "parts": [{**frame, "kind": "image", "mime": "image/png", "data": b"png"},
                          {"kind": "audio", "mime": "audio/wav", "bytes": 3, "sha256": "c" * 64, "data": b"wav"}],
                "payload_bytes": 6, "watched_intervals": []})
        try:
            yield {"sha256": "a" * 64, "bytes": 100, "path": "/synthetic/source.mp4"}, windows, verify
        finally:
            state["closed"] = True
    monkeypatch.setattr(preparation, "prepare_media", prepared)
    return state


async def test_public_joint_timeline_binds_offsets_and_sdk_transmissions(sdk, synthetic_preparation):
    """GIVEN two windows THEN each modality retains absolute times and original support indices."""
    async with Client(media_perceive_server) as client:
        tool = (await client.list_tools())[0]
        assert tool.name == "media_perceive" and tool.annotations.open_world_hint is True
        assert tool.annotations.idempotent_hint is False
        result = await client.call_tool("media_perceive", {"request": request().model_dump(mode="json")})
        value = result.structured_content
        validate(value, tool.output_schema)
    assert value["status"] == "complete"
    assert [event["start_seconds"] for event in value["timeline"]] == [10.4, 11, 12.4, 13]
    assert [event["modality"] for event in value["timeline"]] == ["visible", "spoken"] * 2
    assert all(event["evidence_status"] == "model_inference" for event in value["timeline"])
    assert value["execution"]["provider_calls"] == 4
    assert value["execution"]["continuous_watched_coverage"] is False
    assert value["execution"]["cost_usd"] is None
    assert [w["status"] for w in value["windows"]] == ["complete", "complete"]
    assert synthetic_preparation["closed"] and synthetic_preparation["verified"] == 6
    for count, generation in zip(sdk.aio.models.count_tokens.call_args_list, sdk.aio.models.generate_content.call_args_list):
        assert count.kwargs["contents"] is generation.kwargs["contents"]
        parts = generation.kwargs["contents"].parts
        assert [p.inline_data.mime_type for p in parts if p.inline_data] == ["image/png", "audio/wav"]
        assert "window-relative seconds 0.500000000000" in parts[0].text
        assert generation.kwargs["config"].http_options.retry_options.attempts == 1
        assert generation.kwargs["config"].max_output_tokens == 2048


@pytest.mark.parametrize("dry,grant", [(True, False), (True, True), (False, False)])
async def test_dry_plan_and_absent_grant_never_contact_provider(dry, grant, sdk, synthetic_preparation):
    value = await perceive_media(request(dry_run=dry, authorize_submission=grant))
    assert value.get("status") == "planned" if dry else value["category"] == "PERMISSION_DENIED"
    assert value["execution"]["provider_calls"] == 0
    sdk.aio.models.count_tokens.assert_not_awaited()
    sdk.aio.models.generate_content.assert_not_awaited()
    assert synthetic_preparation["closed"]


@pytest.mark.parametrize("code,category", [(401, "API_PERMISSION_DENIED"), (403, "API_PERMISSION_DENIED"), (429, "API_QUOTA_EXCEEDED")])
async def test_authentication_and_quota_are_terminal(code, category, sdk, synthetic_preparation):
    sdk.aio.models.generate_content.side_effect = APIError(code, {"error": {"message": "secret body", "status": "RESOURCE_EXHAUSTED"}})
    value = await perceive_media(request())
    assert value["category"] == category and value["retryable"] is False
    assert sdk.aio.models.generate_content.await_count == 1
    assert value["execution"]["provider_calls"] == 2
    assert [w["status"] for w in value["windows"]] == ["failed", "planned"]
    assert "secret body" not in json.dumps(value)


async def test_classified_transient_then_success_retains_both_transmissions(sdk, synthetic_preparation):
    sdk.aio.models.generate_content.side_effect = [APIError(503, {"error": {"message": "temporary"}}), response(), response()]
    value = await perceive_media(request(limits={"max_calls": 6}))
    assert value["status"] == "complete"
    assert [a["status"] for a in value["execution"]["attempts"]] == ["failed", "complete", "complete"]
    assert value["execution"]["provider_calls"] == 6
    assert value["execution"]["usage_complete"] is False
    assert value["execution"]["calls"][1]["status"] == "failed_usage_unknown"


async def test_three_attempt_ceiling_and_remaining_population(sdk, synthetic_preparation):
    sdk.aio.models.generate_content.side_effect = APIError(503, {"error": {"message": "temporary"}})
    value = await perceive_media(request(limits={"max_calls": 24}))
    assert len(value["execution"]["attempts"]) == 3
    assert value["execution"]["provider_calls"] == 6
    assert sdk.aio.models.generate_content.await_count == 3
    assert value["execution"]["completed_windows"] == 0
    assert [w["status"] for w in value["windows"]] == ["failed", "planned"]


@pytest.mark.parametrize("exc", [RuntimeError("quota503timeout"), TimeoutError("503"), ValueError("503")])
async def test_unclassified_strings_and_ambiguous_timeouts_are_not_retried(exc, sdk, synthetic_preparation):
    sdk.aio.models.generate_content.side_effect = exc
    value = await perceive_media(request())
    assert "error" in value and sdk.aio.models.generate_content.await_count == 1
    assert len(value["execution"]["attempts"]) == 1


@pytest.mark.parametrize("change", [
    {"max_calls": 1}, {"max_transmitted_bytes": 1}, {"max_tokens": 2048, "max_output_tokens": 2048}])
async def test_call_byte_and_token_limits_block_generation(change, sdk, synthetic_preparation):
    value = await perceive_media(request(limits=change))
    assert "error" in value
    sdk.aio.models.generate_content.assert_not_awaited()
    assert value["execution"]["provider_calls"] <= 1


@pytest.mark.parametrize("events", [
    [{"modality": "spoken", "start_seconds": 1, "end_seconds": 3, "description": "outside"}],
    [{"modality": "visible", "start_seconds": 0, "end_seconds": 0.2, "description": "unsupported", "frame_indices": [0]}],
    [{"modality": "visible", "start_seconds": 0, "end_seconds": 2, "description": "missing", "frame_indices": [1]}],
    [{"modality": "spoken", "start_seconds": 1, "end_seconds": 1.5, "description": "later"},
     {"modality": "spoken", "start_seconds": 0, "end_seconds": 0.5, "description": "earlier"}],
    [{"modality": "visible", "start_seconds": 0, "end_seconds": 2, "description": "bool", "frame_indices": [True]}],
    [{"modality": "spoken", "start_seconds": float("nan"), "end_seconds": 2, "description": "nonfinite"}],
])
async def test_untrusted_timeline_rejects_outside_unordered_and_fabricated_support(events, sdk, synthetic_preparation):
    sdk.aio.models.generate_content.return_value = response(answer(events=events))
    value = await perceive_media(request())
    assert "error" in value and value["timeline"] == []
    assert sdk.aio.models.generate_content.await_count == 1


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY", None])
async def test_truncated_refused_or_unknown_termination_fails_without_json_repair(finish, sdk, synthetic_preparation):
    sdk.aio.models.generate_content.return_value = response(finish=finish)
    value = await perceive_media(request())
    assert "error" in value and value["timeline"] == []
    assert sdk.aio.models.generate_content.await_count == 1


async def test_empty_events_and_abstentions_remain_valid_with_unknown_usage(sdk, synthetic_preparation):
    sdk.aio.models.generate_content.return_value = response(answer(events=[], abstentions=["No supported evidence"]), usage=False)
    value = await perceive_media(request())
    assert value["status"] == "complete" and value["timeline"] == []
    assert len(value["abstentions"]) == 2
    assert value["execution"]["measured_total_tokens"] is None
    assert value["execution"]["usage_complete"] is False


async def test_account_and_settings_drift_between_count_and_generation_blocks_dispatch(sdk, synthetic_preparation):
    async def count(**_):
        update_config(gemini_api_key="replacement-config-key")
        return types.CountTokensResponse(total_tokens=12)
    sdk.aio.models.count_tokens.side_effect = count
    value = await perceive_media(request())
    assert "error" in value and value["execution"]["provider_calls"] == 1
    sdk.aio.models.generate_content.assert_not_awaited()


@pytest.mark.parametrize("failure", [False, True])
async def test_configured_secret_is_removed_from_transcripts_and_errors(failure, sdk, synthetic_preparation):
    secret = "configured/private+credential"
    update_config(gemini_api_key=secret)
    if failure:
        sdk.aio.models.generate_content.side_effect = APIError(403, {"error": {"message": "Authorization: " + secret}})
    else:
        sdk.aio.models.generate_content.return_value = response(answer(summary=secret,
            events=[{"modality": "spoken", "start_seconds": 0, "end_seconds": 1, "description": secret}],
            abstentions=[secret]))
    value = await perceive_media(request(instruction=secret))
    serialized = json.dumps(value)
    assert secret not in serialized and "configured%2Fprivate%2Bcredential" not in serialized
    assert secret not in sdk.aio.models.generate_content.call_args.kwargs["contents"].model_dump_json()
    assert GeminiClient.get.call_args.kwargs["api_key"] == secret


async def test_overall_deadline_joins_preparation(sdk, synthetic_preparation):
    async def slow(**_):
        await asyncio.sleep(1)
    sdk.aio.models.generate_content.side_effect = slow
    value = await perceive_media(request(limits={"timeout_seconds": 0.01}))
    assert "error" in value and synthetic_preparation["closed"]
    assert value["execution"]["provider_calls"] == 2


async def test_actual_task_cancellation_joins_preparation_without_retry(sdk, synthetic_preparation):
    entered = asyncio.Event()

    async def interrupted(**_):
        entered.set()
        await asyncio.Event().wait()
    sdk.aio.models.generate_content.side_effect = interrupted
    task = asyncio.create_task(perceive_media(request()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert synthetic_preparation["closed"]
    assert sdk.aio.models.generate_content.await_count == 1


async def test_provider_json_byte_limit_rejects_otherwise_bounded_fields(sdk, synthetic_preparation):
    events = [{"modality": "spoken", "start_seconds": 0, "end_seconds": 1,
               "description": "x" * 2000} for _ in range(100)]
    sdk.aio.models.generate_content.return_value = response(answer(events=events))
    value = await perceive_media(request())
    assert "error" in value and value["timeline"] == []
    assert sdk.aio.models.generate_content.await_count == 1


@pytest.mark.parametrize("values", [{"start_seconds": True}, {"end_seconds": float("inf")},
    {"dry_run": "false"}, {"authorize_submission": 1}, {"window_seconds": 31},
    {"end_seconds": 10}, {"limits": {"max_calls": 25}}])
def test_strict_requests_reject_nonfinite_coercion_and_excessive_limits(values):
    with pytest.raises(ValidationError):
        request(**values)
