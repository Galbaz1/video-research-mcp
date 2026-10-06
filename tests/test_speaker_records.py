"""Pure speaker record admission, anonymous turns, relabel provenance, RTTM and sample offsets."""

import io
import json
import struct
import wave

import pytest

from video_research_mcp import speaker_records as records
from video_research_mcp.models.speakers import RelabelRequest

DIGEST = "a" * 64


def _submitted(operation="diarize", groups=None, samples=160000):
    runtime = {"sherpa_onnx_version": "1.13.8", "embedding_model": {"dimension": 4}}
    wav = {"path": "/x/diarization-input.wav", "sha256": "b" * 64, "sample_count": samples}
    config = records.diarize_config(None) if operation == "diarize" else {}
    return records.worker_payload(operation, runtime, DIGEST, wav, config, groups)


def _receipt(submitted, **changes):
    receipt = {"descriptor_sha256": DIGEST, "wav_sha256": "b" * 64, "sample_count": submitted["wav"]["sample_count"],
               "config": submitted["config"], "sherpa_onnx_version": "1.13.8", "embedding_dimension": 4,
               "speaker_identity_verified": False}
    return {**receipt, **changes}


def _turn(native, start, end, similarity=0.9, reason=None):
    return {"native_cluster_id": native, "start_seconds": start, "end_seconds": end,
            "similarity": similarity, "similarity_unavailable_reason": reason}


TWO_SPEAKERS = [_turn(7, 0.0, 2.5), _turn(3, 2.6, 5.0, 0.8), _turn(7, 5.1, 7.0, None, "singleton_cluster"),
                _turn(3, 7.2, 9.5, 0.7)]


def _answer(submitted, turns=TWO_SPEAKERS, **receipt_changes):
    return json.dumps({"protocol": records.PROTOCOL, "operation": "diarize",
                       "receipt": _receipt(submitted, **receipt_changes), "turns": turns}).encode()


def test_two_cluster_answer_yields_anonymous_timestamped_turns_with_confidence():
    """GIVEN native ids {7, 3} WHEN admitted THEN SPEAKER_NN by first appearance on both clocks, no names."""
    submitted = _submitted()
    turns = records.anonymous_turns(records.admit_turns(_answer(submitted), submitted), origin=75.0)
    assert [t["cluster"] for t in turns] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00", "SPEAKER_01"]
    assert [t["native_cluster_id"] for t in turns] == [7, 3, 7, 3]
    assert turns[1]["wav_start_seconds"] == 2.6 and turns[1]["start_seconds"] == pytest.approx(77.6)
    assert turns[0]["cluster_similarity"] == 0.9
    assert turns[2]["cluster_similarity"] is None and turns[2]["confidence_unavailable_reason"] == "singleton_cluster"
    assert not any({"name", "label", "embedding"} & set(t) for t in turns)
    summary = records.cards(turns)
    assert [(c["cluster"], c["turn_count"]) for c in summary] == [("SPEAKER_00", 2), ("SPEAKER_01", 2)]
    assert summary[1]["mean_cluster_similarity"] == pytest.approx(0.75)
    assert summary[0]["speaking_seconds"] == pytest.approx(4.4)


@pytest.mark.parametrize("mutate", [
    lambda s: _answer(s, descriptor_sha256="c" * 64),
    lambda s: _answer(s, wav_sha256="c" * 64),
    lambda s: _answer(s, embedding_dimension=8),
    lambda s: _answer(s, config={**s["config"], "threshold": 0.4}),
    lambda s: _answer(s, speaker_identity_verified=True),
    lambda s: _answer(s, sample_count=float(s["wav"]["sample_count"])),
    lambda s: _answer(s, turns=[_turn(1, 3.0, 4.0), _turn(1, 1.0, 2.0)]),
    lambda s: _answer(s, turns=[_turn(1, 9.0, 10.5)]),
    lambda s: _answer(s, turns=[_turn(1, 2.0, 2.0)]),
    lambda s: _answer(s, turns=[_turn(-1, 0.0, 1.0)]),
    lambda s: _answer(s, turns=[_turn(1, 0.0, 1.0, 1.5)]),
    lambda s: _answer(s, turns=[_turn(1, 0.0, 1.0, None)]),
    lambda s: _answer(s, turns=[_turn(1, 0.0, 1.0, 0.5, "singleton_cluster")]),
    lambda s: _answer(s, turns=[{**_turn(1, 0.0, 1.0), "name": "Alice"}]),
    lambda s: _answer(s).replace(b'"speaker_identity_verified": false', b'"speaker_identity_verified": NaN'),
    lambda s: _answer(s)[:-1] + b', "turns": []}',
    lambda s: json.dumps({"protocol": "other", "operation": "diarize", "receipt": {}, "turns": []}).encode(),
    lambda s: _answer(s, turns=[_turn(1, i / 100, i / 100 + 0.005) for i in range(1025)]),
    lambda s: b" " * (records.MAX_DIARIZE_ANSWER + 1),
])
def test_diarize_admission_refuses_unbound_or_out_of_contract_answers(mutate):
    """GIVEN an answer differing from the submission or contract WHEN admitted THEN it is refused."""
    submitted = _submitted()
    with pytest.raises(ValueError):
        records.admit_turns(mutate(submitted), submitted)


def test_centroid_admission_requires_exact_groups_dimension_and_finite_nonzero_vectors():
    """GIVEN embed answers WHEN admitted THEN only exact-group finite non-zero d-vectors pass."""
    submitted = _submitted("embed", {"SPEAKER_00": [[0, 16000]]})

    def answer(centroids):
        return json.dumps({"protocol": records.PROTOCOL, "operation": "embed", "receipt": _receipt(submitted),
                           "centroids": centroids}).encode()

    assert records.admit_centroids(answer({"SPEAKER_00": [1.0, 0.0, 0.0, 0.0]}), submitted)
    for bad in ({"SPEAKER_01": [1.0, 0, 0, 0]}, {"SPEAKER_00": [1.0, 0.0]}, {"SPEAKER_00": [0.0] * 4},
                {"SPEAKER_00": [1.0, "x", 0, 0]}, {"SPEAKER_00": [1e308, 1e308, 1e308, 1e308]}):
        with pytest.raises(ValueError):
            records.admit_centroids(answer(bad), submitted)


def test_speaker_count_hint_only_replaces_threshold_clustering():
    """GIVEN no hint or a hint WHEN configured THEN R11 settings stay except num_clusters."""
    assert records.diarize_config(None) == records.QUALIFIED_CONFIG
    assert records.diarize_config(2) == {**records.QUALIFIED_CONFIG, "num_clusters": 2}


def _record(turns, origin=10.0, samples=160000):
    anonymous = records.anonymous_turns(turns, origin)
    return {"schema": "speaker-diarization/v1", "source": {"path": "/a.wav", "sha256": DIGEST},
            "selection": {"start_seconds": origin, "end_seconds": origin + samples / 16000},
            "audio": {"path": "diarization-input.wav", "sha256": "b" * 64, "sample_count": samples},
            "runtime": {"route": "optional_subprocess_worker"}, "turns": anonymous,
            "cards": records.cards(anonymous), "confidence_kind": records.CONFIDENCE_KIND}


def _relabel(**fields):
    return RelabelRequest(action="relabel", diarization_record_path="/r.json", expected_record_sha256=DIGEST,
                          output_directory="/out", **fields)


def test_relabel_record_copies_parent_turns_verbatim_and_adds_only_labels():
    """GIVEN a parent WHEN explicitly relabelled THEN turns equal parent turns plus label; provenance kept."""
    parent = _record(TWO_SPEAKERS)
    reference = {"path": "/r.json", "sha256": DIGEST, "schema": "speaker-diarization/v1"}
    request = _relabel(assignments={"SPEAKER_01": "Alice"}, roles={"Alice": "peer"}, note="checked by ear")
    record = records.relabel_record(parent, reference, request, {}, None)
    assert record["parent"] == reference and record["source"] == parent["source"]
    assert [{k: v for k, v in t.items() if k != "label"} for t in record["turns"]] == parent["turns"]
    assert [t["label"] for t in record["turns"]] == ["SPEAKER_00", "Alice", "SPEAKER_00", "Alice"]
    assert record["labels"] == {"SPEAKER_01": {"name": "Alice", "origin": "user_assignment", "role": "peer"}}
    assert (record["registry_written"], record["voiceprints_persisted"], record["suggestions_applied"]) == (False, 0, False)
    with pytest.raises(ValueError, match="Unknown cluster"):
        records.relabel_record(parent, reference, _relabel(assignments={"SPEAKER_05": "Bob"}), {}, None)


def test_rttm_lines_are_exact_on_the_source_clock():
    """GIVEN anonymous and relabelled turns WHEN exported THEN RTTM lines are exact."""
    parent = _record(TWO_SPEAKERS[:2], origin=75.0)
    assert records.rttm(parent["turns"], DIGEST, "cluster").decode().splitlines() == [
        f"SPEAKER src-{'a' * 12} 1 75.000 2.500 <NA> <NA> SPEAKER_00 <NA> <NA>",
        f"SPEAKER src-{'a' * 12} 1 77.600 2.400 <NA> <NA> SPEAKER_01 <NA> <NA>"]
    labelled = [{**parent["turns"][0], "label": "Alice"}]
    assert records.rttm(labelled, DIGEST, "label").decode().split()[7] == "Alice"


def test_samples_use_longest_turns_exact_offsets_and_never_cross_their_turn():
    """GIVEN per-cluster limits WHEN selected THEN offsets are exact sample indices inside each turn."""
    record = _record(TWO_SPEAKERS)
    clips = records.select_samples(record, [], per_cluster=1, max_seconds=2)
    assert [(c["cluster"], c["turn_index"], c["start_sample"], c["end_sample"]) for c in clips] == [
        ("SPEAKER_00", 0, 0, 32000), ("SPEAKER_01", 1, 41600, 73600)]
    assert clips[1]["start_seconds"] == pytest.approx(12.6) and clips[1]["end_seconds"] == pytest.approx(14.6)
    both = records.select_samples(record, ["SPEAKER_01"], per_cluster=3, max_seconds=15)
    assert [(c["start_sample"], c["end_sample"]) for c in both] == [(41600, 80000), (115200, 152000)]
    with pytest.raises(ValueError, match="Unknown cluster"):
        records.select_samples(record, ["SPEAKER_09"], 1, 8)


def test_samples_exceeding_120_seconds_are_refused_not_truncated():
    """GIVEN many long turns WHEN the total would exceed 120 s THEN selection is refused."""
    turns = [_turn(i, i * 15.0, i * 15.0 + 15.0) for i in range(9)]
    record = _record(turns, samples=9 * 15 * 16000)
    with pytest.raises(ValueError, match="refused, not truncated"):
        records.select_samples(record, [], per_cluster=1, max_seconds=15)


def test_wav_round_trip_preserves_pcm_and_rejects_other_formats():
    """GIVEN stdlib PCM WHEN wrapped and parsed THEN the samples are identical; stereo is refused."""
    pcm = struct.pack("<4h", 0, 1000, -1000, 32767)
    assert records.wav_pcm(records.wav_bytes(pcm)) == (pcm, 4)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)
    with pytest.raises(ValueError, match="16 kHz mono"):
        records.wav_pcm(buffer.getvalue())
