"""Optional owned REST contracts through MockTransport only; no socket or real key."""

from copy import deepcopy
import json
import logging

import httpx
from pydantic import ValidationError
import pytest

from video_explainer_mcp.models.narration import NarrationRequest
from video_explainer_mcp import narration_pcm as pcm
from video_explainer_mcp import narration_provider as provider
from video_explainer_mcp.narration_timing import provider_words


def configured(monkeypatch, name="minimax", **changes):
    """Explicit fixture-only enable/voice/host/key authority."""
    prefix = f"EXPLAINER_NARRATION_{name.upper()}"
    monkeypatch.setenv(prefix + "_ENABLED", "1")
    monkeypatch.setenv(prefix + "_VOICES", "fixture-voice,Cherry")
    monkeypatch.setenv(prefix + "_DOWNLOAD_HOSTS", "audio.provider.invalid")
    monkeypatch.setenv("MINIMAX_API_KEY" if name == "minimax" else "DASHSCOPE_API_KEY", "fixture-private-key")
    request = NarrationRequest(provider=name, voice="fixture-voice" if name == "minimax" else "Cherry",
                               model="speech-2.8-hd" if name == "minimax" else "qwen3-tts-flash", **changes)
    return provider.selection(request)


def subtitles(text="One."):
    return [{"text": text, "text_begin": 0, "text_end": len(text), "time_begin": 0, "time_end": 200,
             "timestamped_words": [{"word": text, "word_begin": 0, "word_end": len(text), "time_begin": 0, "time_end": 200}]}]


def completed(text="One."):
    return {"base_resp": {"status_code": 0, "status_msg": "never expose provider text"},
            "data": {"status": 2, "audio": pcm.tone(text, 1)[0].hex(),
                     "subtitle_file": "https://audio.provider.invalid/words.json?signature=private-signed-query"},
            "extra_info": {"usage_characters": len(text), "usage_voice_count": 1, "audio_length": 200}, "trace_id": "trace-safe"}


def transport(monkeypatch, handler):
    fake = httpx.MockTransport(handler)
    monkeypatch.setattr(provider, "http_client", lambda: httpx.AsyncClient(transport=fake, trust_env=False, follow_redirects=False))


async def test_minimax_exact_contract_measured_audio_and_independent_words(monkeypatch, caplog):
    selected, requests, returned = configured(monkeypatch), [], []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completed() if request.method == "POST" else subtitles())
    transport(monkeypatch, handler)
    caplog.set_level(logging.INFO, logger="httpx")
    result = await provider.synthesize("One.", selected, lambda body, info: returned.append((body, info)))
    body = json.loads(requests[0].content)
    assert body == {"model": "speech-2.8-hd", "text": "One.", "stream": False, "output_format": "hex",
                    "language_boost": "English", "subtitle_enable": True, "subtitle_type": "word",
                    "voice_setting": {"voice_id": "fixture-voice", "speed": 1.0, "vol": 1, "pitch": 0},
                    "audio_setting": {"sample_rate": 24000, "format": "wav", "channel": 1}}
    assert requests[0].url.host == "api.minimax.io" and requests[0].headers["authorization"] == "Bearer fixture-private-key"
    assert requests[1].method == "GET" and "authorization" not in requests[1].headers
    assert pcm.qualify(result["audio"])[1]["frames"] == 4800
    assert result["words"][0]["end_frame"] == 4800 and result["words"][0]["alignment"] == "provider_declared"
    assert result["usage"]["usage_characters"] == 4
    assert returned[0][0] is None and returned[1][0] == result["audio"]
    assert "private-signed-query" not in caplog.text and "fixture-private-key" not in json.dumps(result, default=lambda _: "audio")


async def test_qwen_has_no_speed_or_invented_word_alignment(monkeypatch):
    selected, requests = configured(monkeypatch, "qwen", region="cn"), []
    audio = pcm.tone("One.", 1)[0]
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"audio": {"url": "https://audio.provider.invalid/audio.wav?token=secret"}},
                                           "usage": {"characters": 4}, "request_id": "request-safe"})
        return httpx.Response(200, content=audio)
    transport(monkeypatch, handler)
    result = await provider.synthesize("One.", selected, lambda *a: None)
    assert json.loads(requests[0].content) == {"model": "qwen3-tts-flash", "input": {"text": "One.", "voice": "Cherry", "language_type": "English"}}
    assert requests[0].url.host == "dashscope.aliyuncs.com"
    assert "authorization" not in requests[1].headers and result["words"] is None
    assert result["alignment"] == "absent_selected_provider_contract"
    with pytest.raises(ValueError, match="no numeric speed"):
        configured(monkeypatch, "qwen", rate=1.5)


@pytest.mark.parametrize("field,value", [("base", None), ("base", False), ("base", 0.0), ("base", "0"),
                                       ("completion", None), ("completion", True), ("completion", 2.0), ("completion", 1)])
async def test_missing_noninteger_or_incomplete_status_never_accepts(monkeypatch, field, value):
    selected = configured(monkeypatch)
    response = completed()
    response["base_resp"]["status_code"] = value if field == "base" else 0
    if field == "completion":
        response["data"]["status"] = value
    calls = []
    transport(monkeypatch, lambda request: (calls.append(request) or httpx.Response(200, json=response)))
    with pytest.raises(provider.ProviderError) as caught:
        await provider.synthesize("One.", selected, lambda *a: pytest.fail("invalid status accepted"))
    assert caught.value.outcome == "unknown" and len(calls) == 1


@pytest.mark.parametrize("url", ["http://audio.provider.invalid/words.json", "https://unselected.invalid/words.json",
                                "https://audio.provider.invalid:443/words.json", "https://user:secret@audio.provider.invalid/words.json"])
async def test_download_fence_prevents_an_unselected_get(monkeypatch, url):
    selected, response, calls = configured(monkeypatch), completed(), []
    response["data"]["subtitle_file"] = url
    transport(monkeypatch, lambda request: (calls.append(request) or httpx.Response(200, json=response)))
    with pytest.raises(provider.ProviderError, match="url_refused"):
        await provider.synthesize("One.", selected, lambda *a: None)
    assert len(calls) == 1


async def test_redirect_and_http_error_are_terminal_without_raw_body(monkeypatch):
    selected, calls = configured(monkeypatch), []
    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json=completed())
        return httpx.Response(302, headers={"Location": "https://outside.invalid/?key=private"}, text="provider-secret-body")
    transport(monkeypatch, handler)
    with pytest.raises(provider.ProviderError) as caught:
        await provider.synthesize("One.", selected, lambda *a: None)
    assert len(calls) == 2 and caught.value.status == 302 and caught.value.outcome == "accepted"
    assert "provider-secret-body" not in str(caught.value)


async def test_timeout_is_unknown_and_post_has_no_retry(monkeypatch):
    selected, calls = configured(monkeypatch), []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("fixture-private-key https://signed.invalid/?signature=secret", request=request)
    transport(monkeypatch, handler)
    with pytest.raises(provider.ProviderError) as caught:
        await provider.synthesize("One.", selected, lambda *a: None)
    assert caught.value.outcome == "unknown" and len(calls) == 1
    assert str(caught.value) == "provider_request_outcome_unknown"


@pytest.mark.parametrize("failure", ["disabled", "voice", "host", "key", "model"])
def test_operator_configuration_refuses_before_http(monkeypatch, failure):
    configured(monkeypatch)
    if failure == "disabled":
        monkeypatch.delenv("EXPLAINER_NARRATION_MINIMAX_ENABLED")
    elif failure == "voice":
        monkeypatch.setenv("EXPLAINER_NARRATION_MINIMAX_VOICES", "other")
    elif failure == "host":
        monkeypatch.delenv("EXPLAINER_NARRATION_MINIMAX_DOWNLOAD_HOSTS")
    elif failure == "key":
        monkeypatch.delenv("MINIMAX_API_KEY")
    request = NarrationRequest(provider="minimax", voice="fixture-voice", model="unsupported" if failure == "model" else "speech-2.8-hd")
    monkeypatch.setattr(provider, "http_client", lambda: pytest.fail("HTTP attempted"))
    with pytest.raises(ValueError):
        provider.selection(request)


@pytest.mark.parametrize("change", ["text", "offset", "nan", "beyond", "order", "absent", "incomplete"])
def test_provider_words_require_actual_exact_bounded_offsets(change):
    payload = deepcopy(subtitles())
    word = payload[0]["timestamped_words"][0]
    if change == "text":
        word["word"] = "Different"
    elif change == "offset":
        word["word_end"] = 99
    elif change == "nan":
        word["time_end"] = float("nan")
    elif change == "beyond":
        word["time_end"] = 201
    elif change == "order":
        word["time_begin"] = 200
    elif change == "absent":
        payload[0]["timestamped_words"] = None
    else:
        payload[0]["text_end"] = 3
        payload[0]["text"] = "One"
    with pytest.raises(ValueError):
        provider_words(payload, "One.", 4800, 24000)


def test_provider_word_population_cannot_silently_omit_the_rest_of_the_transcript():
    payload = subtitles("One. Two.")
    payload[0]["timestamped_words"] = subtitles()[0]["timestamped_words"]
    with pytest.raises(ValueError, match="spoken text"):
        provider_words(payload, "One. Two.", 9600, 24000)


@pytest.mark.parametrize("kwargs", [{"rate": float("nan")}, {"pause_seconds": float("inf")}, {"rate": 0.4},
                                    {"provider": "minimax"}, {"voice": "fallback"}, {"model": "other"},
                                    {"action": "custom"}, {"scene_id": 1}, {"unknown": True}])
def test_small_request_model_rejects_unsupported_or_nonfinite_choices(kwargs):
    with pytest.raises(ValidationError):
        NarrationRequest(**kwargs)


async def test_usage_identifier_does_not_reflect_the_key_and_audio_is_retained_before_bad_words(monkeypatch):
    selected, response, saved = configured(monkeypatch), completed(), []
    response["trace_id"] = "fixture-private-key"
    bad = subtitles()
    bad[0]["timestamped_words"][0]["time_end"] = 500
    transport(monkeypatch, lambda request: httpx.Response(200, json=response if request.method == "POST" else bad))
    with pytest.raises(provider.ProviderError) as caught:
        await provider.synthesize("One.", selected, lambda body, details: saved.append((body, details)))
    assert caught.value.outcome == "accepted" and saved[1][0] == bytes.fromhex(response["data"]["audio"])
    assert all(details["request_id"] is None for _, details in saved)
