"""Real transaction interleavings and owned-file admission security regressions."""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_research_mcp import collections_media
from video_research_mcp import collections_owned_io
from video_research_mcp.collections import execute
from video_research_mcp.collections_store import transaction
from video_research_mcp.corpus_index import connect, revision
from video_research_mcp.models.collections import Configure, Create, Put, Read


@pytest.fixture
def scope(tmp_path, monkeypatch, clean_config):
    """Configure a real canonical index with eight bytes of owned media quota."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    value = {"index_path": str(tmp_path / "corpus.sqlite3"), "workspace": "edit"}
    configure(value, tmp_path / "owned", "media")
    return value


def configure(scope, root, collection):
    """Enroll an independent workspace and collection in the same canonical index."""
    execute(Configure(action="configure", owned_root=str(root), quota_bytes=8, **scope))
    execute(Create(action="create", collection=collection, expected_revision=0,
                   kind="media", label="Fixture", **scope))


def admit(scope, tmp_path, asset="x", collection="media", data=b"1234"):
    """Copy dummy bytes through the actual admission and optimistic revision contracts."""
    source = tmp_path / (scope["workspace"] + asset + ".source")
    source.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    with connect(scope["index_path"]) as db:
        expected = revision(db, collection)
    return execute(Put(action="admit", collection=collection, expected_revision=expected,
                       evidence={"asset_id": asset, "video_id": "v", "source_revision": "r",
                                 "media_digest": digest, "kind": "video", "path": str(source),
                                 "sha256": digest, "size_bytes": len(data)}, **scope))


def snapshot(scope):
    """Retain provenance, reservations, liabilities, recency and shared revision together."""
    with connect(scope["index_path"]) as db:
        return {table: [dict(row) for row in db.execute("SELECT * FROM " + table)]
                for table in ("collection_assets", "collection_workspaces", "collections")}


@pytest.mark.parametrize("replacement", ["absent", "same_workspace", "cross_workspace"])
def test_stale_cleanup_cannot_reclaim_reused_identity(scope, tmp_path, monkeypatch, replacement):
    """WHEN a competing cleanup finishes THEN the stale intent cannot affect a new admission."""
    old = Path(admit(scope, tmp_path)["records"][0]["path"])
    other = {**scope, "workspace": "other"}
    if replacement == "cross_workspace":
        configure(other, tmp_path / "other-owned", "other-media")
    calls, interleaving = 0, False
    new, expected = None, None

    @contextmanager
    def scheduled(path, **kwargs):
        nonlocal calls, interleaving, new, expected
        if not interleaving:
            calls += 1
            if calls == 2:
                interleaving = True
                winner = collections_media.cleanup(path, scope["workspace"], ["x"])
                assert winner["reclaimed_bytes"] == 4
                assert not old.exists()
                if replacement != "absent":
                    target_scope = other if replacement == "cross_workspace" else scope
                    collection = "other-media" if replacement == "cross_workspace" else "media"
                    new = Path(admit(target_scope, tmp_path, collection=collection, data=b"keep")["records"][0]["path"])
                expected = snapshot(scope)
        with transaction(path, **kwargs) as db:
            yield db

    monkeypatch.setattr(collections_media, "transaction", scheduled)
    result = collections_media.cleanup(scope["index_path"], scope["workspace"], ["x"])
    assert calls == 2
    assert result["reclaimed_bytes"] == 0
    assert not result["cleanup_liabilities"]
    if new is not None:
        assert new.read_bytes() == b"keep"
    assert snapshot(scope) == expected


@pytest.mark.parametrize("state", ["failed", "cleanup", "pending"])
def test_grown_nonready_reservation_blocks_admission_without_metadata_effects(scope, tmp_path, state):
    """WHEN any unresolved four-byte reservation grows THEN eight-byte quota refuses new bytes."""
    target = Path(admit(scope, tmp_path)["records"][0]["path"])
    with transaction(scope["index_path"]) as db:
        db.execute("UPDATE collection_assets SET state=?,liability='original liability' WHERE asset='x'", (state,))
    target.write_bytes(b"123456789012")
    before = snapshot(scope)
    with pytest.raises(PermissionError, match="quota accounting"):
        admit(scope, tmp_path, asset="new")
    assert snapshot(scope) == before
    assert target.read_bytes() == b"123456789012"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("state", ["failed", "cleanup", "pending"])
def test_short_partial_keeps_full_reservation_and_original_liability(scope, tmp_path, state):
    """WHEN a partial copy is shorter THEN its full charge remains and remaining quota is usable."""
    target = Path(admit(scope, tmp_path)["records"][0]["path"])
    with transaction(scope["index_path"]) as db:
        db.execute("UPDATE collection_assets SET state=?,liability='original liability' WHERE asset='x'", (state,))
    target.write_bytes(b"12")
    before = snapshot(scope)["collection_assets"][0]
    assert admit(scope, tmp_path, asset="new")["status"] == "admitted"
    assert snapshot(scope)["collection_assets"][0] == before
    health = execute(Read(action="health", **scope))["storage"]
    assert health["reserved_bytes"] == 8
    assert health["liability_count"] == 1
    assert target.read_bytes() == b"12"


def test_root_substitution_before_creation_leaves_outside_empty(scope, tmp_path, monkeypatch):
    """WHEN the root becomes an outside symlink THEN admission refuses before creating outside bytes."""
    root, saved, outside = (tmp_path / name for name in ("owned", "saved", "outside"))
    outside.mkdir(mode=0o700)
    real_open, swapped, directory_fds = os.open, False, []

    def substitute(path, flags, *args, **kwargs):
        nonlocal swapped
        fd = real_open(path, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY:
            directory_fds.append(fd)
        if str(path).endswith("editx.source") and not swapped:
            swapped = True
            root.rename(saved)
            root.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(os, "open", substitute)
    result = admit(scope, tmp_path)
    assert swapped
    assert result["status"] == "partial"
    assert list(outside.iterdir()) == []
    assert list(saved.iterdir()) == []
    with connect(scope["index_path"]) as db:
        asset = dict(db.execute("SELECT * FROM collection_assets WHERE asset='x'").fetchone())
        assert asset["state"] == "failed" and asset["size"] == 4
        assert asset["liability"]
        assert revision(db, "media") == 1
    for fd in directory_fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("replacement", ["file", "directory"])
def test_changed_output_before_promotion_retains_liability(scope, tmp_path, monkeypatch, replacement):
    """WHEN the created output identity changes THEN promotion refuses without deleting replacement bytes."""
    calls, replacement_path = 0, None

    @contextmanager
    def scheduled(path, **kwargs):
        nonlocal calls, replacement_path
        calls += 1
        if calls == 2:
            target = next((tmp_path / "owned").iterdir())
            if replacement == "file":
                target.unlink()
            else:
                target.parent.rename(tmp_path / "saved")
                target.parent.mkdir(mode=0o700)
            target.write_bytes(b"keep")
            replacement_path = target
        with transaction(path, **kwargs) as db:
            yield db

    monkeypatch.setattr(collections_media, "transaction", scheduled)
    result = admit(scope, tmp_path)
    assert result["status"] == "partial"
    assert replacement_path.read_bytes() == b"keep"
    with connect(scope["index_path"]) as db:
        asset = dict(db.execute("SELECT * FROM collection_assets WHERE asset='x'").fetchone())
        assert asset["state"] == "failed" and asset["size"] == 4
        assert revision(db, "media") == 1
    assert result["cleanup_liabilities"]


def test_reservation_rollback_closes_held_directory(scope, tmp_path, monkeypatch):
    """WHEN reservation commit fails THEN its held descriptor and metadata are released."""
    before, held = snapshot(scope), []
    real_open = os.open

    def tracked_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY:
            held.append(fd)
        return fd

    @contextmanager
    def refused_commit(path, **kwargs):
        with transaction(path, **kwargs) as db:
            yield db
            raise OSError("fixture reservation commit refused")

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(collections_media, "transaction", refused_commit)
    with pytest.raises(OSError, match="reservation commit refused"):
        admit(scope, tmp_path)
    assert snapshot(scope) == before
    assert list((tmp_path / "owned").iterdir()) == []
    assert len(held) == 1
    with pytest.raises(OSError):
        os.fstat(held[0])


@pytest.mark.parametrize("failure", ["input_bound", "deadline", "fsync"])
def test_copy_failures_are_bounded_charged_and_close_descriptors(scope, tmp_path, monkeypatch, failure):
    """WHEN source bounds or copy durability fail THEN charged partial bytes remain explicit."""
    held, real_open = [], os.open

    def tracked_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        held.append(fd)
        return fd

    monkeypatch.setattr(os, "open", tracked_open)
    if failure == "input_bound":
        monkeypatch.setattr(collections_owned_io, "get_config", lambda: SimpleNamespace(
            media_max_input_bytes=2, media_acquire_timeout_seconds=1))
    elif failure == "deadline":
        clock = iter((0, 2))
        monkeypatch.setattr(collections_owned_io, "time", SimpleNamespace(monotonic=lambda: next(clock)))
        monkeypatch.setattr(collections_owned_io, "get_config", lambda: SimpleNamespace(
            media_max_input_bytes=8, media_acquire_timeout_seconds=1))
    else:
        def refused_fsync(fd):
            raise OSError("fixture copy durability refused")
        monkeypatch.setattr(os, "fsync", refused_fsync)
    result = admit(scope, tmp_path)
    assert result["status"] == "partial"
    with connect(scope["index_path"]) as db:
        asset = dict(db.execute("SELECT * FROM collection_assets WHERE asset='x'").fetchone())
        assert asset["state"] == "failed" and asset["size"] == 4
        assert revision(db, "media") == 1
    target = Path(asset["path"])
    expected_reason = {"input_bound": "MEDIA_MAX_INPUT_BYTES", "deadline": "MEDIA_ACQUIRE_TIMEOUT_SECONDS",
                       "fsync": "copy durability refused"}[failure]
    assert expected_reason in asset["liability"]
    assert (target.read_bytes() if target.exists() else b"") == (b"1234" if failure == "fsync" else b"")
    assert execute(Read(action="health", **scope))["storage"]["reserved_bytes"] == 4
    for fd in held:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_root_substitution_at_relative_create_keeps_partial_bytes_inside_held_directory(scope, tmp_path, monkeypatch):
    """WHEN substitution races the last path check THEN only the held directory receives charged partial bytes."""
    root, saved, outside = (tmp_path / name for name in ("owned", "saved", "outside"))
    outside.mkdir(mode=0o700)
    real_open, swapped, directory_fds = os.open, False, []

    def substitute(path, flags, *args, **kwargs):
        nonlocal swapped
        if str(path).endswith(".blob") and "dir_fd" in kwargs:
            swapped = True
            root.rename(saved)
            root.symlink_to(outside, target_is_directory=True)
        fd = real_open(path, flags, *args, **kwargs)
        if flags & os.O_DIRECTORY:
            directory_fds.append(fd)
        return fd

    monkeypatch.setattr(os, "open", substitute)
    result = admit(scope, tmp_path)
    assert swapped and result["status"] == "partial"
    assert list(outside.iterdir()) == []
    assert [p.read_bytes() for p in saved.iterdir()] == [b"1234"]
    with connect(scope["index_path"]) as db:
        asset = dict(db.execute("SELECT * FROM collection_assets WHERE asset='x'").fetchone())
        assert asset["state"] == "failed" and asset["size"] == 4
        assert asset["liability"] and revision(db, "media") == 1
    for fd in directory_fds:
        with pytest.raises(OSError):
            os.fstat(fd)
