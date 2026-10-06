"""Stdlib-only worker file admission; native imports and the entrypoint are forbidden."""

import hashlib
import importlib.util
import io
import os
import wave
from pathlib import Path

import pytest

from video_research_mcp import speakers


@pytest.fixture()
def worker(monkeypatch):
    spec = importlib.util.spec_from_file_location("r104_worker_boundary", speakers.WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*_args):
        raise AssertionError("native imports/entrypoint forbidden in source tests")

    monkeypatch.setattr(module, "_modules", forbidden)
    monkeypatch.setattr(module, "main", forbidden)
    return module


def _wav(pcm, channels=1, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(pcm)
    return buffer.getvalue()


def _request(tmp_path, data, count):
    model = tmp_path / "synthetic-model"
    model.write_bytes(b"synthetic")
    pin = {"path": str(model), "sha256": hashlib.sha256(model.read_bytes()).hexdigest()}
    wav = tmp_path / "input.wav"
    wav.write_bytes(data)
    return {
        "runtime": {"segmentation_model": pin, "embedding_model": pin},
        "wav": {
            "path": str(wav),
            "sha256": hashlib.sha256(data).hexdigest(),
            "sample_count": count,
        },
    }


@pytest.mark.parametrize("symlink", [False, True])
def test_r104_replacement_between_hash_and_decode_uses_original_bytes(
    worker, tmp_path, monkeypatch, symlink
):
    """GIVEN the path is swapped at decode THEN verified PCM remains bound to the original digest."""
    pcm = b"\x01\x00" * 8
    request = _request(tmp_path, _wav(pcm), 8)
    path = Path(request["wav"]["path"])
    replacement = tmp_path / "replacement.wav"
    replacement.write_bytes(_wav(b"\x02\x00" * 8))
    original_open = wave.open

    def swap_at_decode(file, mode):
        if symlink:
            path.unlink()
            path.symlink_to(replacement)
        else:
            os.replace(replacement, path)
        return original_open(file, mode)

    monkeypatch.setattr(worker.wave, "open", swap_at_decode)
    assert worker._verified_pcm(request) == pcm


def test_r104_wav_symlink_is_refused(worker, tmp_path):
    request = _request(tmp_path, _wav(b"\0\0" * 8), 8)
    link = tmp_path / "link.wav"
    link.symlink_to(request["wav"]["path"])
    request["wav"]["path"] = str(link)
    with pytest.raises((OSError, SystemExit)):
        worker._verified_pcm(request)


def test_r104_nonregular_wav_is_refused_without_blocking(worker, tmp_path):
    request = _request(tmp_path, _wav(b"\0\0" * 8), 8)
    request["wav"]["path"] = str(tmp_path)
    with pytest.raises((OSError, SystemExit)):
        worker._verified_pcm(request)


@pytest.mark.parametrize(
    "kind",
    [
        "oversize",
        "truncated",
        "wrong_count",
        "empty",
        "rate",
        "stereo",
        "hash",
        "float_count",
        "bool_count",
    ],
)
def test_r104_wav_population_refusals(worker, tmp_path, kind):
    data, count = _wav(b"\0\0" * 8), 8
    if kind == "oversize":
        data += b"x" * (8 * 1024 * 1024)
    elif kind == "truncated":
        data = data[:-2]
    elif kind == "wrong_count":
        count = 9
    elif kind == "float_count":
        count = 8.0
    elif kind == "bool_count":
        data, count = _wav(b"\0\0"), True
    elif kind == "empty":
        data, count = _wav(b""), 0
    elif kind == "rate":
        data = _wav(b"\0\0" * 8, rate=8000)
    elif kind == "stereo":
        data, count = _wav(b"\0\0" * 8, channels=2), 4
    request = _request(tmp_path, data, count)
    if kind == "hash":
        request["wav"]["sha256"] = "0" * 64
    with pytest.raises(SystemExit):
        worker._verified_pcm(request)
