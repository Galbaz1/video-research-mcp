"""Actual selected clocks, complete word populations and exact-only duplicate policy."""

import pytest

from video_research_mcp.models.transcript import ASRAnswer, TranscriptCue, TranscriptSegment
from video_research_mcp.transcript_timing import merge_exact, project_answer, select_captions, validate_segments


def answer(**updates):
    cue = {"start_seconds": .2, "end_seconds": .8, "text": "Hello", "speaker_id": None,
           "words": [{"text": "Hello", "start_seconds": .2, "end_seconds": .8}]}
    cue.update(updates)
    return ASRAnswer(outcome="transcript", segments=[cue])


def window(start=10):
    return {"index": 0, "start_seconds": 8, "end_seconds": 12,
            "audio": {"selected_window": {"start_seconds": start, "end_seconds": start + 1}}}


def test_nonzero_requested_offset_cannot_replace_actual_wav_origin():
    records = project_answer(answer(), window(), "a" * 64)
    assert records[0].start_seconds == 10.2 and records[0].end_seconds == 10.8
    assert records[0].words[0].start_seconds == 10.2
    assert records[0].speaker_id is None


def test_record_identity_commits_actual_source_interval_not_local_window_number():
    first = project_answer(answer(), window(10), "a" * 64)
    shifted = project_answer(answer(), window(20), "a" * 64)
    assert first[0].id != shifted[0].id
    assert first[0].id != project_answer(answer(), window(10), "b" * 64)[0].id


def test_repeated_phrase_at_different_times_and_overlap_are_retained():
    records, decisions = [], []
    first = project_answer(answer(), window(10), "a" * 64)
    repeated = project_answer(answer(), window(11), "a" * 64)
    overlap = project_answer(answer(speaker_id="inferred-2"), window(10), "a" * 64)
    for index, population in enumerate([first, repeated, overlap, first]):
        merge_exact(records, population, index, decisions)
    assert len(records) == 3 and len(decisions) == 1
    assert decisions[0]["window_index"] == 3


@pytest.mark.parametrize("updates", [
    {"start_seconds": -.1}, {"start_seconds": float("nan")}, {"end_seconds": float("inf")},
    {"start_seconds": .9, "end_seconds": .8},
    {"words": [{"text": "Wrong", "start_seconds": .2, "end_seconds": .8}]},
    {"words": [{"text": "Hello", "start_seconds": .1, "end_seconds": .8}]},
    {"words": [{"text": "Hello", "start_seconds": .2, "end_seconds": .9}]},
])
def test_malformed_word_and_cue_values_refuse(updates):
    with pytest.raises(ValueError):
        answer(**updates)


def test_actual_wav_end_is_checked_even_when_requested_window_is_longer():
    with pytest.raises(ValueError, match="actual decoded"):
        project_answer(answer(end_seconds=1.1, words=[]), window(), "a" * 64)


@pytest.mark.parametrize("outcome,segments,reasons", [
    ("empty", [TranscriptCue(start_seconds=0, end_seconds=1, text="Hi")], []),
    ("transcript", [], []), ("abstained", [], []),
])
def test_empty_abstained_and_malformed_populations_are_distinct(outcome, segments, reasons):
    with pytest.raises(ValueError):
        ASRAnswer(outcome=outcome, segments=segments, abstentions=reasons)


def test_valid_empty_and_explicit_abstention_remain_distinct():
    assert ASRAnswer(outcome="empty", segments=[]).outcome == "empty"
    assert ASRAnswer(outcome="abstained", segments=[], abstentions=["unintelligible"]).outcome == "abstained"


def test_source_assertions_can_cross_selection_without_text_clipping():
    cues = [TranscriptSegment(id="a", start_seconds=1, end_seconds=4, text="Full sentence"),
            TranscriptSegment(id="b", start_seconds=5, end_seconds=6, text="Other")]
    selected, population = select_captions(validate_segments(cues, 8), 2, 3)
    assert selected == [cues[0]] and selected[0].end_seconds == 4
    assert population["boundary_crossing_ids"] == ["a"] and population["omitted_outside_selection"] == 1


@pytest.mark.parametrize("population", [
    [{"id": "a", "start_seconds": 0, "end_seconds": 4, "text": "Hi"}],
    [{"id": "a", "start_seconds": 1, "end_seconds": 2, "text": "Hi"},
     {"id": "b", "start_seconds": 0, "end_seconds": 1, "text": "Earlier"}],
    [{"id": "a", "start_seconds": 0, "end_seconds": 1, "text": "Hi"},
     {"id": "a", "start_seconds": 1, "end_seconds": 2, "text": "Repeated"}],
])
def test_entire_caption_population_order_extent_and_id_gate(population):
    with pytest.raises(ValueError):
        validate_segments(population, 3)
