"""Retained-artifact read bounds and race refusal with tiny authored fixtures."""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_research_mcp.models.video_memory_av import MemoryState
from video_research_mcp.video_memory import av_store


@pytest.fixture
def retained(tmp_path):
    """Publish one real immutable revision and a tiny content-addressed artifact."""
    payload = b'{"caller_authored":"tiny"}'
    digest = hashlib.sha256(payload).hexdigest()
    source = tmp_path / "source.bin"
    source.write_bytes(b"authored source fixture")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    state = MemoryState(memory_id="avm:" + source_digest, revision=1,
                        source={"sha256": source_digest, "bytes": source.stat().st_size,
                                "path": str(source), "duration_seconds": 1.0},
                        windows=1, artifacts=[], records=[], persons=[])
    root = tmp_path / "memory"
    av_store.commit(root, state, {digest: payload})
    return {"root": root, "state": state.model_copy(update={"revision": 2}),
            "payload": payload, "digest": digest,
            "target": root / "artifacts" / f"{digest}.json",
            "revision_bytes": (root / "rev-000001.json").read_bytes()}


def assert_revision_unchanged(retained):
    """Require the original revision bytes and no later revision after refusal."""
    root = retained["root"]
    assert (root / "rev-000001.json").read_bytes() == retained["revision_bytes"]
    assert not (root / "rev-000002.json").exists()


def commit_next(retained):
    """Reuse the admitted payload while publishing exactly the next revision."""
    return av_store.commit(retained["root"], retained["state"],
                           {retained["digest"]: retained["payload"]})


def instrument_read(monkeypatch, retained, mutate, forbid_read=False):
    """Spy on actual file I/O; refuse legacy unbounded reads before allocating data."""
    target, bound = retained["target"], len(retained["payload"]) + 1
    read_sizes = []
    original_bytes, original_regular = Path.read_bytes, av_store._open_regular

    def read_bytes(path):
        if path == target:
            raise AssertionError("retained artifact reached unbounded Path.read_bytes")
        return original_bytes(path)

    @contextmanager
    def open_regular(path):
        with original_regular(path) as reader:
            if path != target:
                yield reader
                return

            def read(size=-1):
                read_sizes.append(size)
                assert not forbid_read, "oversized retained artifact was read before size refusal"
                assert size == bound, "retained read must use admitted payload length plus one"
                mutate("before")
                data = reader.read(size)
                mutate("after")
                return data

            yield SimpleNamespace(fileno=reader.fileno, read=read)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(av_store, "_open_regular", open_regular)
    return read_sizes


@pytest.mark.parametrize("sparse_size", [8 * 1024 * 1024 + 1, 32 * 1024 * 1024 + 1])
def test_oversized_existing_artifact_is_refused_before_read(retained, monkeypatch, sparse_size):
    """GIVEN an oversized sparse cache WHEN reused THEN reject before acquiring its bytes."""
    with retained["target"].open("r+b") as stream:
        stream.truncate(sparse_size)
    reads = instrument_read(monkeypatch, retained, lambda when: None, forbid_read=True)
    with pytest.raises(ValueError, match="Retained artifact"):
        try:
            commit_next(retained)
        finally:
            assert_revision_unchanged(retained)
    assert reads == []
    assert retained["target"].stat().st_size == sparse_size


@pytest.mark.parametrize("phase", ["before", "after"])
def test_growth_during_bounded_read_is_refused(retained, monkeypatch, phase):
    """GIVEN growth around the bounded read WHEN reused THEN refuse without a revision."""
    def grow(when):
        if when == phase:
            with retained["target"].open("ab") as stream:
                stream.write(b"x")

    reads = instrument_read(monkeypatch, retained, grow)
    with pytest.raises(ValueError, match="Retained artifact"):
        try:
            commit_next(retained)
        finally:
            assert_revision_unchanged(retained)
    assert reads == [len(retained["payload"]) + 1]


def test_same_bytes_path_replacement_during_read_is_refused(retained, monkeypatch):
    """GIVEN identical bytes at a substituted inode WHEN reused THEN reject the path race."""
    replacement = retained["target"].with_name("replacement.json")
    replacement.write_bytes(retained["payload"])

    def replace(when):
        if when == "after":
            os.replace(replacement, retained["target"])

    reads = instrument_read(monkeypatch, retained, replace)
    with pytest.raises(ValueError, match="Retained artifact"):
        try:
            commit_next(retained)
        finally:
            assert_revision_unchanged(retained)
    assert reads == [len(retained["payload"]) + 1]


def test_same_size_mutation_after_read_is_refused(retained, monkeypatch):
    """GIVEN bytes changed after hashing input WHEN reused THEN reject metadata drift."""
    initial = retained["target"].stat()

    def mutate(when):
        if when == "after":
            with retained["target"].open("r+b") as stream:
                stream.write(b"!")
            os.utime(retained["target"], ns=(initial.st_atime_ns, initial.st_mtime_ns + 1))

    reads = instrument_read(monkeypatch, retained, mutate)
    with pytest.raises(ValueError, match="Retained artifact"):
        try:
            commit_next(retained)
        finally:
            assert_revision_unchanged(retained)
    assert reads == [len(retained["payload"]) + 1]


def test_existing_valid_artifact_reuses_bytes_and_publishes_next_revision(retained):
    """GIVEN a valid existing digest WHEN reused THEN preserve bytes and publish revision two."""
    before = retained["target"].stat()
    result = commit_next(retained)
    after = retained["target"].stat()
    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    assert retained["target"].read_bytes() == retained["payload"]
    assert result["revision"] == 2 and result["path"] == "rev-000002.json"
    assert (retained["root"] / "rev-000001.json").read_bytes() == retained["revision_bytes"]
    loaded = av_store.load(retained["root"], retained["state"].source.sha256)
    assert loaded.revision == 2 and loaded.source == retained["state"].source


def test_existing_same_size_wrong_digest_is_refused(retained):
    """GIVEN wrong bytes of the admitted size WHEN reused THEN preserve digest refusal."""
    retained["target"].write_bytes(b"!" + retained["payload"][1:])
    with pytest.raises(ValueError, match="Retained artifact address holds different bytes"):
        commit_next(retained)
    assert_revision_unchanged(retained)
