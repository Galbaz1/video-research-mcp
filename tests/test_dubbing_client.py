"""Mock-only service contract and endpoint policy checks for optional dubbing."""

import base64
import asyncio
import hashlib
from contextlib import asynccontextmanager
import io
import json
import os
from types import SimpleNamespace
import wave
from unittest.mock import AsyncMock
from pathlib import Path

import pytest
import httpx

from video_research_mcp import dubbing_client as client
from video_research_mcp import dubbing_contracts as contracts
from video_research_mcp.models.video_dubbing import VadSettings


@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('entry', ['tts', 'request'])
async def test_r131_tts_output_fenced_before_journal_access(configured, monkeypatch, tmp_path, clean_config, cached, entry):
    """GIVEN an outside output WHEN TTS runs THEN no outside I/O or POST occurs."""
    from video_research_mcp.config import get_config

    inside = tmp_path / 'inside'
    inside.mkdir()
    get_config().local_file_access_root = str(inside)
    reference = inside / 'reference.wav'
    reference.write_bytes(wav_bytes())
    output = tmp_path / 'outside/nested/tts.wav'
    payload = {'text': 'Hello', 'voice_base64': base64.b64encode(reference.read_bytes()).decode(),
               'voice_filename': reference.name, 'trim_silence': True,
               'trim_ref_silence': True, 'return_audio': True}
    if cached:
        output.parent.mkdir(parents=True)
        signature = hashlib.sha256(client.canonical({'origin': 'http://127.0.0.1:9123',
            'endpoint': '/tts', 'body_sha256': hashlib.sha256(client.canonical(payload)).hexdigest()})).hexdigest()
        raw = json.dumps({'audio_base64': base64.b64encode(wav_bytes()).decode(),
                          'duration_sec': 2.0, 'sample_rate': 48000}).encode()
        output.with_suffix('.intent.json').with_suffix('.response.json').write_bytes(raw)
        output.with_suffix('.intent.json').write_text(json.dumps({'request_sha256': signature,
            'state': 'response_saved', 'response_sha256': hashlib.sha256(raw).hexdigest()}))
    outside_io = []
    for name in ('read_bytes', 'open', 'mkdir'):
        original = getattr(Path, name)

        def watch(path, *args, _name=name, _original=original, **kwargs):
            if path.is_relative_to(tmp_path / 'outside'):
                outside_io.append((_name, str(path)))
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(Path, name, watch)
    boundary = AsyncMock()
    monkeypatch.setattr(client, 'exchange', boundary)
    with pytest.raises(PermissionError):
        if entry == 'tts':
            await client.tts('Hello', reference, output)
        else:
            await client.request('/tts', payload, output.with_suffix('.intent.json'))
    assert outside_io == []
    boundary.assert_not_called()


@pytest.mark.parametrize('kind', ['evidence', 'audio', 'intent', 'cache', 'saved_audio'])
async def test_r131_descriptor_growth_is_rejected(configured, monkeypatch, tmp_path, kind):
    """GIVEN growth after inspection WHEN read THEN the bounded file is rejected."""
    output = tmp_path / 'file'
    boundary = AsyncMock(return_value=(200, b'{"ok":true}'))
    monkeypatch.setattr(client, 'exchange', boundary)
    if kind in {'intent', 'cache'}:
        journal = output.with_suffix('.intent.json')
        await client.request('/tts', {'text': 'Hello'}, journal)
        target = journal if kind == 'intent' else journal.with_suffix('.response.json')
        if kind == 'cache':
            intent = json.loads(journal.read_bytes())
            intent['response_sha256'] = hashlib.sha256(target.read_bytes() + b' ' * 32).hexdigest()
            journal.write_bytes(client.canonical(intent))
    else:
        output.write_bytes(b'{"ok":true}' if kind == 'evidence' else wav_bytes(0.01))
        target = output
    limit = target.stat().st_size
    monkeypatch.setattr(contracts, 'MAX_JSON_BYTES', limit)
    if kind == 'intent':
        monkeypatch.setattr(client, 'MAX_JSON_BYTES', limit, raising=False)
    monkeypatch.setattr(client, 'MAX_AUDIO_BYTES', limit)
    monkeypatch.setattr(client, 'MAX_RESPONSE_BYTES', limit)
    original_open, original_fstat = Path.open, os.fstat
    grown = False

    def grow():
        nonlocal grown
        if not grown:
            grown = True
            with original_open(target, 'ab') as stream:
                stream.write(b' ' * 32)

    def opening(path, mode='r', *args, **kwargs):
        if path == target and mode == 'rb':
            grow()
        return original_open(path, mode, *args, **kwargs)

    def inspecting(fd):
        value = original_fstat(fd)
        if (value.st_dev, value.st_ino) == (target.stat().st_dev, target.stat().st_ino):
            grow()
        return value

    monkeypatch.setattr(Path, 'open', opening)
    monkeypatch.setattr(os, 'fstat', inspecting)
    with pytest.raises(client.DubbingError):
        if kind == 'evidence':
            contracts.read_json(target)
        elif kind == 'audio':
            client.audio_bytes(target)
        elif kind == 'saved_audio':
            client.save_audio(base64.b64encode(wav_bytes(0.01)).decode(), target)
        else:
            await client.request('/tts', {'text': 'Hello'}, journal)
    assert grown


def test_r131_bounded_reader_rejects_nonregular_descriptor(monkeypatch, tmp_path):
    """GIVEN a substituted pipe descriptor WHEN opened THEN reject before reading."""
    path = tmp_path / 'file'
    path.write_bytes(b'owned file')
    reader, writer = os.pipe()
    try:
        monkeypatch.setattr(os, 'open', lambda *args: os.dup(reader))
        with pytest.raises(client.DubbingError, match='not_regular'):
            client.bounded_bytes(path, 16, 'not_regular')
    finally:
        os.close(reader)
        os.close(writer)


def wav_bytes(seconds=2.0, rate=48000, channels=2):
    """Create owned PCM bytes without invoking a media process."""
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0" * int(seconds * rate) * channels * 2)
    return output.getvalue()


@pytest.fixture
def configured(monkeypatch):
    """Use an explicit loopback fixture and a synthetic environment credential."""
    monkeypatch.setenv("QWEN_MM_DUBBING_SERVER_URL", "http://127.0.0.1:9123")
    monkeypatch.setenv("VRM_DUBBING_LOCAL", "true")
    monkeypatch.setenv("VRM_DUBBING_API_KEY", "synthetic-test-token")


async def test_missing_service_is_terminal(monkeypatch):
    """GIVEN no service WHEN checked THEN no transport or media execution occurs."""
    monkeypatch.delenv("QWEN_MM_DUBBING_SERVER_URL", raising=False)
    boundary = AsyncMock()
    monkeypatch.setattr(client, "exchange", boundary)
    assert (await client.health())["state"] == "unavailable"
    boundary.assert_not_called()


async def test_exact_health_and_unready(configured, monkeypatch):
    """GIVEN model_loaded=false WHEN checked THEN readiness remains terminal."""
    boundary = AsyncMock(return_value=(200, b'{"model_loaded":false,"status":"loading"}'))
    monkeypatch.setattr(client, "exchange", boundary)
    value = await client.health()
    assert value["state"] == "unready" and value["terminal"] is True
    call = boundary.call_args
    assert call.args == ("http://127.0.0.1:9123/health",)
    assert call.kwargs["method"] == "GET" and call.kwargs["content"] == b""
    assert call.kwargs["headers"]["Authorization"] == "Bearer synthetic-test-token"


async def test_separation_contract_and_local_bytes(configured, monkeypatch, tmp_path):
    """GIVEN inline stems WHEN separated THEN only actual local PCM bytes are used."""
    audio = wav_bytes()
    source = tmp_path / "source.wav"
    source.write_bytes(audio)
    reply = {"stems_base64": {name: base64.b64encode(audio).decode()
                              for name in ("vocals", "no_vocals")},
             "output_paths": {"vocals": "/server/private.wav"}}
    boundary = AsyncMock(return_value=(200, json.dumps(reply).encode()))
    monkeypatch.setattr(client, "exchange", boundary)
    result = await client.separate(source, tmp_path / "stems")
    payload = json.loads(boundary.call_args.kwargs["content"])
    assert payload == {"audio_base64": base64.b64encode(audio).decode(),
                       "audio_filename": "source.wav", "model": "htdemucs",
                       "two_stems": "vocals", "mp3": False, "return_audio": True}
    assert result["vocals"]["path"] == str(tmp_path / "stems/vocals.wav")
    assert (tmp_path / "stems/vocals.wav").read_bytes() == audio
    assert "/server" not in json.dumps(result)


async def test_vad_and_tts_exact_wire_contract(configured, monkeypatch, tmp_path):
    """GIVEN valid service replies WHEN called THEN fields and local joins are exact."""
    audio = wav_bytes()
    source = tmp_path / "voice.wav"
    source.write_bytes(audio)
    replies = [(200, b'{"duration":2,"sample_rate":48000,"segments":[{"start_time":0,"end_time":2}]}'),
               (200, json.dumps({"audio_base64": base64.b64encode(audio).decode(),
                                 "duration_sec": 2.0, "sample_rate": 48000}).encode())]
    boundary = AsyncMock(side_effect=replies)
    monkeypatch.setattr(client, "exchange", boundary)
    vad = await client.vad(source, tmp_path / "vad")
    assert vad["segments"] == [{"start_sec": 0.0, "end_sec": 2.0}]
    output = tmp_path / "tts.wav"
    result = await client.tts("Hello friend", source, output)
    vad_payload = json.loads(boundary.call_args_list[0].kwargs["content"])
    assert vad_payload == {"audio_base64": base64.b64encode(audio).decode(),
                           "audio_filename": "voice.wav", "separate_first": False,
                           "threshold": 0.5, "hop_size": 256, "min_speech": 0.2,
                           "min_silence": 0.3, "pad": 0.1}
    tts_payload = json.loads(boundary.call_args_list[1].kwargs["content"])
    assert tts_payload == {"text": "Hello friend", "voice_base64": base64.b64encode(audio).decode(),
                           "voice_filename": "voice.wav", "trim_silence": True,
                           "trim_ref_silence": True, "return_audio": True}
    assert output.read_bytes() == audio and result["duration_sec"] == 2.0
    for path in tmp_path.rglob("*.intent.json"):
        assert "synthetic-test-token" not in path.read_text()


async def test_verified_nondefault_vad_controls(configured, monkeypatch, tmp_path):
    """GIVEN source-supported controls WHEN requested THEN transmit exact approved values."""
    source = tmp_path / "source.wav"
    source.write_bytes(wav_bytes())
    boundary = AsyncMock(return_value=(200, b'{"duration":2,"sample_rate":48000,"segments":[]}'))
    monkeypatch.setattr(client, "exchange", boundary)
    settings = VadSettings(threshold=0.3, hop_size=128, min_speech=0.4, min_silence=0.2, pad=0.2)
    await client.vad(source, tmp_path / "vad", settings)
    payload = json.loads(boundary.call_args.kwargs["content"])
    assert {key: payload[key] for key in settings.model_dump()} == settings.model_dump()
    with pytest.raises(ValueError):
        VadSettings(threshold=float("nan"))


@pytest.mark.parametrize("reply", [{"model_loaded": "true", "status": "ready"},
                                  {"model_loaded": 1, "status": "ready"},
                                  {"model_loaded": True}, []])
async def test_health_truthiness_is_not_readiness(configured, monkeypatch, reply):
    """GIVEN malformed health WHEN checked THEN truthy labels never admit readiness."""
    monkeypatch.setattr(client, "exchange", AsyncMock(return_value=(200, json.dumps(reply).encode())))
    assert (await client.health())["terminal"] is True


@pytest.mark.parametrize("reply", [{"output_path": "/server/voice.wav"},
                                  {"audio_base64": "invalid!!!", "duration_sec": 2, "sample_rate": 48000},
                                  {"audio_base64": "", "duration_sec": 2, "sample_rate": 48000}])
async def test_server_path_or_invalid_audio_never_becomes_output(configured, monkeypatch, tmp_path, reply):
    """GIVEN no usable returned PCM WHEN synthesized THEN never trust remote paths."""
    source = tmp_path / "reference.wav"
    source.write_bytes(wav_bytes())
    monkeypatch.setattr(client, "exchange", AsyncMock(return_value=(200, json.dumps(reply).encode())))
    with pytest.raises(client.DubbingError):
        await client.tts("Hello", source, tmp_path / "output.wav")
    assert not (tmp_path / "output.wav").exists()


@pytest.mark.parametrize("duration,rate", [(100.0, 48000), (2.0, 44100), (float("nan"), 48000), (True, 48000)])
async def test_tts_metadata_is_checked_against_pcm(configured, monkeypatch, tmp_path, duration, rate):
    """GIVEN contradictory duration/rate WHEN returned THEN reject rather than relabel."""
    source = tmp_path / "ref.wav"
    source.write_bytes(wav_bytes())
    reply = {"audio_base64": base64.b64encode(wav_bytes()).decode(),
             "duration_sec": duration, "sample_rate": rate}
    monkeypatch.setattr(client, "exchange", AsyncMock(return_value=(200, json.dumps(reply).encode())))
    with pytest.raises(client.DubbingError, match="tts_metadata"):
        await client.tts("Hello", source, tmp_path / "out.wav")


@pytest.mark.parametrize("segments", [[{"start_time": 1, "end_time": 1}],
                                     [{"start_time": True, "end_time": 2}],
                                     [{"start_time": 0, "end_time": 3}],
                                     [{"start_time": 1, "end_time": 2}, {"start_time": 0, "end_time": 1}],
                                     [{"start_time": float("nan"), "end_time": 2}]])
async def test_invalid_vad_intervals(configured, monkeypatch, tmp_path, segments):
    """GIVEN invalid ordered VAD evidence WHEN returned THEN refuse intervals."""
    source = tmp_path / "ref.wav"
    source.write_bytes(wav_bytes())
    monkeypatch.setattr(client, "exchange", AsyncMock(return_value=(200, json.dumps(
        {"duration": 2, "sample_rate": 48000, "segments": segments}).encode())))
    with pytest.raises(client.DubbingError):
        await client.vad(source, tmp_path / "vad")


async def test_interrupted_post_is_occupied_without_retry(configured, monkeypatch, tmp_path):
    """GIVEN an unknown transport effect WHEN resumed THEN no second POST is sent."""
    boundary = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(client, "exchange", boundary)
    journal = tmp_path / "operation.intent.json"
    with pytest.raises(client.DubbingError, match="transport_unknown"):
        await client.request("/tts", {"text": "mock"}, journal)
    assert json.loads(journal.read_bytes())["state"] == "intent"
    with pytest.raises(client.DubbingError, match="reconciliation"):
        await client.request("/tts", {"text": "mock"}, journal)
    assert boundary.await_count == 1


async def test_http_failure_and_cached_response_no_resend(configured, monkeypatch, tmp_path):
    """GIVEN a known failed HTTP response WHEN resumed THEN retain it without resend."""
    boundary = AsyncMock(return_value=(503, b'{"secret":"synthetic fixture body"}'))
    monkeypatch.setattr(client, "exchange", boundary)
    journal = tmp_path / "failed.intent.json"
    with pytest.raises(client.DubbingError, match="http_failed"):
        await client.request("/tts", {"text": "mock"}, journal)
    with pytest.raises(client.DubbingError, match="reconciliation"):
        await client.request("/tts", {"text": "mock"}, journal)
    assert boundary.await_count == 1
    assert json.loads(journal.read_bytes())["http_status"] == 503


async def test_success_cache_requires_same_request_and_bytes(configured, monkeypatch, tmp_path):
    """GIVEN exact successful cached response WHEN resumed THEN use its pinned bytes."""
    boundary = AsyncMock(return_value=(200, b'{"value":1}'))
    monkeypatch.setattr(client, "exchange", boundary)
    journal = tmp_path / "success.intent.json"
    assert await client.request("/vad", {"source": "same"}, journal) == {"value": 1}
    assert await client.request("/vad", {"source": "same"}, journal) == {"value": 1}
    with pytest.raises(client.DubbingError):
        await client.request("/vad", {"source": "changed"}, journal)
    journal.with_suffix(".response.json").write_bytes(b'{"value":2}')
    with pytest.raises(client.DubbingError, match="cache_changed"):
        await client.request("/vad", {"source": "same"}, journal)
    assert boundary.await_count == 1


async def test_concurrent_effect_is_not_duplicated(configured, monkeypatch, tmp_path):
    """GIVEN two writers WHEN one intent is occupied THEN exactly one reaches HTTP."""
    started, release = asyncio.Event(), asyncio.Event()
    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return 200, b"{}"
    boundary = AsyncMock(side_effect=slow)
    monkeypatch.setattr(client, "exchange", boundary)
    journal = tmp_path / "concurrent.intent.json"
    first = asyncio.create_task(client.request("/vad", {"source": "same"}, journal))
    await started.wait()
    with pytest.raises(client.DubbingError, match="reconciliation"):
        await client.request("/vad", {"source": "same"}, journal)
    release.set()
    await first
    assert boundary.await_count == 1


async def test_upload_size_and_symlink_fail_before_http(configured, monkeypatch, tmp_path):
    """GIVEN oversized or symlink input WHEN uploaded THEN no HTTP effect occurs."""
    source = tmp_path / "ref.wav"
    source.write_bytes(wav_bytes())
    boundary = AsyncMock()
    monkeypatch.setattr(client, "exchange", boundary)
    monkeypatch.setattr(client, "MAX_AUDIO_BYTES", 16)
    with pytest.raises(client.DubbingError):
        await client.tts("Hello", source, tmp_path / "out.wav")
    alias = tmp_path / "alias.wav"
    alias.symlink_to(source)
    with pytest.raises(PermissionError):
        client.audio_bytes(alias)
    boundary.assert_not_called()


@pytest.mark.parametrize("wrong_peer", [False, True])
async def test_real_http_boundary_peer_proof_and_headers(configured, monkeypatch, wrong_peer):
    """GIVEN a mocked connected socket WHEN HTTP runs THEN authenticate before send."""
    import video_research_mcp.vision_http as fence
    transmitted = []
    class Socket:
        def get_extra_info(self, key):
            return ("127.0.0.2" if wrong_peer else "127.0.0.1", 9123)
        async def aclose(self):
            pass
    class Transport:
        def __init__(self, **kwargs):
            assert kwargs == {"retries": 0, "trust_env": False, "http2": False}
            self._pool = SimpleNamespace(_network_backend=object())
    class HTTP:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        @asynccontextmanager
        async def stream(self, method, target, **kwargs):
            trace = kwargs["extensions"]["trace"]
            await trace("connection.connect_tcp.complete", {"return_value": fence._LimitedStream(Socket(), 4096)})
            await trace("http11.send_request_headers.started", {})
            transmitted.append((method, str(target), kwargs))
            yield httpx.Response(200, stream=httpx.ByteStream(b'{"model_loaded":true,"status":"ready"}'))
        async def aclose(self):
            pass
    monkeypatch.setattr(client.httpx, "AsyncHTTPTransport", Transport)
    monkeypatch.setattr(client.httpx, "AsyncClient", HTTP)
    if wrong_peer:
        with pytest.raises(client.DubbingError, match="peer_policy_refused"):
            await client.request("/health", None)
        assert not transmitted
    else:
        assert (await client.health())["state"] == "ready"
        method, target, kwargs = transmitted[0]
        assert method == "GET" and target == "http://127.0.0.1:9123/health"
        assert kwargs["headers"]["Host"] == "127.0.0.1:9123"
        assert kwargs["headers"]["Authorization"] == "Bearer synthetic-test-token"
