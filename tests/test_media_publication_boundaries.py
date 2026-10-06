"""Mocked publication and filter boundaries; no native process or database runs."""

import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, sentinel

import pytest

from video_research_mcp import footage_edit_native as native
from video_research_mcp import media_assets as assets


@pytest.mark.parametrize("included", [True, False])
@pytest.mark.parametrize("duration", [
    "1[discard];[discard]anullsink;amovie=/other/audio.wav[injected]",
    "0.2", True, None, 0, -1, 60.01, float("nan"), float("inf"), -float("inf"), 10**400,
])
def test_assembly_rejects_untrusted_duration_before_binary_lookup(monkeypatch, tmp_path, duration, included):
    """GIVEN untrusted duration WHEN assembling THEN refuse before resolving any executable."""
    binary = Mock(return_value="/unexecuted/ffmpeg")
    monkeypatch.setattr(native, "binary", binary)
    scenes = [{"duration_seconds": duration, "audio": {"included": included}}]
    with pytest.raises(ValueError, match="Prepared scene duration"):
        native.assemble_command(scenes, tmp_path, tmp_path / "final.mp4")
    binary.assert_not_called()


@pytest.mark.parametrize("included", [True, False])
def test_assembly_keeps_bounded_numeric_durations_in_file_only_command(monkeypatch, tmp_path, included):
    """GIVEN bounded numeric scenes WHEN constructing argv THEN preserve exact trims and mute policy."""
    monkeypatch.setattr(native, "binary", lambda name: "/unexecuted/" + name)
    scenes = [{"duration_seconds": duration, "audio": {"included": included}} for duration in [0.2, 60]]
    command = native.assemble_command(scenes, tmp_path, tmp_path / "final.mp4")
    filters = command[command.index("-filter_complex") + 1]
    assert command.count("-protocol_whitelist") == 2
    assert all(command[i + 1] == "file" for i, value in enumerate(command) if value == "-protocol_whitelist")
    if included:
        assert "atrim=duration=0.2,asetpts=PTS-STARTPTS[a0]" in filters
        assert "atrim=duration=60,asetpts=PTS-STARTPTS[a1]" in filters
        assert "concat=n=2:v=1:a=1[v][a]" in filters
        assert "-an" not in command
    else:
        assert "atrim=" not in filters
        assert "concat=n=2:v=1:a=0[v]" in filters
        assert "-an" in command


@pytest.fixture
def publication(monkeypatch, tmp_path):
    """Bypass catalog initialization and replace transaction, link and deletion boundaries."""
    catalog = object.__new__(assets.AssetCatalog)
    catalog.objects = tmp_path / "objects"
    digest, size = "a" * 64, 9
    target = catalog.objects / (digest + ".mp4")
    db = Mock()
    monkeypatch.setattr(catalog, "_connection", lambda *, commit_state=None: nullcontext(db))
    monkeypatch.setattr(assets, "_select_row", lambda *args: None)
    monkeypatch.setattr(assets, "encode_receipts", lambda receipts: "[]")
    monkeypatch.setattr(assets.sqlite3, "connect", Mock(side_effect=AssertionError("Real DB forbidden")))
    link = Mock()
    unlink = Mock()
    monkeypatch.setattr(assets.os, "link", link)
    monkeypatch.setattr(Path, "unlink", unlink)
    return catalog, db, target, digest, size, link, unlink


@pytest.mark.parametrize("primary_type", [RuntimeError, TimeoutError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_stage", ["hash", "unlink"])
def test_publication_preserves_primary_when_cleanup_fails(monkeypatch, tmp_path, publication, primary_type, cleanup_stage):
    """GIVEN post-link failure WHEN rollback also fails THEN retain primary identity and cleanup liability."""
    catalog, db, target, digest, size, link, unlink = publication
    primary = primary_type("primary asset failure")
    cleanup = PermissionError("private cleanup diagnostic")
    db.execute.side_effect = primary
    copy_hash = Mock(return_value=(digest, size))
    if cleanup_stage == "hash":
        copy_hash.side_effect = cleanup
    else:
        unlink.side_effect = cleanup
    monkeypatch.setattr(assets, "_copy_hash", copy_hash)
    staged = tmp_path / "staged.mp4"
    with pytest.raises(primary_type) as caught:
        catalog._publish(staged, digest, size, ".mp4", {"alias_sha256": "b" * 64}, None)
    assert caught.value is primary
    link.assert_called_once_with(staged, target)
    copy_hash.assert_called_once_with(target)
    if cleanup_stage == "hash":
        unlink.assert_not_called()
    else:
        unlink.assert_called_once_with()
    assert len(primary.__notes__) == 1
    assert "PermissionError" in primary.__notes__[0]
    assert "cleanup unverified" in primary.__notes__[0]
    assert "private cleanup diagnostic" not in primary.__notes__[0]


@pytest.mark.parametrize("mismatch", [None, "digest", "size"])
def test_publication_rollback_requires_original_digest_and_size(monkeypatch, tmp_path, publication, mismatch):
    """GIVEN failed publication WHEN rollback succeeds THEN delete only the original exact byte identity."""
    catalog, db, target, digest, size, _, unlink = publication
    primary = RuntimeError("primary asset failure")
    db.execute.side_effect = primary
    identity = ("c" * 64 if mismatch == "digest" else digest, size + 1 if mismatch == "size" else size)
    copy_hash = Mock(return_value=identity)
    monkeypatch.setattr(assets, "_copy_hash", copy_hash)
    with pytest.raises(RuntimeError) as caught:
        catalog._publish(tmp_path / "staged.mp4", digest, size, ".mp4", {"alias_sha256": "b" * 64}, None)
    assert caught.value is primary
    copy_hash.assert_called_once_with(target)
    if mismatch is None:
        unlink.assert_called_once_with()
    else:
        unlink.assert_not_called()
    assert not getattr(primary, "__notes__", [])


@pytest.fixture
def transaction(monkeypatch):
    """Keep the real transaction context above fake DB and path operations."""
    catalog = object.__new__(assets.AssetCatalog)
    path = Mock()
    path.is_symlink.return_value = False
    path.exists.return_value = False
    catalog.database = path
    monkeypatch.setattr(catalog, "_directories", Mock())
    monkeypatch.setattr(assets, "Path", lambda value: path)
    fake_os = SimpleNamespace(
        O_CREAT=1, O_RDWR=2, O_NOFOLLOW=4,
        open=Mock(return_value=7), fchmod=Mock(), close=Mock(),
    )
    db = Mock()
    fake_sqlite = SimpleNamespace(connect=Mock(return_value=db), Row=sentinel.row_factory)
    monkeypatch.setattr(assets, "os", fake_os)
    monkeypatch.setattr(assets, "sqlite3", fake_sqlite)
    return catalog, db


@pytest.mark.parametrize("primary_type", [RuntimeError, TimeoutError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_stage", ["rollback", "close", "both"])
def test_transaction_cleanup_preserves_primary(transaction, primary_type, cleanup_stage):
    """GIVEN primary failure WHEN actual transaction cleanup fails THEN preserve identity."""
    catalog, db = transaction
    primary = primary_type("primary transaction failure")
    if cleanup_stage in {"rollback", "both"}:
        db.rollback.side_effect = PermissionError("private rollback diagnostic")
    if cleanup_stage in {"close", "both"}:
        db.close.side_effect = PermissionError("private close diagnostic")
    with pytest.raises(primary_type) as caught:
        with catalog._connection():
            raise primary
    assert caught.value is primary
    db.rollback.assert_called_once_with()
    db.close.assert_called_once_with()
    db.commit.assert_not_called()
    assert len(primary.__notes__) == (2 if cleanup_stage == "both" else 1)
    assert all(len(note) <= 180 for note in primary.__notes__)
    assert all("PermissionError" in note and "cleanup unverified" in note for note in primary.__notes__)
    assert all("private" not in note for note in primary.__notes__)


@pytest.mark.parametrize("failure_stage", ["begin", "body", "commit"])
@pytest.mark.parametrize("primary_type", [RuntimeError, TimeoutError, asyncio.CancelledError])
def test_transaction_primary_without_cleanup_failure(transaction, primary_type, failure_stage):
    """GIVEN begin/body/commit failure WHEN cleanup succeeds THEN keep the primary unchanged."""
    catalog, db = transaction
    primary = primary_type("primary transaction failure")
    if failure_stage == "begin":
        db.execute.side_effect = primary
    elif failure_stage == "commit":
        db.commit.side_effect = primary
    with pytest.raises(primary_type) as caught:
        with catalog._connection():
            if failure_stage == "body":
                raise primary
    assert caught.value is primary
    db.rollback.assert_called_once_with()
    db.close.assert_called_once_with()
    assert not getattr(primary, "__notes__", [])


def test_transaction_success_commits_and_closes(transaction):
    """GIVEN no primary failure THEN commit and close exactly once without rollback."""
    catalog, db = transaction
    with catalog._connection() as yielded:
        assert yielded is db
    db.execute.assert_called_once_with("BEGIN IMMEDIATE")
    db.commit.assert_called_once_with()
    db.close.assert_called_once_with()
    db.rollback.assert_not_called()
    assert db.row_factory is sentinel.row_factory


def test_transaction_normal_close_failure_surfaces(transaction):
    """GIVEN successful commit WHEN close fails THEN expose that actual close failure."""
    catalog, db = transaction
    failure = PermissionError("normal close failed")
    db.close.side_effect = failure
    with pytest.raises(PermissionError) as caught:
        with catalog._connection():
            pass
    assert caught.value is failure
    db.commit.assert_called_once_with()
    db.close.assert_called_once_with()
    db.rollback.assert_not_called()


@pytest.mark.parametrize("primary_type", [RuntimeError, TimeoutError, asyncio.CancelledError])
@pytest.mark.parametrize("failure_stage", ["commit", "close"])
def test_publication_transaction_keeps_file_only_after_confirmed_commit(
    monkeypatch, tmp_path, transaction, primary_type, failure_stage,
):
    """GIVEN a commit/close fault THEN preserve identity and keep only committed bytes."""
    catalog, db = transaction
    catalog.objects = tmp_path / "objects"
    digest, size = "a" * 64, 9
    target = catalog.objects / (digest + ".mp4")
    staged = tmp_path / "staged.mp4"
    primary = primary_type("private transaction failure")
    state = {"pending": None, "committed": None, "owned": False}

    def execute(sql, parameters=()):
        if sql.startswith("INSERT"):
            state["pending"] = dict(zip(("digest", "suffix", "size", "receipts"), parameters))
        return SimpleNamespace(fetchone=lambda: state["pending"])

    def commit():
        if failure_stage == "commit":
            raise primary
        state["committed"] = state["pending"].copy()

    db.execute.side_effect = execute
    db.commit.side_effect = commit
    db.rollback.side_effect = lambda: state.update(pending=None)
    if failure_stage == "close":
        db.close.side_effect = primary
    link = Mock(side_effect=lambda *args: state.update(owned=True))
    unlink = Mock(side_effect=lambda: state.update(owned=False))
    monkeypatch.setattr(assets.os, "link", link, raising=False)
    monkeypatch.setattr(Path, "unlink", unlink)
    copy_hash = Mock(return_value=(digest, size))
    monkeypatch.setattr(assets, "_copy_hash", copy_hash)
    receipt = assets.make_receipt("invented-owned-source", {"method": "fake_transaction"})

    with pytest.raises(primary_type) as caught:
        catalog._publish(staged, digest, size, ".mp4", receipt, None)
    assert caught.value is primary
    link.assert_called_once_with(staged, target)
    db.commit.assert_called_once_with()
    db.close.assert_called_once_with()
    if failure_stage == "close":
        assert state["owned"] is True
        assert state["committed"] == {
            "digest": digest, "suffix": ".mp4", "size": size,
            "receipts": assets.encode_receipts([receipt]),
        }
        unlink.assert_not_called()
        db.rollback.assert_not_called()
        copy_hash.assert_called_once_with(target, max_bytes=None)
    else:
        assert state["owned"] is False
        assert state["pending"] is None and state["committed"] is None
        unlink.assert_called_once_with()
        db.rollback.assert_called_once_with()
