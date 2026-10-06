"""Tool-level speaker workflows with patched native boundaries and real record/registry/WAV I/O."""

import ast
import asyncio
import hashlib
import json
import stat
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_research_mcp import speakers
from video_research_mcp.speaker_records import PROTOCOL, wav_bytes, wav_pcm
from video_research_mcp.tools import audio_speakers as tool

RATE = 16000
DIMENSION = 4
SCRIPT = [(7, 0.0, 2.5, 0.91), (3, 2.6, 5.0, 0.82), (7, 5.1, 7.0, 0.88), (3, 7.2, 9.5, None)]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _signal(seconds, offset=0):
    count = round(seconds * RATE)
    return struct.pack(f"<{count}h", *(((i + offset) * 37) % 2000 - 1000 for i in range(count)))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """GIVEN a pinned fake runtime, a source file and patched export/worker boundaries."""
    models = {}
    for key, name, data in (("segmentation_model", "model.onnx", b"seg"), ("embedding_model", "titanet.onnx", b"emb")):
        path = tmp_path / name
        path.write_bytes(data * 100)
        models[key] = {"path": str(path), "sha256": _sha(path), "bytes": 300, "license": "Root-reviewed notice"}
    models["embedding_model"]["dimension"] = DIMENSION
    (tmp_path / "python").write_bytes(b"")
    (tmp_path / "site-packages").mkdir()
    descriptor = tmp_path / "runtime.json"
    descriptor.write_text(json.dumps({"format": "speaker-runtime/v1", "python": str(tmp_path / "python"),
        "site_packages": str(tmp_path / "site-packages"), "sherpa_onnx_version": "1.13.8", "provider": "cpu",
        "num_threads": 1, **models}))
    source = tmp_path / "meeting.wav"
    source.write_bytes(wav_bytes(_signal(40)))
    calls = {"export": [], "worker": []}

    async def export(file_path, sha256, start, end):
        assert sha256 == _sha(file_path)
        calls["export"].append((start, end))
        clock = {"requested_window": {"start_seconds": start, "end_seconds": end},
                 "selected_window": {"start_seconds": start, "end_seconds": end},
                 "source_audio_clock": {"sample_rate": RATE, "sample_count": round((end - start) * RATE),
                                        "duration_seconds": end - start, "first_seconds": start, "end_seconds": end},
                 "clock_relationship": {"output_origin_seconds": 0, "source_origin_seconds": start,
                                        "tolerance_seconds": 1 / RATE, "sample_count_verified": True}}
        return wav_bytes(_signal(end - start, round(start * RATE))), clock

    async def worker(runtime, payload):
        calls["worker"].append(payload)
        assert payload["protocol"] == PROTOCOL and _sha(payload["wav"]["path"]) == payload["wav"]["sha256"]
        receipt = {"descriptor_sha256": payload["descriptor_sha256"], "wav_sha256": payload["wav"]["sha256"],
                   "sample_count": payload["wav"]["sample_count"], "config": payload["config"],
                   "sherpa_onnx_version": "1.13.8", "embedding_dimension": DIMENSION, "speaker_identity_verified": False}
        if payload["operation"] == "diarize":
            answer = {"turns": [{"native_cluster_id": n, "start_seconds": s, "end_seconds": e, "similarity": c,
                                 "similarity_unavailable_reason": None if c is not None else "embedding_failed"}
                                for n, s, e, c in SCRIPT]}
        else:
            vectors = {"SPEAKER_00": [1.0, 0.0, 0.0, 0.0], "SPEAKER_01": [0.0, 1.0, 0.0, 0.0]}
            answer = {"centroids": {key: vectors.get(key, [0.5, 0.5, 0.5, 0.5]) for key in payload["groups"]}}
        return json.dumps({"protocol": PROTOCOL, "operation": payload["operation"], "receipt": receipt, **answer}).encode()

    monkeypatch.setattr(speakers, "_export_wav", export)
    monkeypatch.setattr(speakers, "_run_worker", worker)
    runtime = {"runtime_descriptor_path": str(descriptor), "expected_runtime_descriptor_sha256": _sha(descriptor)}
    return {"tmp": tmp_path, "runtime": runtime, "source": source, "calls": calls, "models": models}


def _tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


async def _diarize(env, name, start=10.0, end=20.0, **fields):
    request = {"action": "diarize", "file_path": str(env["source"]), "expected_source_sha256": _sha(env["source"]),
               "output_directory": str(env["tmp"] / name), "start_seconds": start, "end_seconds": end,
               "dry_run": False, **env["runtime"], **fields}
    return await tool.audio_speakers(request=request)


def _record_ref(result, name="diarization.json"):
    path = Path(result["output_directory"]) / name
    return {"diarization_record_path": str(path), "expected_record_sha256": _sha(path)}


def _no_vectors(root):
    """No output file carries an embedding key or a vector of the embedding dimension."""
    for path in root.rglob("*.json"):
        def walk(value):
            if isinstance(value, dict):
                assert "embedding" not in value and "centroids" not in value
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                assert not (len(value) == DIMENSION and all(isinstance(v, float) for v in value))
                for item in value:
                    walk(item)
        walk(json.loads(path.read_bytes()))


async def test_diarize_dry_run_checks_pins_and_writes_nothing(env):
    """GIVEN dry_run WHEN diarize is planned THEN hashes are checked and no worker or output exists."""
    result = await _diarize(env, "out", dry_run=True, num_speakers=2)
    assert result["status"] == "planned" and result["record"]["worker"] == "not started"
    assert result["record"]["config"]["num_clusters"] == 2
    assert not (env["tmp"] / "out").exists() and env["calls"] == {"export": [], "worker": []}


async def test_diarize_writes_anonymous_timestamped_turns_without_names_or_vectors(env):
    """GIVEN a two-cluster worker answer WHEN executed THEN SPEAKER_NN turns on the source clock persist."""
    result = await _diarize(env, "a")
    out = env["tmp"] / "a"
    assert result["status"] == "complete" and result["voiceprints_persisted"] == 0
    assert sorted(p.name for p in out.iterdir()) == ["diarization-input.wav", "diarization.json",
                                                     "diarization.rttm", "receipt.json"]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in out.iterdir())
    record = json.loads((out / "diarization.json").read_bytes())
    assert [(t["cluster"], t["native_cluster_id"]) for t in record["turns"]] == [
        ("SPEAKER_00", 7), ("SPEAKER_01", 3), ("SPEAKER_00", 7), ("SPEAKER_01", 3)]
    assert record["turns"][1]["start_seconds"] == pytest.approx(12.6)
    assert record["turns"][1]["cluster_similarity"] == 0.82
    assert record["turns"][3]["confidence_unavailable_reason"] == "embedding_failed"
    assert (record["names_assigned"], record["speaker_identity_verified"], record["registry_read"]) == (False, False, False)
    assert record["config"]["num_clusters"] == -1 and record["audio"]["sample_count"] == 160000
    assert record["audio"]["sha256"] == _sha(out / "diarization-input.wav")
    assert (out / "diarization.rttm").read_text().splitlines()[0].endswith("SPEAKER_00 <NA> <NA>")
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert {a["path"]: a["sha256"] for a in receipt["artifacts"]} == {
        name: _sha(out / name) for name in ("diarization-input.wav", "diarization.json", "diarization.rttm")}
    _no_vectors(out)
    assert [p["operation"] for p in env["calls"]["worker"]] == ["diarize"]
    assert not [p for p in env["tmp"].iterdir() if p.name.endswith(".pending")]


@pytest.mark.parametrize("change", ["existing_output", "source_sha", "descriptor_sha", "model_bytes", "too_long"])
async def test_diarize_refusals_are_structured_and_leave_no_output(env, change):
    """GIVEN a changed pin, existing output or over-long selection WHEN diarized THEN a ToolError results."""
    fields = {}
    if change == "existing_output":
        (env["tmp"] / "out").mkdir()
    elif change == "source_sha":
        fields["expected_source_sha256"] = "0" * 64
    elif change == "descriptor_sha":
        fields["expected_runtime_descriptor_sha256"] = "0" * 64
    elif change == "model_bytes":
        Path(env["models"]["embedding_model"]["path"]).write_bytes(b"x" * 300)
    else:
        fields["end_seconds"] = 140.5
    result = await _diarize(env, "out", **fields)
    assert set(result) >= {"error", "category", "hint", "retryable"}
    assert env["calls"]["worker"] == [] and not [p for p in env["tmp"].iterdir() if p.name.endswith(".pending")]


async def test_worker_failure_leaves_no_partial_output_directory(env, monkeypatch):
    """GIVEN a worker answer that fails admission WHEN diarized THEN no output or staging remains."""
    async def bad_worker(runtime, payload):
        return b'{"protocol": "speaker_worker_v1"}'

    monkeypatch.setattr(speakers, "_run_worker", bad_worker)
    result = await _diarize(env, "out")
    assert "error" in result and not (env["tmp"] / "out").exists()
    assert not [p for p in env["tmp"].iterdir() if p.name.startswith(".out.")]


async def test_relabel_persists_only_its_new_directory_and_preserves_provenance(env):
    """GIVEN recordings A and B WHEN A is relabelled THEN only a new directory appears; A, B, registry unchanged."""
    a, b = await _diarize(env, "a"), await _diarize(env, "b", 20.0, 30.0)
    registry_path = env["tmp"] / "speakers.json"
    before = _tree(env["tmp"])
    request = {"action": "relabel", **_record_ref(a), "output_directory": str(env["tmp"] / "a-relabel"),
               "assignments": {"SPEAKER_01": "Alice"}, "roles": {"Alice": "peer"}, "note": "by ear", "dry_run": False}
    result = await tool.audio_speakers(request=request)
    after = _tree(env["tmp"])
    assert {k: v for k, v in after.items() if not k.startswith("a-relabel/")} == before
    assert not registry_path.exists() and b["status"] == "complete"
    record = json.loads((env["tmp"] / "a-relabel" / "relabel.json").read_bytes())
    parent = json.loads((env["tmp"] / "a" / "diarization.json").read_bytes())
    assert record["parent"]["sha256"] == _record_ref(a)["expected_record_sha256"]
    assert [{k: v for k, v in t.items() if k != "label"} for t in record["turns"]] == parent["turns"]
    assert [t["label"] for t in record["turns"]] == ["SPEAKER_00", "Alice", "SPEAKER_00", "Alice"]
    assert record["labels"]["SPEAKER_01"] == {"name": "Alice", "origin": "user_assignment", "role": "peer"}
    assert (record["registry_written"], record["voiceprints_persisted"]) == (False, 0)
    assert (env["tmp"] / "a-relabel" / "relabel.rttm").read_text().split()[7] == "SPEAKER_00"
    assert result["record"]["note"] == "by ear"


@pytest.mark.parametrize("fields", [
    {"assignments": {"SPEAKER_09": "Alice"}},
    {"assignments": {"SPEAKER_00": "Alice Smith"}},
    {"assignments": {"SPEAKER_00": "Alice"}, "roles": {"Bob": "peer"}},
    {"assignments": {}},
    {"assignments": {"SPEAKER_00": "Alice"}, "expected_speakers": ["Alice"]},
    {"assignments": {"SPEAKER_00": "Alice"}, "expected_record_sha256": "0" * 64},
    {"assignments": {"SPEAKER_00": "Alice"}, "output_directory": "EXISTING"},
    {"assignments": {"SPEAKER_00": "Alice"}, "chained": True},
])
async def test_relabel_refusals_change_nothing(env, fields):
    """GIVEN an unknown cluster, bad name/role, missing scope, changed parent, existing output or chain
    WHEN relabelled THEN a ToolError results and no file changes."""
    a = await _diarize(env, "a")
    reference = _record_ref(a)
    if fields.pop("chained", False):
        await tool.audio_speakers(request={"action": "relabel", **reference, "dry_run": False,
            "output_directory": str(env["tmp"] / "r1"), "assignments": {"SPEAKER_00": "Alice"}})
        reference = _record_ref({"output_directory": str(env["tmp"] / "r1")}, "relabel.json")
    if fields.get("output_directory") == "EXISTING":
        fields["output_directory"] = str(env["tmp"] / "a")
    before = _tree(env["tmp"])
    request = {"action": "relabel", **reference, "output_directory": str(env["tmp"] / "new"), "dry_run": False, **fields}
    result = await tool.audio_speakers(request=request)
    assert set(result) >= {"error", "category", "hint"} and _tree(env["tmp"]) == before


def _registry(env, *entries):
    path = env["tmp"] / "speakers.json"
    model = {"basename": "titanet.onnx", "sha256": env["models"]["embedding_model"]["sha256"], "dimension": DIMENSION}
    other = {"basename": "other.onnx", "sha256": "f" * 64, "dimension": 2}
    speakers_ = [{"name": name, "model": other if name == "Zed" else model, "embedding": vector,
                  "added": "t", "provenance": {}, "consent": {"asserted_by_caller": True, "recorded_at": "t"}}
                 for name, vector in entries]
    path.write_text(json.dumps({"format": "speaker-registry/v1", "speakers": speakers_}))
    path.chmod(0o600)
    return path


async def test_match_registry_returns_unapplied_same_model_suggestions_and_saves_nothing(env):
    """GIVEN a registry WHEN relabel requests matching THEN suggestions are ranked, unapplied and unsaved."""
    a = await _diarize(env, "a")
    path = _registry(env, ("Alice", [0.0, 1.0, 0.0, 0.0]), ("Bob", [1.0, 0.1, 0.0, 0.0]), ("Zed", [1.0, 0.0]))
    original = path.read_bytes()
    request = {"action": "relabel", **_record_ref(a), "output_directory": str(env["tmp"] / "m"), "dry_run": False,
               "match_registry": True, "registry_path": str(path), **env["runtime"]}
    result = await tool.audio_speakers(request=request)
    record = result["record"]
    assert [s["name"] for s in record["suggestions"]["SPEAKER_01"]] == ["Alice", "Bob"]
    assert record["suggestions"]["SPEAKER_00"][0]["name"] == "Bob"
    assert all(s["applied"] is False for group in record["suggestions"].values() for s in group)
    assert record["labels"] == {} and [t["label"] for t in record["turns"]][:2] == ["SPEAKER_00", "SPEAKER_01"]
    assert record["registry_match"]["ignored_other_model_entries"] == 1
    assert path.read_bytes() == original and not (env["tmp"] / "speakers.json.lock").exists()
    _no_vectors(env["tmp"] / "m")
    groups = env["calls"]["worker"][-1]["groups"]
    assert groups["SPEAKER_01"] == [[41600, 80000], [115200, 152000]]
    restricted = await tool.audio_speakers(request={**request, "output_directory": str(env["tmp"] / "m2"),
                                                     "expected_speakers": ["Alice"]})
    assert [s["name"] for s in restricted["record"]["suggestions"]["SPEAKER_00"]] == ["Alice"]
    unknown = await tool.audio_speakers(request={**request, "output_directory": str(env["tmp"] / "m3"),
                                                  "expected_speakers": ["Zed"]})
    assert "Zed" in unknown["error"] and not (env["tmp"] / "m3").exists()


async def test_samples_are_exact_retained_pcm_slices_inside_turns(env):
    """GIVEN a diarization WHEN samples are exported THEN clip PCM equals retained PCM at exact offsets."""
    a = await _diarize(env, "a")
    request = {"action": "samples", **_record_ref(a), "output_directory": str(env["tmp"] / "s"),
               "per_cluster": 2, "max_seconds": 2, "dry_run": True}
    planned = await tool.audio_speakers(request=request)
    assert planned["status"] == "planned" and not (env["tmp"] / "s").exists()
    result = await tool.audio_speakers(request={**request, "dry_run": False})
    retained, _ = wav_pcm((env["tmp"] / "a" / "diarization-input.wav").read_bytes())
    clips = result["record"]["clips"]
    assert [(c["cluster"], c["start_sample"], c["end_sample"]) for c in clips] == [
        ("SPEAKER_00", 0, 32000), ("SPEAKER_00", 81600, 112000), ("SPEAKER_01", 41600, 73600),
        ("SPEAKER_01", 115200, 147200)]
    for clip in clips:
        pcm, count = wav_pcm((env["tmp"] / "s" / clip["path"]).read_bytes())
        assert pcm == retained[2 * clip["start_sample"]:2 * clip["end_sample"]]
        assert count == clip["end_sample"] - clip["start_sample"] and clip["sha256"] == _sha(env["tmp"] / "s" / clip["path"])
    assert clips[2]["start_seconds"] == pytest.approx(12.6)
    unknown = await tool.audio_speakers(request={**request, "output_directory": str(env["tmp"] / "s2"),
                                                  "clusters": ["SPEAKER_07"], "dry_run": False})
    assert "Unknown cluster" in unknown["error"]


async def test_enrollment_requires_explicit_name_and_consent_and_dry_run_writes_nothing(env):
    """GIVEN missing name/consent or dry_run WHEN enrolling THEN no registry file appears."""
    a = await _diarize(env, "a")
    path = env["tmp"] / "speakers.json"
    base = {"registry_path": str(path), **env["runtime"], "consent_confirmed": True, "dry_run": False,
            "source": {"kind": "diarized_cluster", **_record_ref(a), "cluster": "SPEAKER_01"}}
    for bad in ({}, {"speaker_name": ""}, {"speaker_name": "Alice Smith"},
                {"speaker_name": "Alice", "consent_confirmed": False}, {"speaker_name": "Alice", "consent_confirmed": 1}):
        result = await tool.audio_speaker_enroll(request={**base, **bad})
        assert set(result) >= {"error", "category", "hint"}
    planned = await tool.audio_speaker_enroll(request={**base, "speaker_name": "Alice", "dry_run": True})
    assert planned["status"] == "planned" and planned["voiceprints_persisted"] == 0
    assert planned["record"]["would_replace"] is False and planned["record"]["registry_sha256_before"] is None
    assert not path.exists() and env["calls"]["worker"][-1]["operation"] == "diarize"


async def test_enrollment_writes_exactly_one_model_keyed_entry_with_provenance(env):
    """GIVEN an explicit name WHEN enrolled from a cluster THEN one 0600 entry with consent and provenance."""
    a = await _diarize(env, "a")
    path = env["tmp"] / "speakers.json"
    request = {"speaker_name": "Alice", "consent_confirmed": True, "registry_path": str(path), "role": "peer",
               "source": {"kind": "diarized_cluster", **_record_ref(a), "cluster": "SPEAKER_01"},
               **env["runtime"], "dry_run": False}
    result = await tool.audio_speaker_enroll(request=request)
    assert result["status"] == "complete" and result["voiceprints_persisted"] == 1
    assert "embedding" not in result["record"]["entry"]
    stored = json.loads(path.read_bytes())["speakers"]
    assert len(stored) == 1 and stored[0]["model"]["sha256"] == env["models"]["embedding_model"]["sha256"]
    assert env["calls"]["worker"][-1]["groups"] == {"enrollment": [[41600, 80000], [115200, 152000]]}
    assert stored[0]["embedding"] == [0.5, 0.5, 0.5, 0.5] and stored[0]["role"] == "peer"
    assert stored[0]["provenance"]["intervals"] == [[41600, 80000], [115200, 152000]]
    assert stored[0]["consent"]["asserted_by_caller"] is True and stat.S_IMODE(path.stat().st_mode) == 0o600
    duplicate = await tool.audio_speaker_enroll(request=request)
    assert "replace_existing" in duplicate["error"]
    window = await tool.audio_speaker_enroll(request={**request, "replace_existing": True, "source": {
        "kind": "file_window", "file_path": str(env["source"]), "expected_source_sha256": _sha(env["source"]),
        "start_seconds": 1.0, "end_seconds": 4.0}})
    assert window["record"]["replaced"] is True and env["calls"]["export"][-1] == (1.0, 4.0)
    assert not Path(env["calls"]["worker"][-1]["wav"]["path"]).exists()
    listing = await tool.audio_speakers(request={"action": "registry", "registry_path": str(path)})
    assert listing["record"]["speaker_count"] == 1 and "embedding" not in json.dumps(listing)


def test_core_import_never_loads_native_speaker_runtime():
    """GIVEN the core modules WHEN imported THEN only the standalone worker imports numpy or sherpa_onnx."""
    assert "sherpa_onnx" not in sys.modules and "video_research_mcp.speaker_worker" not in sys.modules
    root = Path(speakers.__file__).parent
    for name in ("speakers.py", "speaker_records.py", "speaker_registry.py", "models/speakers.py",
                 "tools/audio_speakers.py", "speaker_worker.py"):
        tree = ast.parse((root / name).read_text())
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module}
        native = imported & {"numpy", "sherpa_onnx"}
        assert native == ({"numpy", "sherpa_onnx"} if name == "speaker_worker.py" else set())



@pytest.mark.parametrize("refusal", ["clock", "hash", "none"])
async def test_r104_export_cleanup_preserves_primary(tmp_path, monkeypatch, caplog, refusal):
    """GIVEN view cleanup fails THEN the refusal survives; success reports cleanup failure."""
    path = tmp_path / "export.wav"
    path.write_bytes(wav_bytes(_signal(1)))
    result = {"artifact": {"path": str(path), "sha256": _sha(path)},
              "selected_window": {"start_seconds": 0, "end_seconds": 1},
              "requested_window": {}, "source_audio_clock": {}, "clock_relationship": {}}
    if refusal == "clock":
        result["selected_window"]["end_seconds"] = 0.5
    elif refusal == "hash":
        result["artifact"]["sha256"] = "0" * 64

    async def export(_request):
        return result

    def cleanup(*_args):
        raise OSError("view cleanup failed")

    monkeypatch.setattr(speakers, "export_audio", export)
    monkeypatch.setattr(speakers, "get_config", lambda: SimpleNamespace(cache_dir=str(tmp_path)))
    monkeypatch.setattr(speakers, "_discard_views", cleanup)
    expected = OSError if refusal == "none" else ValueError
    match = {"clock": "complete requested", "hash": "differs", "none": "view cleanup failed"}[refusal]
    with pytest.raises(expected, match=match) as caught:
        await speakers._export_wav(str(path), _sha(path), 0, 1)
    if refusal != "none":
        assert "view cleanup failed" in " ".join(caught.value.__notes__)
        assert "view cleanup failed" in caplog.text


@pytest.mark.parametrize("cancelled", [False, True])
async def test_r104_worker_primary_survives_staging_cleanup(env, monkeypatch, caplog, cancelled):
    """GIVEN worker refusal/cancellation and failed staging cleanup THEN the primary survives."""
    primary = asyncio.CancelledError("worker cancelled") if cancelled else ValueError("worker refused")

    async def worker(_runtime, _payload):
        raise primary

    def cleanup(*_args, **_kwargs):
        raise OSError("staging cleanup failed")

    monkeypatch.setattr(speakers, "_run_worker", worker)
    monkeypatch.setattr(speakers.shutil, "rmtree", cleanup)
    if cancelled:
        with pytest.raises(asyncio.CancelledError) as caught:
            await _diarize(env, "out")
        assert caught.value is primary
    else:
        result = await _diarize(env, "out")
        assert "worker refused" in result["error"]
    assert "staging cleanup failed" in " ".join(primary.__notes__)
    assert "staging cleanup failed" in caplog.text
    assert not (env["tmp"] / "out").exists()
    assert len(list(env["tmp"].glob(".out.*.pending"))) == 1


PARENT_MUTATIONS = [
    ("turns", 0, "wav_start_seconds", -1), ("turns", 0, "wav_end_seconds", 0),
    ("turns", 0, "wav_end_seconds", 11), ("turns", 0, "start_seconds", 9),
    ("turns", 0, "end_seconds", 11), ("turns", 0, "native_cluster_id", -1),
    ("turns", 0, "native_cluster_id", True), ("turns", 0, "cluster", "SPEAKER_99"),
    ("turns", 0, "cluster_similarity", 1.1),
    ("turns", 0, "confidence_unavailable_reason", "singleton_cluster"),
    ("cards", 0, "turn_count", 3), ("cards", 0, "speaking_seconds", True),
    ("selection", "end_seconds", 21), ("selection", "start_seconds", -1),
    ("audio", "sample_count", 160001), ("audio", "sample_count", 160000.0),
    ("audio", "bytes", 1), ("audio", "sample_rate", 8000),
    ("observed_cluster_count", 3), ("names_assigned", True),
    ("confidence_kind", "probability"), ("config", "threshold", 0.4),
    ("turns", 0, "wav_end_seconds", 0.00001),
    ("selection", "requested", "end_seconds", 22),
    ("runtime", "embedding_model", "dimension", True),
    ("source", "sha256", "bad"),
    ("selection", "source_audio_clock", "first_seconds", 9),
    ("selection", "source_audio_clock", "end_seconds", 21),
    ("selection", "source_audio_clock", "sample_count", 160001),
    ("selection", "source_audio_clock", "duration_seconds", 11),
    ("selection", "source_audio_clock", "sample_rate", True),
    ("selection", "clock_relationship", "output_origin_seconds", 1),
    ("selection", "clock_relationship", "source_origin_seconds", 9),
    ("selection", "clock_relationship", "tolerance_seconds", 1),
    ("selection", "clock_relationship", "sample_count_verified", False),
]


@pytest.mark.parametrize("action", ["relabel", "samples", "enroll"])
@pytest.mark.parametrize("mutation", PARENT_MUTATIONS)
async def test_r104_parent_contract_refuses_before_outputs_or_embedding(env, action, mutation):
    """GIVEN a hash-matching malformed parent THEN derived actions refuse without side effects."""
    a = await _diarize(env, "a")
    path = Path(a["output_directory"]) / "diarization.json"
    parent = json.loads(path.read_bytes())
    cursor = parent
    for key in mutation[:-2]:
        cursor = cursor[key]
    cursor[mutation[-2]] = mutation[-1]
    path.write_text(json.dumps(parent))
    before = _tree(env["tmp"])
    worker_count = len(env["calls"]["worker"])
    reference = _record_ref(a)
    if action == "enroll":
        request = {"speaker_name": "Alice", "consent_confirmed": True, "dry_run": False,
                   "registry_path": str(env["tmp"] / "speakers.json"), **env["runtime"],
                   "source": {"kind": "diarized_cluster", **reference, "cluster": "SPEAKER_00"}}
        result = await tool.audio_speaker_enroll(request=request)
    else:
        request = {"action": action, **reference, "dry_run": False,
                   "output_directory": str(env["tmp"] / "derived")}
        if action == "relabel":
            request["assignments"] = {"SPEAKER_00": "Alice"}
        result = await tool.audio_speakers(request=request)
    assert "error" in result
    assert len(env["calls"]["worker"]) == worker_count and _tree(env["tmp"]) == before


@pytest.mark.parametrize("end_seconds", [10.0 + 1 / RATE, 0.00001])
async def test_diarize_refuses_turns_that_cannot_select_retained_samples(env, monkeypatch, end_seconds):
    """A complete producer result must remain usable by every derived action."""
    monkeypatch.setattr(sys.modules[__name__], "SCRIPT", [(7, 0.0, end_seconds, 0.91)])
    result = await _diarize(env, "invalid-producer")
    assert "error" in result
    assert not (env["tmp"] / "invalid-producer").exists()
    assert len(env["calls"]["worker"]) == 1
