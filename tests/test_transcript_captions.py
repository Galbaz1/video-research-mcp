"""Exact caption populations and disclosed export loss; no acoustic accuracy assertion."""

import json

import pytest

from video_research_mcp.models.transcript import CaptionDocument, TranscriptRequest, TranscriptSegment
from video_research_mcp.transcript_captions import parse_captions, preferred_caption
from video_research_mcp.transcript_formats import export_bytes

SHA = "a" * 64


def cue(**updates):
    return TranscriptSegment(id="cue-1", start_seconds=0.1234567, end_seconds=1.9876543,
                             text="123\nHello!", **updates)


@pytest.mark.parametrize("kind,data", [
    ("srt", b"1\n00:00:00,123 --> 00:00:01,987\n123\nHello!\n\n"),
    ("vtt", b"WEBVTT\n\nfirst\n00:00.123 --> 00:01.987\n123\nHello!\n"),
    ("tsv", b"start_seconds\tend_seconds\ttext\tspeaker_id\n0.123\t1.987\t123 Hello!\t\n"),
    ("tsv", b"id\tstart_ms\tend_ms\ttext\tspeaker_id\nfirst\t123\t1987\t123 Hello!\t\n"),
])
def test_numeric_spoken_lines_and_milliseconds_survive(kind, data):
    records, provenance = parse_captions(data, kind, 2)
    assert len(records) == 1
    assert records[0].start_seconds == .123 and records[0].end_seconds == 1.987
    assert records[0].text.startswith("123")
    assert records[0].speaker_id is None and records[0].words == []
    assert provenance["acoustic_alignment_verified"] is False


@pytest.mark.parametrize("kind,data", [
    ("srt", b"00:00:00,000 --> 00:00:01,000\nHi"),
    ("srt", b"1\n00:60:00,000 --> 00:61:00,000\nHi"),
    ("srt", b"1\n00:00:02,000 --> 00:00:01,000\nHi"),
    ("srt", b"1\n00:00:00,000 --> 00:00:04,000\nHi"),
    ("srt", b"1\n00:00:00.000 --> 00:00:01.000\nHi"),
    ("vtt", b"WEBVTT\n\n00:00.000 --> 00:01.000 align:start\nHi"),
    ("vtt", b"WEBVTT\n\nNOTE injected\nHi"),
    ("vtt", b"not WEBVTT\n\n00:00.000 --> 00:01.000\nHi"),
    ("tsv", b"start\tend\ttext\n0\t1\tHi"),
    ("tsv", b"start_seconds\tend_seconds\ttext\tspeaker_id\nnan\t1\tHi\t\n"),
    ("tsv", b"start_seconds\tend_seconds\ttext\tspeaker_id\n0\tinf\tHi\t\n"),
    ("tsv", b"start_ms\tend_ms\ttext\tspeaker_id\n0.5\t1000\tHi\t\n"),
    ("json", b'{"schema_version":true,"segments":[]}'),
    ("json", b'{"segments":[]}'),
    ("json", b'{"schema_version":1,"schema_version":1,"segments":[]}'),
    ("json", b'{"schema_version":1,"segments":[],"provenance":{"word_alignment_verified":true}}'),
    ("srt", b""),
    ("srt", b"\xff"),
])
def test_malformed_assertions_are_refused_without_repair(kind, data):
    with pytest.raises((ValueError, UnicodeError)):
        parse_captions(data, kind, 3)


def test_json_preserves_precision_actual_words_and_unknown_speaker():
    value = {"schema_version": 1, "segments": [{"id": "native-7", "start_seconds": .1234567,
        "end_seconds": .9876543, "text": "One two", "speaker_id": None,
        "words": [{"text": "One", "start_seconds": .1234567, "end_seconds": .4},
                  {"text": "two", "start_seconds": .5, "end_seconds": .9876543}]}]}
    records, provenance = parse_captions(json.dumps(value).encode(), "json", 2)
    assert records[0].model_dump(mode="json") == value["segments"][0]
    data, loss = export_bytes("json", records, provenance, [])
    assert CaptionDocument.model_validate_json(data).segments == records
    assert loss["lost_fields"] == []


@pytest.mark.parametrize("kind", ["srt", "vtt", "tsv"])
def test_roundtrip_timed_export_quantizes_only_declared_milliseconds(kind):
    record = cue()
    data, loss = export_bytes(kind, [record], {}, [])
    restored, _ = parse_captions(data, kind, 3)
    assert restored[0].start_seconds == .123 and restored[0].end_seconds == 1.988
    assert restored[0].text == record.text
    assert "words" in loss["lost_fields"] and "0.5ms" in loss["time_quantization"]


def test_text_explicitly_loses_clocks_and_alignment():
    data, loss = export_bytes("text", [cue()], {}, [])
    assert data.decode() == "123\nHello!"
    assert set(loss["lost_fields"]) == {"ids", "times", "words", "speakers", "provenance"}


def test_quantization_does_not_invent_positive_duration():
    record = TranscriptSegment(id="tiny", start_seconds=.0001, end_seconds=.0002, text="Hi")
    with pytest.raises(ValueError, match="collapses"):
        export_bytes("srt", [record], {}, [])


def test_origin_preference_is_complete_deterministic_and_explicit():
    sources = [{"origin": origin, "source_sha256": SHA, "file_path": f"/{origin}.srt", "expected_sha256": SHA}
               for origin in ["sidecar", "native", "uploaded", "embedded"]]
    request = TranscriptRequest(file_path="/source.wav", expected_source_sha256=SHA,
        output_directory="/absent", caption_sources=sources)
    assert preferred_caption(request).origin == "uploaded"
    changed = request.model_copy(update={"caption_preference": ["native", "sidecar", "uploaded", "embedded"]})
    assert preferred_caption(changed).origin == "native"


@pytest.mark.parametrize("updates", [
    {"local_only": True, "backend": "gemini"},
    {"fallback_backend": "qwen"},
    {"caption_preference": ["uploaded"]},
    {"caption_sources": [{"origin": "native", "source_sha256": "b" * 64, "file_path": "/n.srt", "expected_sha256": SHA}]},
    {"action": "readback"},
    {"limits": {"max_frames": 1}},
    {"start_seconds": True},
])
def test_public_model_refuses_ambiguous_or_non_audio_inputs(updates):
    with pytest.raises(ValueError):
        TranscriptRequest(file_path="/s.wav", expected_source_sha256=SHA, output_directory="/absent", **updates)
