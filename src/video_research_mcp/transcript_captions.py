"""Strict bounded caption formats retaining milliseconds and numeric spoken text."""

import csv
import io
import json
import re

from .models.transcript import CaptionDocument, TranscriptSegment
from .transcript_timing import digest, validate_segments

MAX_CAPTION_BYTES = 1024 * 1024
FALSE_CLAIMS = {"speech_accuracy_verified", "word_alignment_verified", "speaker_identity_verified", "diarization_verified"}


def strict_json(data: bytes):
    """Reject duplicate keys and nonfinite JSON instead of repairing a provider/caption answer."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate caption JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite caption JSON")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def assertion_provenance(value: dict) -> None:
    """Reject supplied evidence that asserts verified acoustic or identity conclusions."""
    for key, item in value.items():
        if key in FALSE_CLAIMS and item is not False:
            raise ValueError("Caption provenance contradicts unverified source assertions")
        if isinstance(item, dict):
            assertion_provenance(item)
        elif isinstance(item, list):
            for nested in item:
                if isinstance(nested, dict):
                    assertion_provenance(nested)


def _clock(value: str, kind: str) -> float:
    separator = "," if kind == "srt" else r"\."
    pattern = rf"(?:(\d{{2,}}):)?(\d{{2}}):(\d{{2}}){separator}(\d{{3}})"
    match = re.fullmatch(pattern, value)
    if not match or (kind == "srt" and match[1] is None) or int(match[2]) >= 60 or int(match[3]) >= 60:
        raise ValueError("Malformed caption millisecond clock")
    return int(match[1] or 0) * 3600 + int(match[2]) * 60 + int(match[3]) + int(match[4]) / 1000


def _timed_text(text: str, kind: str) -> list:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if kind == "vtt":
        if not lines or lines.pop(0) != "WEBVTT":
            raise ValueError("VTT requires an exact WEBVTT header")
    blocks = re.split(r"\n[ \t]*\n", "\n".join(lines).strip("\n"))
    records = []
    for number, block in enumerate(blocks, 1):
        rows = block.split("\n")
        if not block.strip():
            continue
        identity = str(number)
        if " --> " not in rows[0]:
            identity = rows.pop(0)
            if not identity or (kind == "srt" and not identity.isdecimal()):
                raise ValueError("SRT requires a numeric record index")
        elif kind == "srt":
            raise ValueError("SRT requires a numeric record index")
        if len(rows) < 2 or len(rows[0].split(" --> ")) != 2:
            raise ValueError("Malformed caption cue or missing text")
        start, end = rows.pop(0).split(" --> ")
        records.append(TranscriptSegment(id=identity, start_seconds=_clock(start, kind),
            end_seconds=_clock(end, kind), text="\n".join(rows)))
    return records


def _tsv(text: str) -> list:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", strict=True)
    fields = reader.fieldnames
    seconds = ["start_seconds", "end_seconds", "text", "speaker_id"]
    millis = ["start_ms", "end_ms", "text", "speaker_id"]
    if fields not in [seconds, ["id", *seconds], millis, ["id", *millis]]:
        raise ValueError("TSV requires declared seconds or millisecond columns, text and speaker_id; id is optional")
    milliseconds = "start_ms" in fields
    start_key, end_key = ("start_ms", "end_ms") if milliseconds else ("start_seconds", "end_seconds")
    records = []
    for row in reader:
        if None in row or None in row.values() or (milliseconds and (not row[start_key].isdecimal() or not row[end_key].isdecimal())):
            raise ValueError("Malformed TSV record or declared clock")
        start, end = float(row[start_key]), float(row[end_key])
        value = {"start_seconds": start / 1000 if milliseconds else start,
                 "end_seconds": end / 1000 if milliseconds else end,
                 "text": row["text"], "speaker_id": row["speaker_id"] or None}
        records.append(TranscriptSegment(id=row.get("id") or "caption-" + digest(value)[:24], **value))
    return records


def parse_captions(data: bytes, kind: str, extent: float) -> tuple[list, dict]:
    """Parse complete exact bytes; their timing/speaker/word values remain source assertions."""
    if type(data) is not bytes or not 0 < len(data) <= MAX_CAPTION_BYTES:
        raise ValueError("Caption bytes must be nonempty and at most1MiB")
    text = data.decode("utf-8-sig")
    provenance = {}
    if kind == "json":
        document = CaptionDocument.model_validate(strict_json(text.encode()))
        assertion_provenance(document.provenance)
        records, provenance = document.segments, document.provenance
    elif kind in {"srt", "vtt"}:
        records = _timed_text(text, kind)
    elif kind == "tsv":
        records = _tsv(text)
    else:
        raise ValueError("Unsupported caption format")
    if len(records) > 512:
        raise ValueError("Caption record population exceeds512")
    return validate_segments(records, extent), {"provided_provenance": provenance,
        "timing_status": "source_assertion", "speaker_status": "source_assertion_or_unknown",
        "word_status": "source_assertion_if_supplied; absent otherwise", "acoustic_alignment_verified": False}


def preferred_caption(request):
    """Choose a deterministic origin then caller order, without silent parse fallback."""
    return next((source for origin in request.caption_preference for source in request.caption_sources
                 if source.origin == origin), None)
