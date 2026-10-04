"""Optional ASR wire, exact admission and OS lifecycle contracts; no real model."""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import pytest

from video_research_mcp.models.transcript import ASRAnswer

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import local_asr_service as service  # noqa: E402
import local_asr_worker as worker  # noqa: E402


def wav_bytes(frames=16000, channels=1, rate=16000, width=2):
    """Make silence only for parser contracts, never a speech qualification."""
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setparams((channels, width, rate, frames, "NONE", ""))
        writer.writeframes(b"\0" * frames * channels * width)
    return stream.getvalue()


def request_bytes(audio=None, **changes):
    """Build the explicit four-field request with its exact container digest."""
    audio = wav_bytes() if audio is None else audio
    value = {"audio": "data:audio/wav;base64," + base64.b64encode(audio).decode(),
             "audio_sha256": hashlib.sha256(audio).hexdigest(), "language": "nl", "glossary": ["kwadraat"]}
    value.update(changes)
    return worker.json_bytes(value)


from tests.test_local_asr_launch import pinned as pinned  # noqa: E402


def test_admission_complete_identity(pinned):
    path, descriptor = pinned
    assert worker.admit(path, worker.file_digest(path)) == descriptor


@pytest.mark.parametrize("change", ["descriptor", "source", "worker", "interpreter", "version", "inventory", "runtime", "extra", "model", "missing_model", "boolean_version"])
def test_admission_drift_refuses(pinned, change):
    path, descriptor = pinned
    expected = worker.file_digest(path)
    if change == "descriptor":
        path.write_bytes(b"{}")
    elif change in ("source", "worker"):
        descriptor["script_sha256" if change == "source" else "worker_sha256"] = "0" * 64
    elif change == "interpreter":
        descriptor["runtime"]["python_sha256"] = "0" * 64
    elif change == "version":
        descriptor["runtime"]["versions"]["python"] = "9.99"
    elif change == "inventory":
        descriptor["runtime"]["inventory_sha256"] = "0" * 64
    elif change in ("runtime", "extra"):
        (Path(descriptor["runtime"]["directory"]) / ("library.txt" if change == "runtime" else "extra.txt")).write_text("changed")
    elif change == "model":
        (Path(descriptor["models"]["en"]["directory"]) / "model.bin").write_text("changed")
    elif change == "missing_model":
        descriptor["models"].pop("en")
    else:
        descriptor["schema_version"] = True
    if change != "descriptor":
        path.write_bytes(worker.json_bytes(descriptor))
        expected = worker.file_digest(path)
    with pytest.raises(ValueError):
        worker.admit(path, expected)


def test_exact_wav_digest_pcm_and_hints():
    raw = request_bytes()
    request, pcm, duration = worker.decode_request(raw)
    assert pcm == b"\0" * 32000 and duration == 1.0
    assert request["language"] == "nl" and request["glossary"] == ["kwadraat"]


@pytest.mark.parametrize("change", ["digest", "base64", "uri", "language", "glossary", "hints_count", "hint_length", "extra", "channels", "rate", "width", "empty", "duration", "truncated", "trailing", "oversize", "duplicate", "nan"])
def test_input_boundaries(change):
    value = worker.parse_json(request_bytes())
    if change in ("channels", "rate", "width", "empty", "duration", "truncated", "trailing"):
        audio = wav_bytes(**{"channels": {"channels": 2}, "rate": {"rate": 8000}, "width": {"width": 1},
                             "empty": {"frames": 0}, "duration": {"frames": 480001}}.get(change, {}))
        if change == "truncated":
            audio = audio[:-1]
        if change == "trailing":
            audio += b"extra"
        raw = request_bytes(audio)
    else:
        if change == "digest":
            value["audio_sha256"] = "0" * 64
        elif change == "base64":
            value["audio"] += "?"
        elif change == "uri":
            value["audio"] = "file:///private.wav"
        elif change == "language":
            value["language"] = "fr"
        elif change in ("glossary", "hints_count", "hint_length"):
            value["glossary"] = {"glossary": [""], "hints_count": ["x"] * 33, "hint_length": ["x" * 129]}[change]
        elif change == "extra":
            value["download"] = True
        raw = worker.json_bytes(value)
        if change == "oversize":
            raw = b" " * (worker.MAX_REQUEST + 1)
        elif change == "duplicate":
            raw = raw[:-1] + b',"language":"nl"}'
        elif change == "nan":
            raw = b'{"language":NaN}'
    with pytest.raises((ValueError, EOFError, wave.Error)):
        worker.decode_request(raw)


@pytest.fixture
def model_mock(monkeypatch):
    """Mock the optional model while preserving real array conversion and result validation."""
    segment = SimpleNamespace(start=0.125, end=0.875, text=" Hallo wereld",
                              words=[SimpleNamespace(word=" Hallo", start=0.125, end=0.4),
                                     SimpleNamespace(word=" wereld", start=0.45, end=0.875)])
    model = Mock()
    model.model.compute_type = "int8_float32"
    model.transcribe.return_value = (iter([segment]), SimpleNamespace(language="nl"))
    constructor = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=constructor))
    return constructor, model, segment


@pytest.mark.parametrize("language,selected", [("en", "en"), ("nl", "multilingual"), (None, "multilingual")])
def test_actual_model_contract_and_asr_answer(pinned, model_mock, language, selected):
    _, descriptor = pinned
    constructor, model, _ = model_mock
    request, pcm, duration = worker.decode_request(request_bytes(language=language))
    output = worker.infer(request, pcm, duration, descriptor, "d" * 64)
    constructor.assert_called_once_with(descriptor["models"][selected]["directory"], device="cpu", compute_type="int8",
                                        cpu_threads=4, num_workers=1, local_files_only=True)
    args, kwargs = model.transcribe.call_args
    assert args[0].dtype.name == "float32" and len(args[0]) == 16000
    assert kwargs == {"language": language, "task": "transcribe", "beam_size": 5, "temperature": 0,
                      "word_timestamps": True, "vad_filter": False, "condition_on_previous_text": False, "hotwords": "kwadraat"}
    answer = ASRAnswer.model_validate(output["answer"])
    assert answer.segments[0].words[1].start_seconds == 0.45
    assert answer.segments[0].speaker_id is None and output["receipt"]["word_alignment_verified"] is False


def test_model_numpy_timestamps_preserve_values_as_wire_numbers(pinned, model_mock):
    """Native NumPy scalar timestamps retain their values at the JSON boundary."""
    import numpy as np

    _, descriptor = pinned
    _, _, segment = model_mock
    segment.start, segment.end = np.float64(segment.start), np.float64(segment.end)
    for word in segment.words:
        word.start, word.end = np.float64(word.start), np.float64(word.end)
    request, pcm, duration = worker.decode_request(request_bytes())
    output = worker.infer(request, pcm, duration, descriptor, "d" * 64)
    cue = output["answer"]["segments"][0]
    assert cue["start_seconds"] == segment.start and cue["end_seconds"] == segment.end
    assert type(cue["start_seconds"]) is float and type(cue["end_seconds"]) is float
    for actual, original in zip(cue["words"], segment.words, strict=True):
        assert actual["start_seconds"] == original.start and actual["end_seconds"] == original.end
        assert type(actual["start_seconds"]) is float and type(actual["end_seconds"]) is float
    assert worker.parse_json(worker.json_bytes(output))["answer"] == output["answer"]


@pytest.mark.parametrize("change", ["nan", "boolean", "zero", "extent", "word_extent", "missing_words", "text"])
def test_unsafe_model_output_is_never_promoted(pinned, model_mock, change):
    _, descriptor = pinned
    _, _, segment = model_mock
    if change == "nan":
        segment.start = float("nan")
    elif change == "boolean":
        segment.start = False
    elif change == "zero":
        segment.words[0].end = segment.words[0].start
    elif change == "extent":
        segment.end = 1.1
    elif change == "word_extent":
        segment.words[-1].end = 0.9
    elif change == "missing_words":
        segment.words = []
    else:
        segment.text = "different"
    request, pcm, duration = worker.decode_request(request_bytes())
    with pytest.raises(ValueError):
        worker.infer(request, pcm, duration, descriptor, "d" * 64)


def test_empty_actual_model_result(pinned, model_mock):
    _, descriptor = pinned
    _, model, _ = model_mock
    model.transcribe.return_value = (iter([]), SimpleNamespace(language="nl"))
    request, pcm, duration = worker.decode_request(request_bytes(glossary=[]))
    answer = worker.infer(request, pcm, duration, descriptor, "d" * 64)["answer"]
    assert ASRAnswer.model_validate(answer).outcome == "empty"
    assert model.transcribe.call_args.kwargs["hotwords"] is None


@pytest.mark.parametrize("change,status", [("host", 403), ("origin", 403), ("transfer", 415), ("mime", 415),
                                           ("length", 413), ("missing_length", 413), ("duplicate_length", 400), ("body", 400), ("path", 404)])
def test_http_refuses_before_admission_or_inference(monkeypatch, change, status):
    handler = object.__new__(service.Handler)
    handler.path = "/v1/transcribe"
    handler.server = SimpleNamespace(origin="127.0.0.1:1234")
    handler.headers = Message()
    raw = request_bytes()
    for key, value in {"Host": handler.server.origin, "Content-Type": "application/json", "Content-Length": str(len(raw))}.items():
        handler.headers[key] = value
    if change == "host":
        handler.headers.replace_header("Host", "localhost:1234")
    elif change == "origin":
        handler.headers["Origin"] = "https://example.org"
    elif change == "transfer":
        handler.headers["Transfer-Encoding"] = "chunked"
    elif change == "mime":
        handler.headers.replace_header("Content-Type", "text/plain")
    elif change == "length":
        handler.headers.replace_header("Content-Length", str(worker.MAX_REQUEST + 1))
    elif change == "missing_length":
        del handler.headers["Content-Length"]
    elif change == "duplicate_length":
        handler.headers["Content-Length"] = str(len(raw))
    elif change == "path":
        handler.path = "/asr"
    else:
        raw = raw[:-1]
    handler.rfile = io.BytesIO(raw)
    handler.reply = Mock()
    monkeypatch.setattr(service, "admit", Mock(side_effect=AssertionError("must refuse first")))
    handler.do_POST()
    assert handler.reply.call_args.args[0] == status


@pytest.mark.parametrize("reason", ["disconnect", "deadline", "interrupt"])
def test_inference_group_killed_and_joined(monkeypatch, reason):
    """Exercise real OS child cleanup with a sleeping stand-in, without importing models."""
    real_popen = subprocess.Popen
    spawned = []

    def stand_in(command, **kwargs):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(service.subprocess, "Popen", stand_in)
    left, right = socket.socketpair()
    if reason == "disconnect":
        right.close()
    elif reason == "deadline":
        clock = iter([0, 61, 62])
        monkeypatch.setattr(service.time, "monotonic", lambda: next(clock))
    else:
        monkeypatch.setattr(service.select, "select", Mock(side_effect=KeyboardInterrupt))
    exception = {"disconnect": ConnectionAbortedError, "deadline": subprocess.TimeoutExpired, "interrupt": KeyboardInterrupt}[reason]
    try:
        with pytest.raises(exception):
            service.run_worker(b"request", "/operator/descriptor", "d" * 64, left)
        assert spawned[0].returncode == -signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            os.kill(spawned[0].pid, 0)
    finally:
        left.close()
        right.close()


def test_parent_only_sigterm_joins_live_group(tmp_path):
    """Launch the actual HTTP module with a sleeping model stand-in and signal only its parent."""
    event = tmp_path / "events.jsonl"
    bootstrap = tmp_path / "parent.py"
    bootstrap.write_text(f'''import sys, subprocess
sys.path.insert(0, {str(Path(service.__file__).parent)!r})
import local_asr_service as service
service.admit = lambda *args: {{}}
real = subprocess.Popen
def stand_in(command, **kwargs):
    return real([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
service.subprocess.Popen = stand_in
sys.argv = ["service", "--descriptor", "/fixture", "--expected-descriptor-sha256", "fixture"]
service.main()
''')
    with event.open("wb") as log:
        parent = subprocess.Popen([sys.executable, "-B", str(bootstrap)], stdout=log, stderr=log)
        client = None
        try:
            deadline = time.monotonic() + 5
            while not event.read_bytes() and parent.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            ready = json.loads(event.read_text().splitlines()[0])
            client = socket.create_connection((ready["host"], ready["port"]), timeout=2)
            raw = request_bytes()
            client.sendall(f'POST /v1/transcribe HTTP/1.1\r\nHost: {ready["host"]}:{ready["port"]}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n'.encode() + raw)
            while len(event.read_text().splitlines()) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            assert json.loads(event.read_text().splitlines()[1])["event"] == "worker_started"
            parent.send_signal(signal.SIGTERM)
            assert parent.wait(timeout=5) == 0
            joined = json.loads(event.read_text().splitlines()[-1])
            assert joined["event"] == "worker_joined" and joined["returncode"] == -signal.SIGKILL
            with pytest.raises(ProcessLookupError):
                os.kill(joined["worker_pid"], 0)
            with pytest.raises(ProcessLookupError):
                os.killpg(joined["worker_pid"], 0)
        finally:
            if client is not None:
                client.close()
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)


def test_full_bounded_input_survives_slow_child_admission(monkeypatch):
    """Delay stdin reading beyond the poll interval and verify every submitted byte arrives."""
    real_popen = subprocess.Popen
    spawned = []

    def slow_reader(command, **kwargs):
        assert command[:4] == [service.local_asr_launch.TRUSTED_PYTHON, "-I", "-S", "-B"]
        assert command[4:7] == [str(Path(service.__file__).with_name("local_asr_launch.py")), "--entry", "worker"]
        code = ('import sys,time,json,hashlib; time.sleep(.25); data=sys.stdin.buffer.read(); '
                'print(json.dumps({"receipt":{"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}}))')
        process = real_popen([sys.executable, "-c", code], **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(service.subprocess, "Popen", slow_reader)
    raw = b"x" * worker.MAX_REQUEST
    left, right = socket.socketpair()
    try:
        receipt = service.run_worker(raw, "/fixture", "d" * 64, left)["receipt"]
        assert receipt["bytes"] == len(raw) and receipt["sha256"] == hashlib.sha256(raw).hexdigest()
        assert spawned[0].returncode == 0
        with pytest.raises(ProcessLookupError):
            os.kill(spawned[0].pid, 0)
    finally:
        left.close()
        right.close()
