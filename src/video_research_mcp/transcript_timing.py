"""Source-clock admission without proportional words or physical speaker identity claims."""

import hashlib
import json

from .models.transcript import ASRAnswer, TranscriptSegment


def digest(value) -> str:
    """Commit finite canonical JSON, including complete interval and word populations."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_segments(segments, extent: float) -> list[TranscriptSegment]:
    """Admit every cue against source extent; overlaps may belong to distinct speakers."""
    records, seen, previous = [], {}, -1.0
    for value in segments:
        cue = TranscriptSegment.model_validate(value)
        if cue.end_seconds > extent + 1e-6 or cue.start_seconds < previous:
            raise ValueError("Caption intervals are unordered or outside the source clock")
        body = cue.model_dump(mode="json")
        if cue.id in seen:
            raise ValueError("Caption record IDs must be unique")
        seen[cue.id] = body
        previous = cue.start_seconds
        records.append(cue)
    return records


def select_captions(segments, start: float, end: float) -> tuple[list, dict]:
    """Keep complete asserted cues intersecting selection and disclose boundary crossings."""
    selected = [c for c in segments if c.start_seconds < end and c.end_seconds > start]
    return selected, {"available": len(segments), "retained": len(selected),
        "omitted_outside_selection": len(segments) - len(selected),
        "boundary_crossing_ids": [c.id for c in selected if c.start_seconds < start or c.end_seconds > end],
        "interval_policy": "complete asserted cue retained; no text/word clipping"}


def project_answer(answer: ASRAnswer, window: dict, source_sha256: str) -> list[TranscriptSegment]:
    """Map WAV-relative actual model values using the measured selected audio origin."""
    selected = window["audio"]["selected_window"]
    origin, end = selected["start_seconds"], selected["end_seconds"]
    previous, records = -1.0, []
    for cue in answer.segments:
        if cue.start_seconds < previous or cue.end_seconds > end - origin + 1e-6:
            raise ValueError("ASR cue lies outside its actual decoded WAV interval or order")
        previous = cue.start_seconds
        value = cue.model_dump(mode="json")
        value.update(start_seconds=cue.start_seconds + origin, end_seconds=cue.end_seconds + origin)
        for word in value["words"]:
            word["start_seconds"] += origin
            word["end_seconds"] += origin
        identity = digest({"source_sha256": source_sha256, "cue": value})
        records.append(TranscriptSegment(id="asr-" + identity[:24], **value))
    return records


def merge_exact(records: list, incoming: list, window_index: int, decisions: list) -> None:
    """Deduplicate exact absolute identity only; repeated text at another time survives."""
    known = {digest(c.model_dump(mode="json")): c for c in records}
    for cue in incoming:
        key = digest(cue.model_dump(mode="json"))
        if key in known:
            decisions.append({"record_id": cue.id, "window_index": window_index,
                              "policy": "exact source-time/text/speaker/word duplicate"})
        else:
            records.append(cue)
            known[key] = cue
    records.sort(key=lambda c: (c.start_seconds, c.end_seconds, c.id))
