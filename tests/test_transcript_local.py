"""Timed loopback dispatch boundaries and existing absolute export/recovery behavior."""

import asyncio
import base64
import json
from pathlib import Path

import pytest

from tests.test_transcript_workflow import local as local, prepare_stub, request, sha
from video_research_mcp import transcript as workflow, transcript_provider as provider
from video_research_mcp.models.transcript import ASRService


def service(**updates):
    """Configure the one explicit local protocol with an independently supplied digest."""
    return ASRService(base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True,
                      protocol="faster_whisper_v1", expected_descriptor_sha256="d" * 64, **updates)


def reply(content):
    """Return a bounded model answer tied to the submitted WAV and hints."""
    submitted = json.loads(content)
    assert sha(base64.b64decode(submitted["audio"].split(",")[1])) == submitted["audio_sha256"]
    return {"protocol": "faster_whisper_v1", "answer": {"outcome": "transcript", "abstentions": [],
        "segments": [{"start_seconds": .1, "end_seconds": .6, "text": "Hallo wereld", "speaker_id": None,
            "words": [{"text": "Hallo", "start_seconds": .1, "end_seconds": .3},
                      {"text": "wereld", "start_seconds": .4, "end_seconds": .6}]}]},
        "receipt": {"descriptor_sha256": "d" * 64, "audio_sha256": submitted["audio_sha256"],
            "audio_duration_seconds": 1.5, "settings": {"language": submitted["language"],
                "hotwords": " ".join(submitted["glossary"]) or None, "word_timestamps": True},
            "speech_accuracy_verified": False, "word_alignment_verified": False, "speaker_identity_verified": False}}


async def test_timed_local_words_export_absolute_clock_and_bound_readback(local, monkeypatch):
    """GIVEN a measured nonzero WAV origin THEN service times become absolute inferred words."""
    prepare_stub(monkeypatch, shift=.5)
    local[2].asr_service = service()
    calls = []

    async def exchange(url, *, content, headers, method, local):
        assert url.endswith("/v1/transcribe") and local and method == "POST"
        assert headers == {"Content-Type": "application/json"}
        calls.append(json.loads(content))
        return 200, json.dumps(reply(content)).encode()

    monkeypatch.setattr(provider, "exchange", exchange)
    typed = request(local, backend="faster_whisper", local_only=True, language="nl", glossary=["wereld"],
                    start_seconds=2, end_seconds=4, dry_run=False, authorize_submission=True,
                    require_word_alignment=True, export_formats=["json", "text", "srt", "vtt", "tsv"])
    result = await workflow.transcribe(typed)
    assert result["status"] == "complete" and len(calls) == 1
    assert result["segments"][0]["words"][0]["start_seconds"] == 2.6
    assert result["segments"][0]["speaker_id"] is None
    assert result["attempts"][0]["actual_backend"] == "faster_whisper"
    assert result["attempts"][0]["inference_receipt"]["word_alignment_verified"] is False
    assert result["execution"]["service_calls"] == result["attempts"]
    directory = Path(result["receipt"]["directory"])
    assert "00:00:02,600" in (directory / "transcript.srt").read_text()
    restored = await workflow.transcribe(typed.model_copy(update={"action": "readback", "expected_receipt_sha256": result["receipt"]["sha256"]}))
    assert restored["segments"] == result["segments"] and len(calls) == 1


@pytest.mark.parametrize("mutation", ["descriptor", "audio", "duration", "language", "glossary", "accuracy", "word", "speaker"])
async def test_timed_receipt_drift_retains_failed_attempt_without_fabricated_words(local, monkeypatch, mutation):
    """GIVEN changed identity/settings/evidence THEN the workflow retains failure and no transcript."""
    prepare_stub(monkeypatch, shift=.5)
    local[2].asr_service = service()

    async def exchange(*_, content, **kwargs):
        value = reply(content)
        receipt = value["receipt"]
        if mutation in {"descriptor", "audio"}:
            receipt[mutation + "_sha256"] = "0" * 64
        elif mutation == "duration":
            receipt["audio_duration_seconds"] = 2
        elif mutation == "language":
            receipt["settings"]["language"] = "en"
        elif mutation == "glossary":
            receipt["settings"]["hotwords"] = "changed"
        elif mutation == "accuracy":
            receipt["word_alignment_verified"] = True
        elif mutation == "word":
            value["answer"]["segments"][0]["words"][0]["end_seconds"] = 8
        else:
            value["answer"]["segments"][0]["speaker_id"] = "verified-person"
        return 200, json.dumps(value).encode()

    monkeypatch.setattr(provider, "exchange", exchange)
    result = await workflow.transcribe(request(local, backend="faster_whisper", local_only=True,
        language="nl", glossary=["wereld"], dry_run=False, authorize_submission=True))
    state = result["metadata"]
    assert state["status"] == "failed" and state["segments"] == []
    assert state["attempts"][0]["status"] == "failed_or_unknown"


@pytest.mark.parametrize("updates", [{"local": False}, {"expected_descriptor_sha256": None}, {"api_key_env": "LOCAL_API_KEY"}])
def test_timed_protocol_requires_exact_local_admission(updates):
    """GIVEN a remote/unbound/credential profile THEN configuration refuses before execution."""
    values = service().model_dump() | updates
    with pytest.raises(ValueError):
        ASRService.model_validate(values)


async def test_qwen_backend_cannot_use_timed_protocol(local, monkeypatch):
    """GIVEN distinct wire protocols THEN existing Qwen selection cannot silently change its contract."""
    prepare_stub(monkeypatch)
    local[2].asr_service = service()
    monkeypatch.setattr(provider, "exchange", lambda *a, **k: pytest.fail("protocol mismatch dispatched"))
    result = await workflow.transcribe(request(local, backend="qwen", dry_run=False, authorize_submission=True,
                                             require_timestamps=False, export_formats=["json", "text"]))
    assert result["metadata"]["status"] == "failed" and result["metadata"]["attempts"] == []


@pytest.mark.parametrize("error", [ValueError("source changed"), asyncio.CancelledError()])
@pytest.mark.parametrize("backend", ["faster_whisper", "qwen"])
async def test_predispatch_source_failure_has_terminal_attempt(local, monkeypatch, error, backend):
    """Retain failed source checks/cancellation without claiming an HTTP dispatch."""
    local[2].asr_service = service() if backend == "faster_whisper" else ASRService(
        base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True)
    typed = request(local, backend=backend, local_only=True, dry_run=False, authorize_submission=True,
                    require_timestamps=backend == "faster_whisper", require_word_alignment=backend == "faster_whisper",
                    export_formats=["json", "text"])
    plan, attempts = provider.provider_plan(typed), []
    window = {"index": 0, "parts": [{"data": local[0].read_bytes()}]}

    async def verify():
        raise error

    monkeypatch.setattr(provider, "exchange", lambda *a, **k: pytest.fail("source check dispatched HTTP"))
    with pytest.raises(type(error)):
        await getattr(provider, "_" + backend)(typed, window, plan, attempts, verify)
    assert attempts[0]["status"] == "failed_or_unknown"
    assert "http_status" not in attempts[0]
    assert plan["service_calls"] == attempts and plan["service_bytes"] == attempts[0]["serialized_bytes"]
