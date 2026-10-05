"""Model-separated voiceprint registry: validation, locked 0600 writes, listing and suggestions."""

import json
import math
import os
import stat

import pytest

from video_research_mcp import speaker_registry as registry

MODEL_A = {"basename": "titanet.onnx", "sha256": "a" * 64, "dimension": 3}
MODEL_B = {"basename": "other.onnx", "sha256": "b" * 64, "dimension": 2}


def _entry(name, model=MODEL_A, vector=None, **extra):
    vector = vector or [1.0, 0.0, 0.0][:model["dimension"]]
    return {"name": name, "model": model, "embedding": vector, "added": "2026-10-05T00:00:00Z",
            "provenance": {"kind": "file_window"}, "consent": {"asserted_by_caller": True,
                                                                "recorded_at": "2026-10-05T00:00:00Z"}, **extra}


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_absent_registry_is_empty_and_enroll_creates_it_0600(tmp_path):
    """GIVEN no registry WHEN one entry is enrolled THEN a 0600 file holds exactly that entry."""
    path = tmp_path / "speakers.json"
    assert registry.read(path) == ({"format": registry.FORMAT, "speakers": []}, None)
    outcome = registry.enroll(path, _entry("Alice"), replace_existing=False)
    assert outcome["registry_sha256_before"] is None and outcome["replaced"] is False
    assert _mode(path) == 0o600 and _mode(tmp_path / "speakers.json.lock") == 0o600
    value, digest = registry.read(path)
    assert digest == outcome["registry_sha256_after"] and [e["name"] for e in value["speakers"]] == ["Alice"]
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".pending")]


def test_same_name_is_separate_per_embedding_model_and_duplicates_need_replace(tmp_path):
    """GIVEN Alice under model A WHEN enrolled under B THEN both exist; a second A entry needs replace."""
    path = tmp_path / "speakers.json"
    registry.enroll(path, _entry("Alice"), False)
    registry.enroll(path, _entry("Bob", vector=[0.0, 1.0, 0.0]), False)
    registry.enroll(path, _entry("Alice", MODEL_B, [0.0, 1.0]), False)
    before = {(e["name"], e["model"]["sha256"]): e for e in registry.read(path)[0]["speakers"]}
    with pytest.raises(FileExistsError, match="replace_existing"):
        registry.enroll(path, _entry("Alice", vector=[0.6, 0.8, 0.0]), False)
    outcome = registry.enroll(path, _entry("Alice", vector=[0.6, 0.8, 0.0]), True)
    assert outcome["replaced"] is True and outcome["previous_voiceprint_cosine"] == pytest.approx(0.6)
    after = {(e["name"], e["model"]["sha256"]): e for e in registry.read(path)[0]["speakers"]}
    assert after[("Alice", "a" * 64)]["embedding"] == [0.6, 0.8, 0.0]
    assert {k: v for k, v in after.items() if k != ("Alice", "a" * 64)} == {
        k: v for k, v in before.items() if k != ("Alice", "a" * 64)}


@pytest.mark.parametrize("speakers", [
    [_entry("Alice"), _entry("Alice")],
    [_entry("Alice"), _entry("Bob", {**MODEL_A, "dimension": 2}, [1.0, 0.0])],
    [_entry("Alice", vector=[0.0, 0.0, 0.0])],
    [_entry("Alice", vector=[1.0, 0.0])],
    [_entry("Alice", vector=[1.0, float("inf"), 0.0])],
    [_entry("Alice", {**MODEL_A, "sha256": "titanet"})],
    [_entry("Alice", {"basename": "x", "sha256": "a" * 64}, [1.0, 0.0, 0.0])],
    [_entry("Al ice")],
    [_entry("Alice", role="Boss")],
    [_entry("Alice", consent={"asserted_by_caller": False, "recorded_at": "now"})],
    [{k: v for k, v in _entry("Alice").items() if k != "consent"}],
    [_entry("Alice", extra="x")],
])
def test_validation_refuses_ambiguous_or_unsafe_entries(speakers):
    """GIVEN duplicate, mixed-dimension, zero/non-finite or unkeyed entries WHEN validated THEN refused."""
    with pytest.raises(ValueError):
        registry.validate({"format": registry.FORMAT, "speakers": speakers})


def test_read_refuses_group_readable_symlinked_or_nonfinite_files(tmp_path):
    """GIVEN unsafe registry files WHEN read THEN they are refused rather than repaired."""
    path = tmp_path / "speakers.json"
    path.write_text(json.dumps({"format": registry.FORMAT, "speakers": []}))
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError, match="0600"):
        registry.read(path)
    os.chmod(path, 0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        registry.read(link)
    path.write_text('{"format": "speaker-registry/v1", "speakers": [], "speakers": []}')
    with pytest.raises(ValueError):
        registry.read(path)


def test_failed_write_leaves_existing_registry_byte_identical(tmp_path, monkeypatch):
    """GIVEN an invalid replacement WHEN enrolled THEN the prior bytes and no temporary file remain."""
    path = tmp_path / "speakers.json"
    registry.enroll(path, _entry("Alice"), False)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        registry.enroll(path, _entry("Bob", {**MODEL_A, "dimension": 2}, [1.0, 0.0]), False)
    monkeypatch.setattr(registry.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        registry.enroll(path, _entry("Bob", vector=[0.0, 0.0, 1.0]), False)
    assert path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".speakers")) == []


def test_listing_groups_by_model_and_never_returns_voiceprints(tmp_path):
    """GIVEN entries under two models WHEN listed THEN groups carry metadata only."""
    path = tmp_path / "speakers.json"
    registry.enroll(path, _entry("Bob", role="peer"), False)
    registry.enroll(path, _entry("Alice"), False)
    registry.enroll(path, _entry("Alice", MODEL_B, [0.0, 1.0]), False)
    listing = registry.listing(registry.read(path)[0])
    assert listing["speaker_count"] == 3
    assert [g["model"]["sha256"] for g in listing["models"]] == ["a" * 64, "b" * 64]
    assert [s["name"] for s in listing["models"][0]["speakers"]] == ["Alice", "Bob"]
    assert listing["models"][0]["speakers"][1]["role"] == "peer"
    assert "embedding" not in json.dumps(listing)


def test_rank_suggests_only_same_model_entries_and_never_applies_them():
    """GIVEN mixed-model entries WHEN ranked THEN only same-model cosines appear, unapplied."""
    value = registry.validate({"format": registry.FORMAT, "speakers": [
        _entry("Alice"), _entry("Bob", vector=[0.0, 1.0, 0.0]), _entry("Carol", MODEL_B, [1.0, 0.0])]})
    suggestions, ignored = registry.rank(value, MODEL_A, {"SPEAKER_00": [0.8, 0.6, 0.0]}, [])
    assert ignored == 1
    assert [(s["name"], round(s["cosine"], 6), s["applied"]) for s in suggestions["SPEAKER_00"]] == [
        ("Alice", 0.8, False), ("Bob", 0.6, False)]
    restricted, _ = registry.rank(value, MODEL_A, {"SPEAKER_00": [0.8, 0.6, 0.0]}, ["Bob"])
    assert [s["name"] for s in restricted["SPEAKER_00"]] == ["Bob"]
    with pytest.raises(ValueError, match="Carol"):
        registry.rank(value, MODEL_A, {}, ["Carol"])
    with pytest.raises(ValueError, match="dimension"):
        registry.rank(value, {**MODEL_A, "dimension": 4}, {}, [])


def test_cosine_and_unit_are_pure_python_and_refuse_zero_vectors():
    """GIVEN vectors WHEN compared THEN cosine is scale invariant and zero vectors are refused."""
    assert registry.cosine([3.0, 4.0], [6.0, 8.0]) == pytest.approx(1.0)
    assert math.isclose(sum(v * v for v in registry.unit([3.0, 4.0])), 1.0)
    with pytest.raises(ValueError):
        registry.unit([0.0, 0.0])



@pytest.mark.parametrize("existing", [False, True])
def test_r104_oversize_write_refuses_before_tempfile_and_preserves_registry(tmp_path, monkeypatch, existing):
    """GIVEN a write crossing 16 MiB THEN refusal precedes tempfile creation and preserves bytes."""
    path = tmp_path / "speakers.json"
    if existing:
        registry.enroll(path, _entry("Alice"), False)
    before = path.read_bytes() if existing else None
    entry = _entry("Bob", provenance={"padding": "x" * registry.MAX_REGISTRY_BYTES})
    calls = []
    mkstemp = registry.tempfile.mkstemp

    def temporary(*args, **kwargs):
        calls.append(True)
        return mkstemp(*args, **kwargs)

    monkeypatch.setattr(registry.tempfile, "mkstemp", temporary)
    with pytest.raises(ValueError, match="16 MiB"):
        registry.enroll(path, entry, False)
    assert calls == []
    assert (path.read_bytes() if path.exists() else None) == before
    assert not list(tmp_path.glob("*.pending"))
