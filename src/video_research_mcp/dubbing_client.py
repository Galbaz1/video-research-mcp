"""Bounded, authenticated HTTP for an independently operated dubbing service.

Wire contract: Qwen-MM-Plugins 07736672525443c7f8a3f6405eed37d2236f023f,
Apache-2.0. This is a first-party implementation; no service or model is bundled.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import wave

import httpx

from .media_snapshot import checked_path
from .models.video_dubbing import DubbingService, Interval, VadSettings
from .vision_http import (
    _destination, _joined_cleanup, _LimitedBackend, _peer_trace, _quiet_transport_logs,
    _request_headers, _response_bytes,
)

MAX_AUDIO_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 350 * 1024 * 1024
MAX_RESPONSE_BYTES = 700 * 1024 * 1024
VAD_PARAMETERS = {"threshold": 0.5, "hop_size": 256, "min_speech": 0.2,
                  "min_silence": 0.3, "pad": 0.1}


class DubbingError(ValueError):
    """A fixed local reason containing no remote bodies or credentials."""


def bounded_bytes(path: Path, limit: int, reason: str) -> bytes:
    """Read one fenced regular descriptor and reject size changes during reading."""
    path = checked_path(str(path))
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (FileNotFoundError, NotADirectoryError):
        raise DubbingError(reason) from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise DubbingError(reason)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(descriptor)
        if len(data) > limit or len(data) != before.st_size or after.st_size != before.st_size:
            raise DubbingError(reason)
    finally:
        os.close(descriptor)
    return data


def canonical(value: dict) -> bytes:
    """Encode exact JSON request and signature bytes without nonfinite numbers."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def write_json(path: Path, value: dict) -> None:
    """Atomically replace an owned journal or report inside the local fence."""
    path = checked_path(str(path))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def selected_service() -> tuple[DubbingService, str | None]:
    """Read only the operator's origin, loopback policy and environment token."""
    url = os.environ.get("QWEN_MM_DUBBING_SERVER_URL", "")
    if not url:
        raise DubbingError("service_missing")
    local = os.environ.get("VRM_DUBBING_LOCAL", "false")
    if local not in {"true", "false"}:
        raise DubbingError("service_policy_invalid")
    try:
        service = DubbingService(base_url=url, local=local == "true")
    except ValueError:
        raise DubbingError("service_origin_invalid") from None
    credential = os.environ.get("VRM_DUBBING_API_KEY")
    if not service.local and not credential:
        raise DubbingError("service_credential_missing")
    if credential and any(ord(c) < 33 or ord(c) > 126 for c in credential):
        raise DubbingError("service_credential_invalid")
    return service, credential


async def exchange(url: str, *, headers: dict, content: bytes, method: str,
                   local: bool, response_limit: int) -> tuple[int, bytes]:
    """Use the existing peer fence with explicit audio-sized receive bounds.

    Args:
        url: Fixed endpoint on the operator-selected origin.
        headers: Internal headers with the environment credential.
        content: Bounded JSON bytes, never logged.
        method: GET health or POST service operation.
        local: Operator policy requiring literal loopback when true.
        response_limit: Per-operation maximum raw reception including framing.

    Returns:
        HTTP status and bounded raw response bytes, without retries or redirects.
    """
    if len(content) > MAX_REQUEST_BYTES:
        raise DubbingError("request_too_large")
    prepared = _request_headers(headers, "", content)
    client, primary, streams = None, None, []
    try:
        with _quiet_transport_logs():
            async with asyncio.timeout(900):
                target, hostname, authority, selected, port = await _destination(url, local)
                prepared["Host"] = authority
                trace, attested = _peer_trace(selected, port, streams, require_limited=True)
                transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False, http2=False)
                transport._pool._network_backend = _LimitedBackend(
                    transport._pool._network_backend, response_limit)
                client = httpx.AsyncClient(transport=transport, trust_env=False,
                                          follow_redirects=False, timeout=900)
                async with client.stream(method, target, headers=prepared, content=content,
                                         extensions={"sni_hostname": hostname, "trace": trace}) as response:
                    if not attested():
                        raise DubbingError("service_peer_unverified")
                    return response.status_code, await _response_bytes(response, response_limit)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if client is not None:
            await _joined_cleanup(client, streams, primary)


def _object(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise DubbingError("service_json_invalid") from None
    if not isinstance(value, dict):
        raise DubbingError("service_json_invalid")
    return value


async def request(endpoint: str, payload: dict | None, journal: Path | None = None) -> dict:
    """Persist intent before one POST; unknown effects remain occupied on resume."""
    if journal is not None:
        journal = checked_path(str(journal))
        cache = checked_path(str(journal.with_suffix(".response.json")))
        claim = checked_path(str(journal.with_suffix(".claim")))
    service, credential = selected_service()
    body = canonical(payload) if payload is not None else b""
    signature = hashlib.sha256(canonical({"origin": service.base_url, "endpoint": endpoint,
                                         "body_sha256": hashlib.sha256(body).hexdigest()})).hexdigest()
    if len(body) > MAX_REQUEST_BYTES:
        raise DubbingError("request_too_large")
    if journal is not None and journal.exists():
        intent = _object(bounded_bytes(journal, MAX_JSON_BYTES, "service_intent_missing_or_too_large"))
        if intent.get("request_sha256") != signature or intent.get("state") != "response_saved":
            raise DubbingError("service_effect_requires_reconciliation")
        raw = bounded_bytes(cache, MAX_RESPONSE_BYTES, "service_response_cache_changed")
        if hashlib.sha256(raw).hexdigest() != intent["response_sha256"]:
            raise DubbingError("service_response_cache_changed")
        return _object(raw)
    if journal is not None:
        journal.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            with claim.open("xb"):
                pass
        except FileExistsError:
            raise DubbingError("service_effect_requires_reconciliation") from None
        write_json(journal, {"request_sha256": signature, "state": "intent"})
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    try:
        status, raw = await exchange(service.base_url.rstrip("/") + endpoint, headers=headers,
                                     content=body, method="GET" if payload is None else "POST",
                                     local=service.local,
                                     response_limit=16384 if payload is None else MAX_RESPONSE_BYTES)
    except PermissionError:
        raise DubbingError("service_peer_policy_refused") from None
    except (OSError, TimeoutError, httpx.HTTPError):
        raise DubbingError("service_transport_unknown") from None
    if journal is not None:
        cache.write_bytes(raw)
        write_json(journal, {"request_sha256": signature, "state": "response_saved" if 200 <= status < 300 else "http_failed",
                            "http_status": status, "response_sha256": hashlib.sha256(raw).hexdigest()})
    if not 200 <= status < 300:
        raise DubbingError("service_http_failed")
    return _object(raw)


async def health() -> dict:
    """Return terminal readiness evidence without launching or downloading models."""
    try:
        data = await request("/health", None)
        if type(data.get("model_loaded")) is not bool or not isinstance(data.get("status"), str):
            raise DubbingError("service_health_invalid")
        ready = data["model_loaded"]
        return {"state": "ready" if ready else "unready", "terminal": not ready,
                "model_loaded": ready, "service_acceptance": "UNQUALIFIED"}
    except Exception as exc:
        return {"state": "unavailable", "terminal": True, "model_loaded": None,
                "reason": str(exc) if isinstance(exc, DubbingError) else "service_boundary_failed",
                "exception_type": type(exc).__name__, "service_acceptance": "UNQUALIFIED"}


def audio_bytes(path: Path) -> bytes:
    """Read a fenced regular PCM WAV under the upload limit."""
    data = bounded_bytes(path, MAX_AUDIO_BYTES, "audio_missing_or_too_large")
    pcm_metadata(data)
    return data


def pcm_metadata(data: bytes) -> dict:
    """Validate locally held complete PCM data instead of service duration claims."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames, channels, width, rate = wav.getnframes(), wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            if (wav.getcomptype() != "NONE" or width != 2 or channels not in {1, 2}
                    or not 8000 <= rate <= 192000 or frames <= 0
                    or len(wav.readframes(frames)) != frames * channels * width):
                raise DubbingError("audio_pcm_invalid")
    except (wave.Error, EOFError):
        raise DubbingError("audio_pcm_invalid") from None
    return {"duration_sec": frames / rate, "sample_rate": rate, "channels": channels}


def save_audio(encoded: str, path: Path) -> dict:
    """Bound/decode returned WAV bytes and record only the local content identity."""
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_AUDIO_BYTES + 2) // 3):
        raise DubbingError("returned_audio_missing_or_too_large")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise DubbingError("returned_audio_base64_invalid") from None
    metadata = pcm_metadata(data)
    path = checked_path(str(path))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        if bounded_bytes(path, MAX_AUDIO_BYTES, "local_audio_changed") != data:
            raise DubbingError("local_audio_changed")
    else:
        with path.open("xb") as stream:
            stream.write(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), **metadata}


async def separate(source: Path, output: Path, model: str = "htdemucs") -> dict:
    """Upload source PCM and store both returned stems locally under fixed names."""
    audio = audio_bytes(source)
    payload = {"audio_base64": base64.b64encode(audio).decode(), "audio_filename": source.name,
               "model": model, "two_stems": "vocals", "mp3": False, "return_audio": True}
    output = checked_path(str(output))
    data = await request("/separate", payload, output / "separation.intent.json")
    stems = data.get("stems_base64")
    if not isinstance(stems, dict) or not {"vocals", "no_vocals"} <= stems.keys():
        raise DubbingError("separation_stems_missing")
    result = {name: save_audio(stems[name], output / f"{name}.wav") for name in ("vocals", "no_vocals")}
    duration = pcm_metadata(audio)["duration_sec"]
    if any(abs(stem["duration_sec"] - duration) > 0.35 for stem in result.values()):
        raise DubbingError("separation_duration_mismatch")
    return result


async def vad(source: Path, output: Path, settings: VadSettings | None = None) -> dict:
    """Validate exact service VAD fields, preserving speech-presence uncertainty."""
    audio = audio_bytes(source)
    parameters = (settings or VadSettings()).model_dump()
    data = await request("/vad", {"audio_base64": base64.b64encode(audio).decode(),
                                 "audio_filename": source.name, "separate_first": False, **parameters},
                         checked_path(str(output)) / "vad.intent.json")
    duration, rate, segments = data.get("duration"), data.get("sample_rate"), data.get("segments")
    if (type(duration) not in {int, float} or not 0 < duration <= 86400
            or type(rate) is not int or not 0 < rate <= 192000 or not isinstance(segments, list)
            or len(segments) > 10000 or abs(duration - pcm_metadata(audio)["duration_sec"]) > 0.35):
        raise DubbingError("vad_metadata_invalid")
    normalized, previous = [], 0.0
    try:
        for item in segments:
            interval = Interval(start_sec=item["start_time"], end_sec=item["end_time"])
            if interval.start_sec < previous or interval.end_sec > duration + 0.05:
                raise ValueError("invalid interval")
            previous = interval.end_sec
            normalized.append(interval.model_dump())
    except (ValueError, KeyError, TypeError):
        raise DubbingError("vad_intervals_invalid") from None
    return {"duration_sec": float(duration), "sample_rate": rate, "segments": normalized}


async def tts(text: str, reference: Path, output: Path) -> dict:
    """Synthesize one journaled candidate using default service emotion controls."""
    if not text.strip() or len(text) > 10000:
        raise DubbingError("tts_text_invalid")
    output = checked_path(str(output))
    audio = audio_bytes(reference)
    data = await request("/tts", {"text": text, "voice_base64": base64.b64encode(audio).decode(),
                                 "voice_filename": reference.name, "trim_silence": True,
                                 "trim_ref_silence": True, "return_audio": True},
                         output.with_suffix(".intent.json"))
    result = save_audio(data.get("audio_base64"), output)
    if (type(data.get("duration_sec")) not in {int, float}
            or not math.isfinite(data["duration_sec"])
            or abs(data["duration_sec"] - result["duration_sec"]) > 0.05
            or type(data.get("sample_rate")) is not int or data["sample_rate"] != result["sample_rate"]):
        raise DubbingError("tts_metadata_mismatch")
    return result
