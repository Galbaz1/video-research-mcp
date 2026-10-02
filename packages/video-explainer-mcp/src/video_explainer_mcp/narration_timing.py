"""Validate current provider-declared word/text offsets against measured samples."""

import math


def interval(value: dict, text: str, begin_key: str, end_key: str, text_key: str, frames: int, rate: int) -> dict:
    """Require exact inclusive/exclusive text offsets and finite ordered milliseconds."""
    begin, end = value[begin_key], value[end_key]
    if type(begin) is not int or type(end) is not int or not 0 <= begin < end <= len(text):
        raise ValueError("Subtitle text offsets must be ordered integers within the exact transcript")
    if value[text_key] != text[begin:end]:
        raise ValueError("Subtitle text differs from the exact approved transcript span")
    start, finish = value["time_begin"], value["time_end"]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, finish)):
        raise ValueError("Subtitle milliseconds must be finite")
    if not 0 <= start < finish <= frames * 1000 / rate:
        raise ValueError("Subtitle milliseconds lie outside measured audio")
    first, last = round(start * rate / 1000), round(finish * rate / 1000)
    if not 0 <= first < last <= frames:
        raise ValueError("Subtitle interval has no complete measured sample span")
    return {"text_begin": begin, "text_end": end, "start_frame": first, "end_frame": last}


def provider_words(payload, text: str, frames: int, rate: int) -> list[dict]:
    """Validate a strict complete segment list; never infer absent real word alignment."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("Expected a nonempty provider subtitle segment list")
    words, text_end, audio_end, covered = [], 0, 0, set()
    for segment in payload:
        bounds = interval(segment, text, "text_begin", "text_end", "text", frames, rate)
        if bounds["text_begin"] != text_end or bounds["start_frame"] < audio_end:
            raise ValueError("Subtitle segments must cover the transcript in ordered nonoverlapping spans")
        events = segment.get("timestamped_words")
        if not isinstance(events, list) or not events:
            raise ValueError("Provider word alignment is absent")
        previous_text, previous_audio = bounds["text_begin"], bounds["start_frame"]
        for event in events:
            word = interval(event, text, "word_begin", "word_end", "word", frames, rate)
            if not previous_text <= word["text_begin"] < word["text_end"] <= bounds["text_end"]:
                raise ValueError("Provider words have overlapping or out-of-segment text offsets")
            if not previous_audio <= word["start_frame"] < word["end_frame"] <= bounds["end_frame"]:
                raise ValueError("Provider words have overlapping or out-of-segment sample offsets")
            words.append({"word": event["word"], **word, "alignment": "provider_declared"})
            covered.update(range(word["text_begin"], word["text_end"]))
            previous_text, previous_audio = word["text_end"], word["end_frame"]
        text_end, audio_end = bounds["text_end"], bounds["end_frame"]
    if text_end != len(text):
        raise ValueError("Provider subtitle segments do not cover the exact transcript")
    if any(character.isalnum() and index not in covered for index, character in enumerate(text)):
        raise ValueError("Provider words do not cover the exact transcript's spoken text")
    return words
