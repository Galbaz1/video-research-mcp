"""Tests for the generic file-based cache."""

from __future__ import annotations

from pathlib import Path
import json
import hashlib
from copy import deepcopy

import pytest

import video_research_mcp.config as cfg_mod
from video_research_mcp import cache
from video_research_mcp.media_identity import identify_source

_SOURCE_ROOT = None


def _request(content_id, tool_name, model, instruction=""):
    _SOURCE_ROOT.mkdir(exist_ok=True)
    path = _SOURCE_ROOT / (hashlib.sha256(content_id.encode()).hexdigest() + ".bin")
    if not path.exists():
        path.write_bytes(content_id.encode())
    source = identify_source(str(path))
    contract = {
        "source_digest": source.digest,
        "source_revision": source.revision,
        "provider": "fixture-provider",
        "account_scope": "fixture-account",
        "model": model,
        "tool_name": tool_name,
        "output_schema": {"type": "object"},
        "thinking_level": "high",
        "prompt": instruction,
        "metadata": None,
        "preprocessing": [],
        "window": [],
        "sampling": {},
        "retrieval_revision": None,
    }
    return contract, source


def _save(content_id, tool, model, analysis, instruction=""):
    contract, source = _request(content_id, tool, model, instruction)
    return cache.save(
        content_id, tool, model, analysis, instruction=instruction, contract=contract, source=source
    )


def _load(content_id, tool, model, instruction=""):
    contract, source = _request(content_id, tool, model, instruction)
    return cache.load(
        content_id, tool, model, instruction=instruction, contract=contract, source=source
    )


def _cache_path(content_id, tool, model, instruction=""):
    contract, _ = _request(content_id, tool, model, instruction)
    return cache.cache_path(content_id, tool, model, instruction=instruction, contract=contract)


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    """Point cache at a temp directory."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    cfg_mod._config = None
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    cfg_mod._config = None
    monkeypatch.setattr(
        __import__(__name__, fromlist=["_SOURCE_ROOT"]), "_SOURCE_ROOT", tmp_path / "sources"
    )
    yield
    cfg_mod._config = None


class TestCache:
    @pytest.mark.parametrize(
        "payload", [[], None, "broken", 1, {"analysis": []}, {"analysis": {}}, {"error": "failed"}]
    )
    def test_malformed_or_failed_payload_is_a_miss(self, payload):
        path = _cache_path("bad", "analyze", "model")
        path.write_text(json.dumps(payload))
        assert _load("bad", "analyze", "model") is None
        cache.list_entries()

    @pytest.mark.parametrize("artifact_state", ["missing", "empty", "corrupt", "symlink"])
    def test_unverified_artifact_paths_are_never_cached_proof(self, tmp_path, artifact_state):
        artifact = tmp_path / "proof.html"
        if artifact_state == "empty":
            artifact.touch()
        elif artifact_state == "corrupt":
            artifact.write_text("corrupt bytes")
        elif artifact_state == "symlink":
            original = tmp_path / "original"
            original.write_text("outside the artifact scope")
            artifact.symlink_to(original)
        result = {"artifacts": {"proof": str(artifact)}, "quality_report": {"status": "pass"}}
        assert _save("proof", "analyze", "model", result) is False
        # Historical cache files cannot bypass the current writer policy.
        _cache_path("proof", "analyze", "model").write_text(json.dumps({"analysis": result}))
        assert _load("proof", "analyze", "model") is None

    def test_save_and_load(self):
        data = {"title": "Test Video", "summary": "A summary"}
        assert _save("vid123", "analyze", "gemini-pro", data) is True

        loaded = _load("vid123", "analyze", "gemini-pro")
        assert loaded is not None
        assert loaded["title"] == "Test Video"

    def test_cache_miss(self):
        assert _load("nonexistent", "analyze", "gemini-pro") is None

    def test_clear_specific(self):
        _save("vid1", "analyze", "model", {"a": 1})
        _save("vid2", "analyze", "model", {"b": 2})
        removed = cache.clear("vid1")
        assert removed >= 1
        assert _load("vid1", "analyze", "model") is None
        assert _load("vid2", "analyze", "model") is not None

    def test_clear_specific_does_not_delete_prefix_matches(self):
        _save("vid1", "analyze", "model", {"a": 1})
        _save("vid12", "analyze", "model", {"b": 2})
        removed = cache.clear("vid1")
        assert removed == 1
        assert _load("vid1", "analyze", "model") is None
        assert _load("vid12", "analyze", "model") is not None

    def test_clear_all(self):
        _save("vid1", "analyze", "model", {"a": 1})
        _save("vid2", "analyze", "model", {"b": 2})
        removed = cache.clear()
        assert removed >= 2

    def test_clear_all_removes_corrupt_and_legacy_entries_but_preserves_registries(self):
        directory = cache._cache_dir()
        entries = [directory / "v2_corrupt.json", directory / "legacy.json"]
        for path in entries:
            path.write_text("{truncated")
        registries = [directory / name for name in cache._REGISTRY_FILES]
        for path in registries:
            path.write_text("{truncated")

        assert cache.clear("unbound-source") == 0
        assert all(path.exists() for path in entries)
        assert cache.clear() == 2
        assert all(not path.exists() for path in entries)
        assert all(path.read_text() == "{truncated" for path in registries)

    def test_stats(self):
        _save("vid1", "t", "m", {"x": 1})
        s = cache.stats()
        assert s["total_files"] >= 1
        assert "total_size_mb" in s

    def test_list_entries(self):
        _save("vid1", "t", "m", {"x": 1})
        entries = cache.list_entries()
        assert len(entries) >= 1
        assert entries[0]["content_id"] == "vid1"

    def test_save_is_atomic_when_replace_fails(self, monkeypatch):
        """A failed atomic replace should preserve the previously committed cache payload."""
        assert _save("vid_atomic", "analyze", "model", {"version": 1}) is True

        original_replace = Path.replace

        def _fail_replace(self: Path, target: Path) -> Path:
            if self.suffix == ".tmp":
                raise OSError("simulated replace failure")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", _fail_replace)
        assert _save("vid_atomic", "analyze", "model", {"version": 2}) is False

        loaded = _load("vid_atomic", "analyze", "model")
        assert loaded is not None
        assert loaded["version"] == 1

    def test_list_entries_with_missing_cached_at(self, tmp_path, monkeypatch):
        """list_entries sorts safely when cached_at is None or missing."""
        import json

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(exist_ok=True)

        # Entry with cached_at = None (key exists but value is None)
        (cache_dir / "none_entry.json").write_text(
            json.dumps({"content_id": "vid_none", "tool": "t", "cached_at": None})
        )
        # Entry with cached_at missing entirely
        (cache_dir / "missing_entry.json").write_text(
            json.dumps({"content_id": "vid_missing", "tool": "t"})
        )
        # Normal entry
        _save("vid_ok", "t", "m", {"x": 1})

        entries = cache.list_entries()
        assert len(entries) >= 3
        # Should not raise — the fix ensures None values don't crash sorted()
        ids = [e["content_id"] for e in entries]
        assert "vid_none" in ids
        assert "vid_missing" in ids


class TestCacheWithInstruction:
    """Verify that instruction param differentiates cache entries."""

    def test_different_instructions_different_keys(self):
        """Same content + different instruction → different cache entries."""
        _save("vid1", "analyze", "model", {"a": 1}, instruction="summarize")
        _save("vid1", "analyze", "model", {"b": 2}, instruction="list recipes")

        loaded1 = _load("vid1", "analyze", "model", instruction="summarize")
        loaded2 = _load("vid1", "analyze", "model", instruction="list recipes")

        assert loaded1 is not None
        assert loaded2 is not None
        assert loaded1["a"] == 1
        assert loaded2["b"] == 2

    def test_empty_instruction_uses_default_key(self):
        """No instruction → 'default' hash segment."""
        key_no_instr = cache.cache_key("vid1", "analyze", "model")
        key_empty = cache.cache_key("vid1", "analyze", "model", instruction="")
        assert key_no_instr == key_empty
        assert len(key_no_instr) == 67
        assert key_no_instr.startswith("v2_")

    def test_instruction_miss(self):
        """Cache with one instruction misses for a different instruction."""
        _save("vid1", "analyze", "model", {"a": 1}, instruction="summarize")
        assert _load("vid1", "analyze", "model", instruction="different") is None

    def test_clear_clears_all_instructions(self):
        """Clearing by content_id removes all instruction variants."""
        _save("vid1", "analyze", "model", {"a": 1}, instruction="summarize")
        _save("vid1", "analyze", "model", {"b": 2}, instruction="list recipes")
        removed = cache.clear("vid1")
        assert removed == 2


@pytest.mark.parametrize(
    "field",
    [
        "source_digest",
        "source_revision",
        "provider",
        "account_scope",
        "model",
        "output_schema",
        "thinking_level",
        "prompt",
        "metadata",
        "preprocessing",
        "window",
        "sampling",
        "retrieval_revision",
    ],
)
def test_every_result_contract_field_participates_in_identity(field):
    contract, _ = _request("owned", "analyze", "model")
    changed = deepcopy(contract)
    changed[field] = {"changed": field}
    assert cache.cache_key("owned", "analyze", "model", contract=contract) != cache.cache_key(
        "owned", "analyze", "model", contract=changed
    )


def test_equivalent_json_mapping_order_has_one_deterministic_key():
    contract, source = _request("owned", "analyze", "model")
    reordered = dict(reversed(list(contract.items())))
    assert cache.cache_key("owned", "analyze", "model", contract=contract) == cache.cache_key(
        "owned", "analyze", "model", contract=reordered
    )
    assert cache.save(
        "owned", "analyze", "model", {"answer": "owned"}, contract=contract, source=source
    )
    assert cache.load("owned", "analyze", "model", contract=reordered, source=source) == {
        "answer": "owned"
    }


def test_legacy_entries_and_missing_contract_are_explicit_misses():
    path = cache.cache_path("legacy", "analyze", "model")
    path.write_text(json.dumps({"analysis": {"answer": "legacy"}}))
    assert cache.load("legacy", "analyze", "model") is None
    assert cache.save("legacy", "analyze", "model", {"answer": "legacy"}) is False


def test_content_id_traversal_cannot_escape_cache_root():
    path = cache.cache_path("../../outside", "../tool", "model")
    assert path.parent == cache._cache_dir()
    assert path.name.startswith("v2_")


def test_deleted_original_invalidates_dependent_results():
    contract, source = _request("owned", "analyze", "model")
    assert cache.save(
        "owned", "analyze", "model", {"answer": "owned"}, contract=contract, source=source
    )
    Path(source.alias).unlink()
    assert cache.load("owned", "analyze", "model", contract=contract, source=source) is None
    assert not cache.cache_path("owned", "analyze", "model", contract=contract).exists()


def test_uninspected_remote_source_never_replays_or_saves():
    contract, _ = _request("owned", "analyze", "model")
    source = identify_source("https://example.com/owned")
    assert (
        cache.save(
            "owned", "analyze", "model", {"answer": "owned"}, contract=contract, source=source
        )
        is False
    )
    assert cache.load("owned", "analyze", "model", contract=contract, source=source) is None
