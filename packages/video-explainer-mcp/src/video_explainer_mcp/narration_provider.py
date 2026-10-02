"""Independently owned optional REST contracts and deterministic local tone provider.

Behavioral requirements credit Qwen-MM-Plugins (Apache-2.0) and MoneyPrinterTurbo
(MIT, Copyright (c) 2024 Harry). No foreign source, SDK or renderer is imported.
"""

import asyncio
from contextvars import ContextVar
import hashlib
import json
import logging
import os
import re
from urllib.parse import urlsplit

from .narration_pcm import MAX_BYTES, qualify, tone
from .narration_timing import provider_words

MODELS = {"qwen": {"qwen3-tts-flash"}, "minimax": {
    "speech-2.8-hd", "speech-2.8-turbo", "speech-2.6-hd", "speech-2.6-turbo",
    "speech-02-hd", "speech-02-turbo", "speech-01-hd", "speech-01-turbo"}}
LANGUAGES = {"Auto", "English", "Chinese", "German", "Italian", "Portuguese", "Spanish",
             "Japanese", "Korean", "French", "Russian"}
HOSTS = {"qwen": {"global": "dashscope-intl.aliyuncs.com", "cn": "dashscope.aliyuncs.com"},
         "minimax": {"global": "api.minimax.io", "cn": "api.minimax.cn"}}
_quiet = ContextVar("owned_narration_http", default=False)


class _PrivateHTTP(logging.Filter):
    """Suppress httpx's URL-bearing request log only during this owned HTTP scope."""

    def filter(self, record):
        return not _quiet.get()


logging.getLogger("httpx").addFilter(_PrivateHTTP())


class ProviderError(Exception):
    """Expose fixed local reasons and outcomes, never provider bodies or URLs."""

    def __init__(self, reason: str, outcome: str, status=None):
        super().__init__(reason)
        self.reason, self.outcome, self.status = reason, outcome, status


def selection(request) -> dict:
    """Require explicit enable/voice/download-host authority before reading a real key."""
    public = request.model_dump(exclude={"action", "scene_id", "custom_audio"})
    if request.provider == "mock" or request.action == "custom":
        return {**public, "provider": "custom" if request.action == "custom" else "mock", "endpoint": None}
    provider = request.provider
    prefix = f"EXPLAINER_NARRATION_{provider.upper()}"
    if os.environ.get(prefix + "_ENABLED") != "1":
        raise ValueError("Selected narration provider is not explicitly enabled")
    voices = sorted(set(filter(None, (v.strip() for v in os.environ.get(prefix + "_VOICES", "").split(",")))))
    hosts = sorted(set(filter(None, (v.strip().lower() for v in os.environ.get(prefix + "_DOWNLOAD_HOSTS", "").split(",")))))
    if request.voice not in voices or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request.voice):
        raise ValueError("Selected voice is not explicitly allowed")
    if request.model not in MODELS[provider] or request.language not in LANGUAGES:
        raise ValueError("Unsupported selected model or language")
    if not hosts or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) for host in hosts):
        raise ValueError("Configure exact provider download hostnames")
    if provider == "qwen" and request.rate != 1:
        raise ValueError("Selected Qwen HTTP contract has no numeric speed; rate must be 1")
    key = os.environ.get("DASHSCOPE_API_KEY" if provider == "qwen" else "MINIMAX_API_KEY")
    if not key:
        raise ValueError("Selected narration provider credential is missing")
    path = "/api/v1/services/aigc/multimodal-generation/generation" if provider == "qwen" else "/v1/t2a_v2"
    return {**public, "endpoint": f"https://{HOSTS[provider][request.region]}{path}",
            "allowed_voices": voices, "download_hosts": hosts, "credential": key}


def public_selection(selected: dict) -> dict:
    """Bind relevant operator configuration without including environment credentials."""
    return {key: value for key, value in selected.items() if key != "credential"}


def download_url(value, selected: dict) -> str:
    """Allow only HTTPS on exact configured hosts, without credentials, redirects or ports."""
    if not isinstance(value, str):
        raise ProviderError("provider_download_url_invalid", "accepted")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in selected["download_hosts"] or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise ProviderError("provider_download_url_refused", "accepted")
    return value


def http_client():
    """Load the separately declared HTTP extra only for an enabled real provider."""
    import httpx

    return httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False)


async def response_bytes(client, method: str, url: str, maximum: int, *, body=None, key=None) -> bytes:
    """Bound streamed response bytes; POST authentication is never forwarded to GET."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with client.stream(method, url, json=body, headers=headers, follow_redirects=False) as response:
        if not 200 <= response.status_code < 300:
            raise ProviderError("provider_http_status", "failed" if method == "POST" else "accepted", response.status_code)
        chunks, total = [], 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > maximum:
                raise ProviderError("provider_response_too_large", "unknown" if method == "POST" else "accepted")
            chunks.append(chunk)
        return b"".join(chunks)


def metadata(result: dict, provider: str, credential: str) -> dict:
    """Retain finite numeric usage and a safe identifier, excluding arbitrary provider text."""
    original = result.get("usage", {}) if provider == "qwen" else result.get("extra_info", {})
    fields = ("characters",) if provider == "qwen" else ("usage_characters", "usage_voice_count", "audio_length")
    usage = {key: original[key] for key in fields if isinstance(original, dict) and type(original.get(key)) is int and original[key] >= 0}
    request_id = result.get("request_id") if provider == "qwen" else result.get("trace_id")
    return {"usage": usage, "usage_authority": "provider_reported; audio_length is not measured duration",
            "request_id": request_id if isinstance(request_id, str) and credential not in request_id and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) else None}


def payload(text: str, selected: dict) -> dict:
    """Build the selected current HTTP body without inventing provider parameters."""
    if selected["provider"] == "qwen":
        return {"model": selected["model"], "input": {"text": text, "voice": selected["voice"], "language_type": selected["language"]}}
    return {"model": selected["model"], "text": text, "stream": False, "output_format": "hex",
            "language_boost": "auto" if selected["language"] == "Auto" else selected["language"],
            "subtitle_enable": True, "subtitle_type": "word",
            "voice_setting": {"voice_id": selected["voice"], "speed": selected["rate"], "vol": 1, "pitch": 0},
            "audio_setting": {"sample_rate": 24000, "format": "wav", "channel": 1}}


async def real_sentence(text: str, selected: dict, returned) -> dict:
    """Make exactly one POST and retain returned audio before alignment/local admission."""
    provider = selected["provider"]
    if len(text) > (600 if provider == "qwen" else 9999):
        raise ProviderError("provider_text_limit", "unrun")
    async with http_client() as client:
        raw = await response_bytes(client, "POST", selected["endpoint"], MAX_BYTES * 2 + 1024 * 1024, body=payload(text, selected), key=selected["credential"])
        terminal = False
        try:
            result = json.loads(raw)
            details = metadata(result, provider, selected["credential"])
            if provider == "minimax":
                status = result["base_resp"]["status_code"]
                if type(status) is not int:
                    raise ProviderError("provider_status_invalid", "unknown")
                if status != 0:
                    raise ProviderError("provider_business_status", "failed", status)
                if type(result["data"]["status"]) is not int or result["data"]["status"] != 2:
                    raise ProviderError("provider_completion_unknown", "unknown")
                terminal = True
                returned(None, details)
                audio = bytes.fromhex(result["data"]["audio"])
                if not audio or len(audio) > MAX_BYTES:
                    raise ProviderError("provider_audio_empty_or_large", "accepted")
                returned(audio, details)
                _, measured = qualify(audio)
                if measured["sample_rate"] != 24000:
                    raise ProviderError("provider_audio_format_mismatch", "accepted")
                url = download_url(result["data"]["subtitle_file"], selected)
                subtitles = json.loads(await response_bytes(client, "GET", url, 2 * 1024 * 1024))
                words = provider_words(subtitles, text, measured["frames"], measured["sample_rate"])
            else:
                url = download_url(result["output"]["audio"]["url"], selected)
                terminal = True
                returned(None, {**details, "download_identity_sha256": hashlib.sha256(url.encode()).hexdigest()})
                audio = await response_bytes(client, "GET", url, MAX_BYTES)
                returned(audio, details)
                qualify(audio)
                words = None
            return {"audio": audio, "words": words, "alignment": "provider_declared" if words else "absent_selected_provider_contract", **details}
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("provider_payload_or_audio_invalid", "accepted" if terminal else "unknown") from error


async def synthesize(text: str, selected: dict, returned) -> dict:
    """Return one measured candidate without POST retries or implicit provider fallback."""
    if selected["provider"] == "mock":
        audio, words = tone(text, selected["rate"])
        returned(audio, {"usage": {}, "request_id": None})
        await asyncio.sleep(0)
        return {"audio": audio, "words": words, "alignment": "synthetic_event; tones are not speech", "usage": {}}
    token = _quiet.set(True)
    try:
        async with asyncio.timeout(60):
            return await real_sentence(text, selected, returned)
    except (ProviderError, asyncio.CancelledError):
        raise
    except Exception as error:
        raise ProviderError("provider_request_outcome_unknown", "unknown") from error
    finally:
        _quiet.reset(token)
