"""Explicit timed loopback ASR wire with source-bound inference receipts."""

import base64
import hashlib
import json
import math

from .models.transcript import ASRAnswer
from .transcript_captions import strict_json


def payload(request, window):
    """Bind the actual prepared WAV and forward the supported language/glossary hints."""
    wav = window["parts"][0]["data"]
    value = {"audio": "data:audio/wav;base64," + base64.b64encode(wav).decode(),
             "audio_sha256": hashlib.sha256(wav).hexdigest(),
             "language": request.language, "glossary": request.glossary}
    encoded = json.dumps(value, separators=(",", ":")).encode()
    if len(wav) > 1024 * 1024 or len(encoded) > 2 * 1024 * 1024:
        raise ValueError("Timed local ASR payload exceeds its admitted wire bound")
    return value, encoded


def admit_answer(data, submitted, service, duration):
    """Validate returned inference and exact submitted identity without asserting accuracy."""
    if len(data) > 128 * 1024:
        raise ValueError("Timed local ASR answer exceeds128KiB")
    value = strict_json(data)
    if not isinstance(value, dict) or set(value) != {"protocol", "answer", "receipt"} or value["protocol"] != service.protocol:
        raise ValueError("Timed local ASR returned an unsupported envelope")
    receipt = value["receipt"]
    if not isinstance(receipt, dict) or receipt.get("descriptor_sha256") != service.expected_descriptor_sha256 or receipt.get("audio_sha256") != submitted["audio_sha256"]:
        raise ValueError("Timed local ASR receipt differs from the admitted descriptor or WAV")
    measured = receipt.get("audio_duration_seconds")
    if type(measured) not in (int, float) or not math.isfinite(measured) or abs(measured - duration) > 1 / 16000:
        raise ValueError("Timed local ASR duration differs from the submitted PCM clock")
    settings = receipt.get("settings", {})
    if settings.get("language") != submitted["language"] or settings.get("hotwords") != (" ".join(submitted["glossary"]) or None) or settings.get("word_timestamps") is not True:
        raise ValueError("Timed local ASR did not preserve required language/glossary/word settings")
    if any(receipt.get(key) is not False for key in ("speech_accuracy_verified", "word_alignment_verified", "speaker_identity_verified")):
        raise ValueError("Timed local ASR cannot assert benchmark or speaker acceptance")
    answer = ASRAnswer.model_validate(value["answer"])
    if any(c.speaker_id is not None or not c.words for c in answer.segments):
        raise ValueError("Timed local ASR requires actual words and unknown speaker identities")
    return answer, receipt

