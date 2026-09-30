"""Real vision workflows with only provider SDK/wire boundaries replaced."""

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from google.genai import types
from PIL import Image
import pytest

from video_research_mcp.client import GeminiClient
from video_research_mcp.config import get_config, update_config
from video_research_mcp.models.vision import VisionBackend, VisionRequest
from video_research_mcp.vision_analysis import analyze_vision
from tests.test_vision_workflows import source_request, wire_reply
from tests.native_media_fixtures import build_fixtures


@pytest.fixture
def source(tmp_path, clean_config):
    image = tmp_path / "own.png"
    Image.new("RGB", (16, 12), "red").save(image)
    update_config(local_file_access_root=str(tmp_path), cache_dir=str(tmp_path / "cache"))
    return image


@pytest.fixture
def sdk(monkeypatch):
    client = MagicMock()
    client.aio.models.count_tokens = AsyncMock(
        return_value=types.CountTokensResponse(total_tokens=12)
    )
    client.aio.models.generate_content = AsyncMock(
        return_value=types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    finish_reason=types.FinishReason.STOP,
                    content=types.Content(
                        parts=[types.Part(text=json.dumps({"answer": "own", "regions": []}))]
                    ),
                )
            ],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=12, candidates_token_count=8, total_token_count=20
            ),
        )
    )
    client.selected_keys = []
    def selected(*, api_key=None):
        client.selected_keys.append(api_key)
        return client
    monkeypatch.setattr(GeminiClient, "get", selected)
    return client


def request(source, **kwargs):
    """Authorize only the controlled provider boundary, with an exact fixture digest."""
    return VisionRequest(
        sources=[source_request(source)],
        instruction="Read source",
        dry_run=False,
        authorize_submission=True,
        **kwargs,
    )


async def test_gemini_actual_payload_count_budget_and_no_hidden_retry(source, sdk):
    result = await analyze_vision(request(source), "ocr")
    assert result["status"] == "complete", result
    sdk.aio.models.count_tokens.assert_awaited_once()
    sdk.aio.models.generate_content.assert_awaited_once()
    sent = sdk.aio.models.generate_content.call_args.kwargs
    counted = sdk.aio.models.count_tokens.call_args.kwargs
    assert counted["contents"] == sent["contents"]
    parts = sent["contents"].parts
    pixels = next(p.inline_data.data for p in parts if p.inline_data)
    assert hashlib.sha256(pixels).hexdigest() == result["payload_receipt"][0]["sha256"]
    config = sent["config"]
    assert config.max_output_tokens == 2048 and config.http_options.retry_options.attempts == 1
    assert not config.system_instruction and not config.tools
    assert result["execution"]["provider_calls"] == 2
    assert result["execution"]["measured_total_tokens"] == 20
    assert result["execution"]["image_transmissions"] == 2
    assert "requested_windows" not in result["execution"]
    assert result["provenance"]["ocr_text"] == "model_inference"


@pytest.mark.parametrize(
    "failure",
    [
        "call_cap",
        "unknown_count",
        "small_tokens",
        "truncated",
        "failed",
        "overrun",
        "config_change",
    ],
)
async def test_gemini_denials_refusals_and_failures_do_not_retry(source, sdk, failure):
    options = {}
    if failure == "call_cap":
        options["limits"] = {"max_calls": 1}
    if failure == "unknown_count":
        sdk.aio.models.count_tokens.return_value.total_tokens = None
    if failure == "small_tokens":
        options["limits"] = {"max_tokens": 2048}
    if failure == "truncated":
        sdk.aio.models.generate_content.return_value.candidates[
            0
        ].finish_reason = types.FinishReason.MAX_TOKENS
    if failure == "failed":
        sdk.aio.models.generate_content.side_effect = RuntimeError("private provider diagnostics")
    if failure == "overrun":
        sdk.aio.models.generate_content.return_value.usage_metadata.total_token_count = 200000
    if failure == "config_change":

        async def change(**kw):
            update_config(default_model="configured-new-model")
            return types.CountTokensResponse(total_tokens=12)

        sdk.aio.models.count_tokens.side_effect = change
    result = await analyze_vision(request(source, **options), "vision_chat")
    assert "error" in result and not result["retryable"]
    assert sdk.aio.models.count_tokens.await_count <= 1
    assert sdk.aio.models.generate_content.await_count == int(
        failure in {"truncated", "failed", "overrun"}
    )
    assert not list((source.parent / "cache/media/views").iterdir())
    assert "private provider diagnostics" not in json.dumps(result)


async def test_gemini_dry_plan_skips_sdk_count_and_inference(source, sdk):
    value = request(source).model_copy(update={"dry_run": True})
    result = await analyze_vision(value, "vision_chat")
    assert result["status"] == "planned"
    sdk.aio.models.count_tokens.assert_not_awaited()
    sdk.aio.models.generate_content.assert_not_awaited()


async def test_strict_custom_schema_rejects_extra_model_fields_without_retry(source, sdk):
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    result = await analyze_vision(request(source, output_schema=schema), "vision_chat")
    assert "error" in result
    sdk.aio.models.generate_content.assert_awaited_once()


@pytest.fixture
def temporary_profile(monkeypatch):
    monkeypatch.setenv("VISION_QWEN_API_KEY", "own-mock-key")
    update_config(
        vision_backends={
            "temporary": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "explicit-model",
                "api_key_env": "VISION_QWEN_API_KEY",
                "capabilities": ["images", "video", "structured_json"],
                "video_delivery": "dashscope_temporary",
                "upload_policy_url": "https://dashscope.aliyuncs.com/api/v1/uploads",
            }
        }
    )


@pytest.fixture
async def video(source):
    """Build original development media through the independently declared fixture."""
    value = await build_fixtures(source.parent / "videos")
    return Path(value["fixtures"]["cfr"]["path"])


def policy_reply(host="https://owned-bucket.oss-cn-beijing.aliyuncs.com"):
    """Return a bounded selected-account temporary policy from a wire mock."""
    return 200, json.dumps(
        {
            "data": {
                "upload_host": host,
                "upload_dir": "own-prefix",
                "oss_access_key_id": "temporary-policy-key",
                "signature": "temporary-policy-signature",
                "policy": "temporary-policy",
                "x_oss_object_acl": "private",
                "x_oss_forbid_overwrite": "true",
            }
        }
    ).encode()


async def test_temporary_dry_plan_and_call_cap_send_nothing(
    source, video, temporary_profile, monkeypatch
):
    wire = AsyncMock()
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    req = VisionRequest(
        sources=[source_request(video, kind="video")], instruction="Describe", backend="temporary"
    )
    plan = await analyze_vision(req, "vision_chat")
    assert plan["status"] == "planned" and plan["execution"]["planned_calls"] == 3
    assert plan["execution"]["submission_within_call_limit"] is False
    denied = await analyze_vision(
        req.model_copy(update={"dry_run": False, "authorize_submission": True}), "vision_chat"
    )
    assert "error" in denied and not wire.called
    assert plan["payload_receipt"][0]["upload_attempted"] is False


@pytest.mark.parametrize("failure", [None, "policy_host", "upload", "generation"])
async def test_temporary_upload_exact_account_origins_and_retained_attempts(
    source, video, temporary_profile, monkeypatch, failure
):
    observed = []

    async def wire(url, **kw):
        observed.append((url, kw))
        if len(observed) == 1:
            assert (
                url
                == "https://dashscope.aliyuncs.com/api/v1/uploads?action=getPolicy&model=explicit-model"
            )
            assert kw["headers"]["Authorization"] == "Bearer own-mock-key" and kw["method"] == "GET"
            return policy_reply(
                "https://untrusted.example"
                if failure == "policy_host"
                else "https://owned-bucket.oss-cn-beijing.aliyuncs.com"
            )
        if len(observed) == 2:
            assert url == "https://owned-bucket.oss-cn-beijing.aliyuncs.com"
            assert "Authorization" not in kw["headers"] and kw["method"] == "POST"
            assert video.read_bytes() in kw["content"] and b"own-mock-key" not in kw["content"]
            assert b"temporary-policy-signature" in kw["content"]
            if failure == "upload":
                raise RuntimeError("unknown upload outcome secret")
            return 200, b""
        assert url == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        assert kw["headers"]["X-DashScope-OssResourceResolve"] == "enable"
        body = json.loads(kw["content"])
        assert body["model"] == "explicit-model"
        assert body["messages"][0]["content"][1]["video_url"]["url"].startswith("oss://own-prefix/")
        if failure == "generation":
            return 503, b"unknown generation secret"
        return wire_reply(
            usage={
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
                "untrusted_diagnostic": "own-mock-key",
            }
        )

    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    req = VisionRequest(
        sources=[source_request(video, kind="video")],
        instruction="Describe",
        backend="temporary",
        dry_run=False,
        authorize_submission=True,
        limits={"max_calls": 3},
    )
    result = await analyze_vision(req, "vision_chat")
    assert len(observed) == {"policy_host": 1, "upload": 2}.get(failure, 3)
    assert result["execution"]["provider_calls"] == len(observed)
    assert result.get("status") == "complete" if failure is None else "error" in result
    assert result["payload_receipt"][0]["upload_attempted"] is (failure != "policy_host")
    if failure != "policy_host":
        assert len(result["uploads"]) == 1
        upload = result["uploads"][0]
        assert upload["upload_origin"] == "https://owned-bucket.oss-cn-beijing.aliyuncs.com"
        assert upload["source_sha256"] == source_request(video)["expected_source_sha256"]
        assert upload["deletion_verified"] is upload["retention_verified"] is False
        assert upload["expiry_seconds"] is None and upload["region_availability"] == "unverified"
        assert upload["status"] == (
            "attempted_upload_unknown" if failure == "upload" else "uploaded"
        )
    assert "own-mock-key" not in json.dumps(
        result
    ) and "unknown upload outcome secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "profile",
    [
        {"base_url": "http://example.com/v1"},
        {"base_url": "https://127.0.0.1/v1"},
        {"base_url": "http://localhost/v1", "local": True},
        {"base_url": "https://user:secret@server/v1"},
        {"base_url": "https://example.com/v1?secret=key"},
        {
            "base_url": "https://example.com/v1",
            "video_delivery": "dashscope_temporary",
            "upload_policy_url": "https://example.com/api/v1/uploads",
            "api_key_env": "VISION_QWEN_API_KEY",
        },
    ],
)
def test_configured_origin_boundary_rejects_unsafe_or_borrowed_upload_routes(profile):
    with pytest.raises(ValueError):
        VisionBackend(model="own", capabilities=["images", "structured_json"], **profile)


async def test_backend_changed_after_generation_retains_call_failure(source, monkeypatch):
    update_config(
        vision_backends={
            "local": {
                "base_url": "http://127.0.0.1:8123/v1",
                "model": "old",
                "local": True,
                "capabilities": ["images", "structured_json"],
            }
        }
    )

    async def wire(*args, **kwargs):
        get_config().vision_backends["local"].model = "new"
        return wire_reply()

    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    result = await analyze_vision(request(source, backend="local"), "vision_chat")
    assert "error" in result and result["execution"]["provider_calls"] == 1


async def test_custom_schema_nonfinite_model_json_fails_before_success(source, sdk):
    sdk.aio.models.generate_content.return_value.candidates[0].content.parts[
        0
    ].text = '{"value": NaN}'
    schema = {"type": "object", "properties": {"value": {"type": "number"}}, "required": ["value"]}
    result = await analyze_vision(request(source, output_schema=schema), "vision_chat")
    assert "error" in result
    sdk.aio.models.generate_content.assert_awaited_once()


@pytest.mark.parametrize("setting", ["credential_fallback", "temperature"])
async def test_gemini_effective_config_change_between_count_and_generation_blocks(
    source, sdk, monkeypatch, setting
):
    update_config(default_model="gemini-3.1-pro-preview")
    if setting == "credential_fallback":
        update_config(gemini_api_key="")
        monkeypatch.setenv("GEMINI_API_KEY", "owned-initial-key")

    async def changed(**kwargs):
        if setting == "credential_fallback":
            monkeypatch.setenv("GEMINI_API_KEY", "owned-changed-key")
        else:
            update_config(default_temperature=0.25)
        return types.CountTokensResponse(total_tokens=12)

    sdk.aio.models.count_tokens.side_effect = changed
    result = await analyze_vision(request(source), "vision_chat")
    assert "error" in result
    sdk.aio.models.count_tokens.assert_awaited_once()
    sdk.aio.models.generate_content.assert_not_awaited()
    assert result["execution"]["provider_calls"] == 1


async def test_gemini_credential_fallback_and_sampling_settings_are_in_request_binding(
    source, sdk, monkeypatch
):
    update_config(gemini_api_key="", default_model="gemini-3.1-pro-preview")
    monkeypatch.setenv("GEMINI_API_KEY", "owned-initial-key")
    req = request(source).model_copy(update={"dry_run": True})
    first = await analyze_vision(req, "vision_chat")
    monkeypatch.setenv("GEMINI_API_KEY", "owned-changed-key")
    second = await analyze_vision(req, "vision_chat")
    update_config(default_temperature=0.25)
    third = await analyze_vision(req, "vision_chat")
    assert len({value["request_sha256"] for value in (first, second, third)}) == 3
    sdk.aio.models.count_tokens.assert_not_awaited()


async def test_gemini_selected_account_is_passed_to_actual_client(source, sdk, monkeypatch):
    update_config(gemini_api_key="")
    monkeypatch.setenv("GEMINI_API_KEY", "owned-selected-account")
    result = await analyze_vision(request(source), "vision_chat")
    assert result["status"] == "complete", result
    assert sdk.selected_keys == ["owned-selected-account"]


async def test_gemini_nonsampling_temperature_change_does_not_rebind(source, sdk):
    update_config(default_model="gemini-3.8-flash")
    req = request(source)
    first = await analyze_vision(req.model_copy(update={"dry_run": True}), "vision_chat")
    async def changed(**kwargs):
        update_config(default_temperature=0.25)
        return types.CountTokensResponse(total_tokens=12)
    sdk.aio.models.count_tokens.side_effect = changed
    result = await analyze_vision(req, "vision_chat")
    assert result["status"] == "complete", result
    assert result["request_sha256"] == first["request_sha256"]
    assert sdk.aio.models.generate_content.call_args.kwargs["config"].temperature is None


async def test_gemini_absent_selected_account_makes_zero_provider_calls(source, sdk, monkeypatch):
    update_config(gemini_api_key="")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = await analyze_vision(request(source), "vision_chat")
    assert "error" in result and result["execution"]["provider_calls"] == 0
    sdk.aio.models.count_tokens.assert_not_awaited()
    sdk.aio.models.generate_content.assert_not_awaited()
