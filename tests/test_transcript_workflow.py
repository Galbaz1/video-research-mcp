"""Owned fixtures and mocked native/provider boundaries with real source/hash lifecycle."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from video_research_mcp import media_snapshot, transcript as workflow, transcript_audio as audio
from video_research_mcp import transcript_provider as provider
from video_research_mcp.models.transcript import ASRAnswer, ASRService, TranscriptRequest
from video_research_mcp.transcript_formats import encoded


def wav_bytes(seconds=2, *, zero=False, tail=False):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        data = (b"\0\0" if zero else b"\x10\0") * round(seconds * 16000)
        writer.writeframes(data[:-2] + b"\x01\0" if tail else data)
    return stream.getvalue()


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def local(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache_dir=str(tmp_path / "cache"), media_acquire_timeout_seconds=10, asr_service=None)
    monkeypatch.setattr(media_snapshot, "get_config", lambda: cfg)
    monkeypatch.setattr(provider, "get_config", lambda: cfg)
    source = tmp_path / "source.wav"
    source.write_bytes(wav_bytes(8))
    return source, tmp_path, cfg


def request(local, **updates):
    source, directory, _ = local
    values = dict(file_path=str(source), expected_source_sha256=sha(source.read_bytes()),
                  output_directory=str(directory / "run"), end_seconds=2)
    values.update(updates)
    return TranscriptRequest(**values)


def captions(local, *, text="Hi", origin="uploaded", kind="srt", contents=None):
    source, directory, _ = local
    path = directory / (origin + "." + kind)
    path.write_bytes(contents if contents is not None else f"1\n00:00:00,100 --> 00:00:01,200\n{text}\n".encode())
    return {"origin": origin, "format": kind, "source_sha256": sha(source.read_bytes()),
            "file_path": str(path), "expected_sha256": sha(path.read_bytes())}


def prepare_stub(monkeypatch, *, zero=False, shift=0, failure_on_exit=False):
    @asynccontextmanager
    async def prepared(req):
        source = {"path": str(Path(req.file_path).absolute()), "sha256": req.expected_source_sha256,
                  "bytes": Path(req.file_path).stat().st_size}
        windows = []
        for index in range(round((req.end_seconds - req.start_seconds) / req.window_seconds) or 1):
            start = req.start_seconds + index * req.window_seconds
            end = min(req.end_seconds, start + req.window_seconds)
            actual = start + shift
            data = wav_bytes(end - actual, zero=zero)
            windows.append({"index": index, "start_seconds": start, "end_seconds": end, "frames": [],
                "audio": {"selected_window": {"start_seconds": actual, "end_seconds": end}},
                "parts": [{"kind": "audio", "mime": "audio/wav", "data": data, "sha256": sha(data),
                           "bytes": len(data), "actual_seconds": actual}], "payload_bytes": len(data)})

        async def verify():
            assert sha(Path(req.file_path).read_bytes()) == req.expected_source_sha256

        yield source, windows, verify
        if failure_on_exit:
            raise ValueError("controlled preparation closing verification failure")
    monkeypatch.setattr(workflow, "prepared_audio", prepared)


def gemini_stub(monkeypatch, *, answers=None, fail_index=None, block=None):
    monkeypatch.setattr(provider, "selected_gemini", lambda: ("configured-model", "fake-unit-key", None))
    called = []

    async def infer(req, window, selected, budget, attempts, verify, *, schema, task_prompt):
        called.append(window)
        attempts.append({"window_index": window["index"], "status": "attempted"})
        budget.calls.append({"kind": "generate", "status": "completed_usage_unknown", "finish_reasons": ["STOP"]})
        await verify()
        if block:
            block.set()
            await asyncio.Event().wait()
        if window["index"] == fail_index:
            attempts[-1]["status"] = "failed"
            raise RuntimeError("fake-unit-key raw provider detail https://secret.invalid/?signed=token")
        attempts[-1]["status"] = "complete"
        return ASRAnswer.model_validate(answers or {"outcome": "transcript", "segments": [
            {"start_seconds": .1, "end_seconds": .5, "text": "Hello", "speaker_id": None, "words": []}]})
    monkeypatch.setattr(provider, "infer_window", infer)
    return called


@pytest.mark.asyncio
async def test_caption_preference_skips_asr_and_restarts_exact_bytes(local, monkeypatch):
    uploaded, native = captions(local), captions(local, origin="native", text="Other")
    monkeypatch.setattr(workflow, "provider_plan", lambda _: pytest.fail("caption route must not select provider"))
    result = await workflow.transcribe(request(local, caption_sources=[native, uploaded]))
    assert result["status"] == "complete" and result["outcome"] == "captions"
    assert result["segments"][0]["text"] == "Hi" and result["attempts"] == []
    assert result["captions"][0]["status"] == "not_selected_unread"
    assert result["provenance"]["speech_accuracy_verified"] is False
    restored = await workflow.transcribe(request(local, action="readback", expected_receipt_sha256=result["receipt"]["sha256"]))
    assert restored == result


@pytest.mark.asyncio
async def test_selected_malformed_caption_does_not_fall_through(local):
    bad = captions(local, contents=b"malformed")
    good = captions(local, origin="sidecar")
    result = await workflow.transcribe(request(local, caption_sources=[good, bad]))
    assert result["metadata"]["status"] == "failed" and result["metadata"]["segments"] == []
    assert result["metadata"]["attempts"] == [] and result["metadata"]["receipt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["source", "caption", "export", "receipt"])
async def test_restart_refuses_every_committed_identity_drift(local, changed):
    item = captions(local)
    result = await workflow.transcribe(request(local, caption_sources=[item]))
    directory = Path(result["receipt"]["directory"])
    target = {"source": local[0], "caption": Path(item["file_path"]),
              "export": directory / "transcript.srt", "receipt": directory / "receipt.json"}[changed]
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        await workflow.read_transcript(str(directory), result["receipt"]["sha256"])


@pytest.mark.asyncio
async def test_readback_caller_source_fields_are_not_ignored(local):
    result = await workflow.transcribe(request(local, caption_sources=[captions(local)]))
    with pytest.raises(ValueError, match="caller source SHA"):
        await workflow.read_transcript(result["receipt"]["directory"], result["receipt"]["sha256"],
                                       expected_source_sha256="b" * 64)
    with pytest.raises(ValueError, match="caller source path"):
        await workflow.read_transcript(result["receipt"]["directory"], result["receipt"]["sha256"], file_path=str(local[1] / "other.wav"))


@pytest.mark.asyncio
async def test_existing_output_namespace_is_never_overwritten(local):
    directory = local[1] / "run"
    directory.mkdir()
    sentinel = directory / "unrelated"
    sentinel.write_text("preserve")
    with pytest.raises(FileExistsError):
        await workflow.transcribe(request(local))
    assert sentinel.read_text() == "preserve"


@pytest.mark.asyncio
async def test_actual_selected_wav_offset_and_payload_are_bound(local, monkeypatch):
    prepare_stub(monkeypatch, shift=.5)
    calls = gemini_stub(monkeypatch)
    result = await workflow.transcribe(request(local, start_seconds=2, end_seconds=4,
        backend="gemini", dry_run=False, authorize_submission=True))
    assert result["segments"][0]["start_seconds"] == 2.6
    assert calls[0]["start_seconds"] == 2.5 and calls[0]["frames"] == []
    chunk = Path(result["receipt"]["directory"]) / result["windows"][0]["artifact"]["path"]
    assert sha(chunk.read_bytes()) == result["windows"][0]["artifact"]["sha256"]
    assert result["windows"][0]["pcm_observation"]["sample_count"] == 24000


@pytest.mark.asyncio
async def test_second_window_failure_retains_first_and_remaining_unrun(local, monkeypatch):
    prepare_stub(monkeypatch)
    gemini_stub(monkeypatch, fail_index=1)
    result = await workflow.transcribe(request(local, end_seconds=6, window_seconds=2,
        backend="gemini", dry_run=False, authorize_submission=True))
    state = result["metadata"]
    assert state["status"] == "partial" and len(state["segments"]) == 1
    assert [w["status"] for w in state["windows"]] == ["complete", "failed_or_interrupted", "planned"]
    assert len(state["attempts"]) == 2 and "fake-unit-key" not in json.dumps(result)
    assert "secret.invalid" not in json.dumps(result)


@pytest.mark.asyncio
async def test_silent_complete_selection_needs_no_backend_or_credentials(local, monkeypatch):
    prepare_stub(monkeypatch, zero=True)
    monkeypatch.setattr(workflow, "provider_plan", lambda _: pytest.fail("zero PCM must skip all provider selection"))
    result = await workflow.transcribe(request(local, dry_run=False, authorize_submission=False))
    assert result["status"] == "complete" and result["outcome"] == "empty"
    assert result["segments"] == [] and result["attempts"] == []
    assert result["windows"][0]["pcm_observation"]["all_samples_exact_zero"]
    restarted = await workflow.read_transcript(result["receipt"]["directory"], result["receipt"]["sha256"])
    assert restarted == result


def test_complete_pcm_observation_does_not_use_first120seconds(tmp_path):
    path = tmp_path / "long.wav"
    path.write_bytes(wav_bytes(121, zero=True, tail=True))
    measured = audio.pcm_observation(path, tmp_path / "observation")
    assert measured["sample_count"] == 121 * 16000
    assert measured["all_samples_exact_zero"] is False


@pytest.mark.asyncio
async def test_dry_plan_prepares_actual_audio_but_does_not_select_account(local, monkeypatch):
    prepare_stub(monkeypatch)
    monkeypatch.setattr(workflow, "provider_plan", lambda _: pytest.fail("dry run account discovery forbidden"))
    result = await workflow.transcribe(request(local, backend="gemini"))
    assert result["status"] == "planned" and result["outcome"] == "planned"
    assert result["segments"] == [] and result["windows"][0]["status"] == "planned"


@pytest.mark.asyncio
async def test_source_closing_verification_cannot_promote_success(local, monkeypatch):
    prepare_stub(monkeypatch, failure_on_exit=True)
    gemini_stub(monkeypatch)
    result = await workflow.transcribe(request(local, backend="gemini", dry_run=False, authorize_submission=True))
    assert result["metadata"]["status"] == "failed"
    assert result["metadata"]["exports"] == []


@pytest.mark.asyncio
async def test_cancellation_retains_interrupted_receipt_and_preserves_original(local, monkeypatch):
    prepare_stub(monkeypatch)
    began = asyncio.Event()
    gemini_stub(monkeypatch, block=began)
    original = local[0].read_bytes()
    task = asyncio.create_task(workflow.transcribe(request(local, backend="gemini", dry_run=False, authorize_submission=True)))
    await began.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    receipt = json.loads((local[1] / "run" / "receipt.json").read_bytes())
    assert receipt["status"] == "failed" and local[0].read_bytes() == original
    assert json.loads((local[1] / "run" / "run-state.json").read_bytes())["windows"][0]["status"] == "failed_or_interrupted"


@pytest.mark.asyncio
async def test_embedded_caption_command_is_explicit_file_only_and_owned(local, monkeypatch):
    source = local[0]
    cfg = SimpleNamespace()
    owned = SimpleNamespace(path=source, remaining=lambda: 5, verify=lambda: asyncio.sleep(0))
    commands = []

    async def run(command, timeout, *, cwd):
        commands.append(command)
        Path(command[-1]).write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\n123\n")
    monkeypatch.setattr(audio, "binary", lambda name: "/owned/" + name)
    monkeypatch.setattr(audio, "run_media_process", run)
    cfg.embedded_track = 2
    data = await audio.extract_embedded(owned, cfg, local[1])
    assert b"123" in data and commands[0][commands[0].index("-map") + 1] == "0:s:2"
    assert "-copyts" in commands[0] and "-n" in commands[0]
    assert commands[0][commands[0].index("-protocol_whitelist") + 1] == "file"


@pytest.mark.parametrize("url,local_flag", [("http://remote.test", True), ("https://8.8.8.8", True),
    ("http://localhost", True), ("https://user:pass@remote.test", False), ("https://remote.test?token=a", False)])
def test_service_local_assertion_cannot_authorize_internet_or_endpoint_credentials(url, local_flag):
    with pytest.raises(ValueError):
        ASRService(base_url=url, local=local_flag)


@pytest.mark.asyncio
@pytest.mark.parametrize("updates,service", [
    ({}, None), ({}, ASRService(base_url="http://127.0.0.1:9999", local=True)),
    ({"require_timestamps": True}, ASRService(base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True)),
    ({"language": "English"}, ASRService(base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True)),
    ({"glossary": ["term"]}, ASRService(base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True)),
    ({"require_word_alignment": True}, ASRService(base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True)),
    ({"local_only": True}, ASRService(base_url="https://service.test", runtime_qualified=True)),
])
async def test_unsupported_or_disabled_qwen_refuses_before_http(local, monkeypatch, updates, service):
    prepare_stub(monkeypatch)
    local[2].asr_service = service
    monkeypatch.setattr(provider, "exchange", lambda *a, **k: pytest.fail("no unauthorized service call"))
    base = dict(backend="qwen", dry_run=False, authorize_submission=True, require_timestamps=False, export_formats=["json", "text"])
    base.update(updates)
    result = await workflow.transcribe(request(local, **base))
    assert result["metadata"]["status"] == "failed" and result["metadata"]["attempts"] == []


@pytest.mark.asyncio
async def test_explicit_cloud_to_local_fallback_keeps_both_attempts_and_no_invented_times(local, monkeypatch):
    prepare_stub(monkeypatch)
    gemini_stub(monkeypatch, fail_index=0)
    local[2].asr_service = ASRService(base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True, declared_model="operator-model")
    posted = []

    async def exchange(url, *, headers, content, method, local):
        posted.append((url, json.loads(content), method, local))
        state = json.loads((Path(request_root) / "run-state.json").read_bytes())
        assert state["windows"][0]["status"] == "dispatching"
        return 200, encoded({"results": [{"text": "Untimed actual reply"}]})
    request_root = str(local[1] / "run")
    monkeypatch.setattr(provider, "exchange", exchange)
    result = await workflow.transcribe(request(local, backend="gemini", fallback_backend="qwen", dry_run=False,
        authorize_submission=True, require_timestamps=False, export_formats=["json", "text"]))
    assert result["status"] == "complete" and result["segments"] == []
    assert result["untimed_text"][0]["start_seconds"] is None
    assert [a["actual_backend"] for a in result["attempts"]] == ["gemini", "qwen"]
    assert posted[0][1]["return_time_stamps"] is False and posted[0][2:] == ("POST", True)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not-json", b'{}', b'{"results":[{"text":""}]}',
    b'{"results":[{"text":"Hi","start":0}]}', b'{"results":null}'])
async def test_malformed_local_results_are_failures_not_empty_speech(local, monkeypatch, body):
    prepare_stub(monkeypatch)
    local[2].asr_service = ASRService(base_url="http://127.0.0.1:9999", local=True, runtime_qualified=True)

    async def exchange(*args, **kwargs):
        return 200, body
    monkeypatch.setattr(provider, "exchange", exchange)
    result = await workflow.transcribe(request(local, backend="qwen", require_timestamps=False,
        export_formats=["json", "text"], dry_run=False, authorize_submission=True))
    assert result["metadata"]["status"] == "failed" and result["metadata"]["outcome"] != "empty"


@pytest.mark.asyncio
async def test_caption_source_without_audio_does_not_prepare_asr(local, monkeypatch):
    item = captions(local)

    async def clock(owned, req, directory):
        return {"path": str(owned.original), "sha256": owned.sha256, "bytes": owned.size,
                "presentation_end_seconds": 8, "has_audio": False}, [{"index": 0, "start_seconds": 0, "end_seconds": 2}]
    monkeypatch.setattr(workflow, "source_clock", clock)
    monkeypatch.setattr(workflow, "prepared_audio", lambda _: pytest.fail("caption assertions do not require audio"))
    result = await workflow.transcribe(request(local, caption_sources=[item]))
    assert result["status"] == "complete" and result["source"]["has_audio"] is False


@pytest.mark.asyncio
async def test_source_drift_during_export_retains_failed_receipt(local, monkeypatch):
    original_writer = workflow.write_artifact

    def writer(directory, name, data, role):
        record = original_writer(directory, name, data, role)
        if name == "transcript.srt":
            local[0].write_bytes(local[0].read_bytes() + b"source drift after snapshot exit")
        return record
    monkeypatch.setattr(workflow, "write_artifact", writer)
    result = await workflow.transcribe(request(local, caption_sources=[captions(local)]))
    assert result["metadata"]["status"] == "failed"
    receipt = json.loads((local[1] / "run" / "receipt.json").read_bytes())
    assert receipt["status"] == "failed"


@pytest.mark.parametrize("stage", ["verification", "originals"])
async def test_persistence_deadline_refuses_complete_receipt(local, monkeypatch, stage):
    """GIVEN slow persistence proof THEN the public tool retains a failed receipt."""
    from video_research_mcp.tools.audio_transcribe import audio_transcribe

    name = "verify_artifacts" if stage == "verification" else "_rejoin_originals"
    original = getattr(workflow, name)

    async def slow(*args):
        await asyncio.sleep(.1)
        return await original(*args)
    monkeypatch.setattr(workflow, name, slow)
    result = await audio_transcribe(request(local, caption_sources=[captions(local)],
                                           limits={"timeout_seconds": .04}))
    assert result["metadata"]["status"] == "failed"
    receipt = json.loads((local[1] / "run" / "receipt.json").read_bytes())
    assert receipt["status"] == "failed"


@pytest.mark.parametrize("stage", ["verification", "originals", "final_verification"])
async def test_persistence_cancellation_retains_restart_receipt(local, monkeypatch, stage):
    """GIVEN cancellation during proof THEN exports and a failed receipt remain bound."""
    from video_research_mcp.tools.audio_transcribe import audio_transcribe

    name = "_rejoin_originals" if stage == "originals" else "verify_artifacts"
    original = getattr(workflow, name)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def blocked(*args):
        nonlocal calls
        calls += 1
        if calls == (2 if stage == "final_verification" else 1):
            entered.set()
            await release.wait()
        return await original(*args)
    monkeypatch.setattr(workflow, name, blocked)
    typed = request(local, caption_sources=[captions(local)])
    task = asyncio.create_task(audio_transcribe(typed))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    root = local[1] / "run"
    receipt = json.loads((root / "receipt.json").read_bytes())
    assert receipt["status"] == "failed"
    trusted = sha((root / "receipt.json").read_bytes())
    restored = await workflow.read_transcript(str(root), trusted,
        file_path=typed.file_path, expected_source_sha256=typed.expected_source_sha256)
    assert restored["status"] == "failed"
    assert len(restored["exports"]) == 3


async def test_caption_container_clock_survives_absent_audio_duration(local, monkeypatch):
    """GIVEN finite audio-only container duration THEN caption selection uses that clock."""
    from unittest.mock import AsyncMock

    owned = SimpleNamespace(path=Path("source.mkv"), verify=AsyncMock())
    observed = {"stream_index": None, "streams": [{"codec_type": "audio"}],
                "presentation_end_seconds": 8, "duration_seconds": 8}
    monkeypatch.setattr(audio, "probe_snapshot", AsyncMock(return_value=observed))
    decoded = AsyncMock(return_value=observed | {"audio_end_seconds": None})
    monkeypatch.setattr(audio, "audio_source", decoded, raising=False)
    source, windows = await audio.source_clock(owned, request(local, end_seconds=None), local[1])
    assert source["presentation_end_seconds"] == 8
    assert windows == [{"index": 0, "start_seconds": 0, "end_seconds": 8}]
    decoded.assert_not_called()
