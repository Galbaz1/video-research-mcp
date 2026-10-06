"""Pure admission and record construction for anonymous turns, relabels, RTTM, samples and PCM.

Records carry timestamps, anonymous cluster labels and similarity scalars only:
voiceprint vectors never enter diarization, relabel or sample records.
"""

import io
import math
import re
import wave

from .speaker_registry import check_vector
from .transcript_captions import strict_json

PROTOCOL = "speaker_worker_v1"
RATE = 16000
MAX_DIARIZE_ANSWER = 128 * 1024
MAX_EMBED_ANSWER = 1024 * 1024
MAX_TURNS = 1024
MAX_SAMPLE_SECONDS = 120
QUALIFIED_CONFIG = {"num_clusters": -1, "threshold": 0.5, "window_shift_ratio": 0.1,
                    "min_duration_on": 0.3, "min_duration_off": 0.5}
CONFIDENCE_KIND = "cosine_turn_embedding_to_own_cluster_centroid"
CONFIDENCE_MEANING = ("Cosine between the turn embedding and its anonymous cluster centroid (turn included); "
                      "not a probability, accuracy estimate or identity; never thresholded")
_TURN_KEYS = {"native_cluster_id", "start_seconds", "end_seconds", "similarity", "similarity_unavailable_reason"}
_UNAVAILABLE = {"singleton_cluster", "embedding_failed"}


def diarize_config(num_speakers: int | None) -> dict:
    """R11 sherpa settings; an explicit speaker-count hint replaces threshold clustering only."""
    return {**QUALIFIED_CONFIG, "num_clusters": num_speakers or -1}


def worker_payload(operation: str, runtime: dict, descriptor_sha256: str, wav: dict, config: dict,
                   groups: dict | None = None) -> dict:
    """One speaker_worker_v1 request; groups map keys to [start_sample, end_sample] intervals."""
    payload = {"protocol": PROTOCOL, "operation": operation, "descriptor_sha256": descriptor_sha256,
               "runtime": runtime, "wav": wav, "config": config}
    return payload if groups is None else {**payload, "groups": groups}


def _receipt(value, submitted: dict, answer_key: str) -> None:
    if (not isinstance(value, dict) or set(value) != {"protocol", "operation", "receipt", answer_key}
            or value["protocol"] != PROTOCOL or value["operation"] != submitted["operation"]):
        raise ValueError("Speaker worker returned an unsupported envelope")
    expected = {"descriptor_sha256": submitted["descriptor_sha256"], "wav_sha256": submitted["wav"]["sha256"],
                "sample_count": submitted["wav"]["sample_count"], "config": submitted["config"],
                "sherpa_onnx_version": submitted["runtime"]["sherpa_onnx_version"],
                "embedding_dimension": submitted["runtime"]["embedding_model"]["dimension"],
                "speaker_identity_verified": False}
    receipt = value["receipt"]
    if (receipt != expected or receipt["speaker_identity_verified"] is not False
            or type(receipt["sample_count"]) is not int or type(receipt["embedding_dimension"]) is not int):
        raise ValueError("Speaker worker receipt differs from the submitted descriptor, WAV, config or dimension")


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _admit_turn(turn, previous: float, duration: float) -> None:
    if not isinstance(turn, dict) or set(turn) != _TURN_KEYS:
        raise ValueError("Speaker worker turn keys are not exact")
    start, end, similarity = turn["start_seconds"], turn["end_seconds"], turn["similarity"]
    if type(turn["native_cluster_id"]) is not int or turn["native_cluster_id"] < 0:
        raise ValueError("Speaker worker cluster ids must be non-negative integers")
    if not (_finite(start) and _finite(end)) or not previous <= start < end <= duration + 1 / RATE:
        raise ValueError("Speaker worker turns must be finite, ordered and inside the submitted WAV")
    if similarity is None:
        if turn["similarity_unavailable_reason"] not in _UNAVAILABLE:
            raise ValueError("Unavailable turn similarity requires a declared reason")
    elif not _finite(similarity) or not -1 <= similarity <= 1 or turn["similarity_unavailable_reason"] is not None:
        raise ValueError("Turn similarity must be a finite cosine in [-1, 1]")


def admit_turns(data: bytes, submitted: dict) -> list[dict]:
    """Validate a diarize answer against the exact submission without asserting accuracy."""
    if len(data) > MAX_DIARIZE_ANSWER:
        raise ValueError("Speaker worker diarize answer exceeds 128 KiB")
    value = strict_json(data)
    _receipt(value, submitted, "turns")
    turns, previous = value["turns"], 0.0
    if not isinstance(turns, list) or len(turns) > MAX_TURNS:
        raise ValueError("Speaker worker turns must be a list of at most 1024 turns")
    for turn in turns:
        _admit_turn(turn, previous, submitted["wav"]["sample_count"] / RATE)
        previous = turn["start_seconds"]
    return turns


def admit_centroids(data: bytes, submitted: dict) -> dict[str, list]:
    """Validate an embed answer: one finite non-zero centroid of the declared dimension per group."""
    if len(data) > MAX_EMBED_ANSWER:
        raise ValueError("Speaker worker embed answer exceeds 1 MiB")
    value = strict_json(data)
    _receipt(value, submitted, "centroids")
    centroids = value["centroids"]
    if not isinstance(centroids, dict) or set(centroids) != set(submitted["groups"]):
        raise ValueError("Speaker worker centroids differ from the submitted groups")
    dimension = submitted["runtime"]["embedding_model"]["dimension"]
    return {key: check_vector(vector, dimension) for key, vector in centroids.items()}


def anonymous_turns(turns: list[dict], origin: float) -> list[dict]:
    """Map native ids to SPEAKER_NN by first appearance; keep both clocks and the native id."""
    labels: dict[int, str] = {}
    result = []
    for turn in turns:
        native = turn["native_cluster_id"]
        if native not in labels:
            labels[native] = f"SPEAKER_{len(labels):02d}"
        result.append({"cluster": labels[native], "native_cluster_id": native,
                       "wav_start_seconds": turn["start_seconds"], "wav_end_seconds": turn["end_seconds"],
                       "start_seconds": origin + turn["start_seconds"], "end_seconds": origin + turn["end_seconds"],
                       "cluster_similarity": turn["similarity"],
                       "confidence_unavailable_reason": turn["similarity_unavailable_reason"]})
    if len(labels) > 100:
        raise ValueError("Speaker worker returned more than 100 anonymous clusters")
    return result


def cards(turns: list[dict]) -> list[dict]:
    """Per-cluster speaker cards: turn count, speaking time, span and mean similarity."""
    summary: dict[str, dict] = {}
    for turn in turns:
        card = summary.setdefault(turn["cluster"], {
            "cluster": turn["cluster"], "native_cluster_id": turn["native_cluster_id"], "turn_count": 0,
            "speaking_seconds": 0.0, "first_start_seconds": turn["start_seconds"],
            "last_end_seconds": turn["end_seconds"], "similarities": []})
        card["turn_count"] += 1
        card["speaking_seconds"] += turn["end_seconds"] - turn["start_seconds"]
        card["last_end_seconds"] = max(card["last_end_seconds"], turn["end_seconds"])
        if turn["cluster_similarity"] is not None:
            card["similarities"].append(turn["cluster_similarity"])
    for card in summary.values():
        values = card.pop("similarities")
        card["mean_cluster_similarity"] = math.fsum(values) / len(values) if values else None
    return list(summary.values())


def _record_runtime(runtime: dict) -> None:
    expected = {"route", "descriptor_sha256", "sherpa_onnx_version", "provider", "num_threads",
                "segmentation_model", "embedding_model"}
    if (not isinstance(runtime, dict) or set(runtime) != expected
            or runtime["route"] != "optional_subprocess_worker" or runtime["provider"] != "cpu"
            or type(runtime["num_threads"]) is not int or not 1 <= runtime["num_threads"] <= 8
            or not re.fullmatch(r"[a-f0-9]{64}", runtime["descriptor_sha256"])
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", runtime["sherpa_onnx_version"])):
        raise ValueError("Diarization runtime metadata differs from its producer contract")
    for key in ("segmentation_model", "embedding_model"):
        model = runtime[key]
        keys = {"basename", "sha256", "bytes", "license"} | ({"dimension"} if key == "embedding_model" else set())
        if (not isinstance(model, dict) or set(model) != keys or not isinstance(model["basename"], str)
                or not model["basename"] or not re.fullmatch(r"[a-f0-9]{64}", model["sha256"])
                or type(model["bytes"]) is not int or model["bytes"] < 1
                or not isinstance(model["license"], str) or not 1 <= len(model["license"]) <= 512):
            raise ValueError("Diarization model metadata differs from its producer contract")
    dimension = runtime["embedding_model"]["dimension"]
    if type(dimension) is not int or not 1 <= dimension <= 4096:
        raise ValueError("Diarization embedding dimension differs from its producer contract")


def _record_metadata(record: dict) -> None:
    keys = {"schema", "source", "selection", "audio", "runtime", "config", "num_speakers_hint", "turns", "cards",
            "observed_cluster_count", "confidence_kind", "confidence_interpretation", "names_assigned",
            "registry_read", "embeddings_persisted", "speaker_identity_verified"}
    if set(record) != keys or record["schema"] != "speaker-diarization/v1":
        raise ValueError("Diarization record keys differ from its producer contract")
    if (any(record[k] is not False for k in ("names_assigned", "registry_read", "embeddings_persisted",
                                           "speaker_identity_verified"))
            or record["confidence_kind"] != CONFIDENCE_KIND or record["confidence_interpretation"] != CONFIDENCE_MEANING):
        raise ValueError("Diarization record must retain its anonymous similarity contract")
    source, audio = record["source"], record["audio"]
    if (not isinstance(source, dict) or set(source) != {"path", "sha256"}
            or not isinstance(source["path"], str) or not source["path"].startswith("/")
            or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"])):
        raise ValueError("Diarization source metadata is invalid")
    if (not isinstance(audio, dict) or set(audio) != {"path", "sha256", "bytes", "sample_count", "sample_rate", "channels"}
            or not isinstance(audio["path"], str) or not audio["path"]
            or not re.fullmatch(r"[a-f0-9]{64}", audio["sha256"])
            or type(audio["sample_count"]) is not int or not 1 <= audio["sample_count"] <= 120 * RATE
            or type(audio["bytes"]) is not int or audio["bytes"] < 1
            or type(audio["sample_rate"]) is not int or audio["sample_rate"] != RATE
            or type(audio["channels"]) is not int or audio["channels"] != 1):
        raise ValueError("Diarization retained audio metadata is invalid")
    hint = record["num_speakers_hint"]
    if hint is not None and (type(hint) is not int or not 1 <= hint <= 16):
        raise ValueError("Diarization speaker-count hint is invalid")
    if (record["config"] != diarize_config(hint) or type(record["config"]["num_clusters"]) is not int):
        raise ValueError("Diarization config differs from its producer contract")
    _record_runtime(record["runtime"])


def _record_clock(record: dict) -> float:
    selection = record["selection"]
    if (not isinstance(selection, dict) or set(selection) != {"start_seconds", "end_seconds", "requested",
                                                           "source_audio_clock", "clock_relationship"}):
        raise ValueError("Diarization selection keys differ from its producer contract")
    start, end = selection["start_seconds"], selection["end_seconds"]
    if (not (_finite(start) and _finite(end)) or not 0 <= start < end or end - start > 120 + 1 / RATE
            or abs(end - start - record["audio"]["sample_count"] / RATE) > 1 / RATE):
        raise ValueError("Diarization selection clock differs from its retained sample population")
    requested = selection["requested"]
    if (not isinstance(requested, dict) or set(requested) != {"start_seconds", "end_seconds"}
            or not all(_finite(requested[k]) and abs(requested[k] - selection[k]) <= 1 / RATE
                       for k in ("start_seconds", "end_seconds"))
            or not 0 <= requested["start_seconds"] < requested["end_seconds"]
            or requested["end_seconds"] - requested["start_seconds"] > 120):
        raise ValueError("Diarization requested and retained selection clocks disagree")
    for key in ("source_audio_clock", "clock_relationship"):
        if not isinstance(selection[key], dict):
            raise ValueError("Diarization source clock provenance must be an object")
    _record_source_clock(selection, record["audio"])
    return start


def _record_source_clock(selection: dict, audio: dict) -> None:
    clock, relation = selection["source_audio_clock"], selection["clock_relationship"]
    if (type(clock["sample_count"]) is not int or clock["sample_count"] != audio["sample_count"]
            or type(clock["sample_rate"]) is not int or clock["sample_rate"] != RATE
            or not _finite(clock["duration_seconds"]) or clock["duration_seconds"] != audio["sample_count"] / RATE
            or any(not _finite(clock[k]) or clock[k] != selection[s]
                   for k, s in (("first_seconds", "start_seconds"), ("end_seconds", "end_seconds")))
            or any(type(v) in (int, float) and not _finite(v) for v in clock.values())):
        raise ValueError("Diarization measured source clock differs from its retained PCM")
    if (set(relation) != {"output_origin_seconds", "source_origin_seconds", "tolerance_seconds", "sample_count_verified"}
            or relation["sample_count_verified"] is not True
            or any(not _finite(relation[k]) or relation[k] != expected for k, expected in (
                ("output_origin_seconds", 0), ("source_origin_seconds", selection["start_seconds"]),
                ("tolerance_seconds", 1 / RATE)))):
        raise ValueError("Diarization clock relationship differs from its producer contract")


def admit_record(record: dict) -> None:
    """Admit the produced diarization contract before any relabel, sample or cluster enrollment."""
    try:
        _record_metadata(record)
        origin = _record_clock(record)
        turns, native, previous = record["turns"], [], 0.0
        if not isinstance(turns, list) or len(turns) > MAX_TURNS:
            raise ValueError("Diarization turns must be a list of at most 1024 turns")
        for turn in turns:
            raw = {"native_cluster_id": turn["native_cluster_id"], "start_seconds": turn["wav_start_seconds"],
                   "end_seconds": turn["wav_end_seconds"], "similarity": turn["cluster_similarity"],
                   "similarity_unavailable_reason": turn["confidence_unavailable_reason"]}
            _admit_turn(raw, previous, record["audio"]["sample_count"] / RATE)
            if (not (_finite(turn["start_seconds"]) and _finite(turn["end_seconds"]))
                    or not 0 <= round(raw["start_seconds"] * RATE) < round(raw["end_seconds"] * RATE) <= record["audio"]["sample_count"]):
                raise ValueError("Diarization turn clocks must select non-empty retained PCM intervals")
            native.append(raw)
            previous = raw["start_seconds"]
        if turns != anonymous_turns(native, origin):
            raise ValueError("Diarization anonymous clusters or exact turn clocks disagree with the producer")
        summary = record["cards"]
        if (not isinstance(summary, list) or summary != cards(turns)
                or type(record["observed_cluster_count"]) is not int or record["observed_cluster_count"] != len(summary)):
            raise ValueError("Diarization cards or cluster count disagree with the admitted turns")
        for card in summary:
            if (type(card["native_cluster_id"]) is not int or type(card["turn_count"]) is not int
                    or any(not _finite(card[k]) for k in ("speaking_seconds", "first_start_seconds", "last_end_seconds"))
                    or (card["mean_cluster_similarity"] is not None and not _finite(card["mean_cluster_similarity"]))):
                raise ValueError("Diarization card values must retain finite producer types")
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Diarization record is malformed") from error


def relabel_record(parent: dict, parent_ref: dict, request, suggestions: dict, match: dict | None) -> dict:
    """New record: parent turns verbatim plus a label; the parent and registry stay untouched."""
    known = {card["cluster"] for card in parent["cards"]}
    if set(request.assignments) - known:
        raise ValueError(f"Unknown cluster(s): {', '.join(sorted(set(request.assignments) - known))}")
    labels = {cluster: {"name": name, "origin": "user_assignment", "role": request.roles.get(name)}
              for cluster, name in sorted(request.assignments.items())}
    return {"schema": "speaker-relabel/v1", "parent": parent_ref, "source": parent["source"],
            "selection": parent["selection"], "audio": parent["audio"], "runtime": parent["runtime"],
            "labels": labels, "roles": dict(request.roles), "note": request.note,
            "turns": [{**turn, "label": request.assignments.get(turn["cluster"], turn["cluster"])}
                      for turn in parent["turns"]],
            "cards": parent["cards"], "suggestions": suggestions, "suggestions_applied": False,
            "registry_match": match, "registry_written": False, "voiceprints_persisted": 0,
            "confidence_kind": parent["confidence_kind"], "speaker_identity_verified": False}


def rttm(turns: list[dict], source_sha256: str, key: str) -> bytes:
    """NIST RTTM lines on the source clock; JSON stays canonical at full precision."""
    return "".join(
        f"SPEAKER src-{source_sha256[:12]} 1 {turn['start_seconds']:.3f} "
        f"{turn['end_seconds'] - turn['start_seconds']:.3f} <NA> <NA> {turn[key]} <NA> <NA>\n"
        for turn in turns).encode()


def cluster_intervals(record: dict, clusters: list[str] | None = None) -> dict[str, list[list[int]]]:
    """Exact [start_sample, end_sample] intervals of every turn per selected cluster."""
    known = [card["cluster"] for card in record["cards"]]
    chosen = clusters or known
    if set(chosen) - set(known):
        raise ValueError(f"Unknown cluster(s): {', '.join(sorted(set(chosen) - set(known)))}")
    return {cluster: [[round(t["wav_start_seconds"] * RATE), round(t["wav_end_seconds"] * RATE)]
                      for t in record["turns"] if t["cluster"] == cluster] for cluster in chosen}


def select_samples(record: dict, clusters: list[str], per_cluster: int, max_seconds: float) -> list[dict]:
    """Longest turns first; each clip stays inside its turn; >120 s total is refused, not truncated."""
    cluster_intervals(record, clusters)
    origin, limit = record["selection"]["start_seconds"], record["audio"]["sample_count"]
    clips = []
    for cluster in clusters or [card["cluster"] for card in record["cards"]]:
        turns = [(index, turn) for index, turn in enumerate(record["turns"]) if turn["cluster"] == cluster]
        turns.sort(key=lambda item: (item[1]["wav_start_seconds"] - item[1]["wav_end_seconds"], item[0]))
        for number, (index, turn) in enumerate(turns[:per_cluster], 1):
            start = round(turn["wav_start_seconds"] * RATE)
            end = min(round(turn["wav_end_seconds"] * RATE), start + round(max_seconds * RATE), limit)
            if end <= start:
                raise ValueError(f"Turn {index} of {cluster} has no exportable samples")
            clips.append({"cluster": cluster, "turn_index": index, "start_sample": start, "end_sample": end,
                          "start_seconds": origin + start / RATE, "end_seconds": origin + end / RATE,
                          "path": f"{cluster}-{number}.wav"})
    if sum(clip["end_sample"] - clip["start_sample"] for clip in clips) > MAX_SAMPLE_SECONDS * RATE:
        raise ValueError("Requested samples exceed 120 seconds in total; refused, not truncated")
    return clips


def wav_pcm(data: bytes) -> tuple[bytes, int]:
    """Return the PCM16 body and sample count of an uncompressed 16 kHz mono WAV."""
    with wave.open(io.BytesIO(data), "rb") as reader:
        shape = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype())
        if shape != (1, 2, RATE, "NONE"):
            raise ValueError("Speaker audio must be 16 kHz mono PCM16 WAV")
        count = reader.getnframes()
        pcm = reader.readframes(count)
    if not count or len(pcm) != 2 * count:
        raise ValueError("Speaker WAV sample population is empty or incomplete")
    return pcm, count


def wav_bytes(pcm: bytes) -> bytes:
    """Wrap PCM16 samples in a canonical 16 kHz mono WAV header."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(pcm)
    return buffer.getvalue()
