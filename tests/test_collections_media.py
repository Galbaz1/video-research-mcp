"""Quota refusal, deterministic eviction and owned-file cleanup integrity."""

import hashlib
import json
from pathlib import Path

import pytest

from video_research_mcp.collections import execute
from video_research_mcp.corpus_index import connect, mutate, revision
from video_research_mcp.models.collections import Configure, Create, Delete, Pin, Prune, Put, Read, Select
from video_research_mcp.models.corpus import IndexRequest


@pytest.fixture
def scope(tmp_path, monkeypatch, clean_config):
    """GIVEN one canonical database and exactly eight bytes of private media quota."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    value = {"index_path": str(tmp_path / "corpus.sqlite3"), "workspace": "edit"}
    execute(Configure(action="configure", owned_root=str(tmp_path / "owned"), quota_bytes=8, **value))
    execute(Create(action="create", collection="media", expected_revision=0, kind="media", label="Local", **value))
    return value


def current(scope, collection="media"):
    """Read the actual shared corpus revision for the next concrete mutation."""
    with connect(scope["index_path"]) as db:
        return revision(db, collection)


def admit(scope, tmp_path, name, data=b"1234", action="admit", collection="media", digest=None):
    """Admit independent fixture bytes with exact original source provenance."""
    path = tmp_path / (name + ".source")
    path.write_bytes(data)
    sha = digest or hashlib.sha256(data).hexdigest()
    evidence = {"asset_id": name, "video_id": "v-" + name, "source_revision": "r1", "media_digest": sha,
                "kind": "video" if action == "admit" else "analysis", "path": str(path),
                "sha256": sha, "size_bytes": len(data)}
    result = execute(Put(action=action, collection=collection, expected_revision=current(scope, collection), evidence=evidence, **scope))
    return result, path


def test_quota_rejects_before_copy_or_metadata_admission(scope, tmp_path, monkeypatch):
    """WHEN the quota is full THEN no copy runs and canonical metadata stays unchanged."""
    admit(scope, tmp_path, "a")
    admit(scope, tmp_path, "b")
    before = sorted((tmp_path / "owned").iterdir())
    old = current(scope)
    def unexpected_open(*args, **kwargs):
        pytest.fail("Quota overflow reached an OS file open")
    monkeypatch.setattr("video_research_mcp.collections_media.os.open", unexpected_open)
    with pytest.raises(ValueError, match="before any copy"):
        admit(scope, tmp_path, "c")
    assert sorted((tmp_path / "owned").iterdir()) == before
    assert current(scope) == old
    with connect(scope["index_path"]) as db:
        assert db.execute("SELECT count(*) FROM collection_assets").fetchone()[0] == 2
    assert execute(Read(action="health", **scope))["storage"]["reserved_bytes"] == 8


def test_lru_pins_and_read_order_survive_restart(scope, tmp_path):
    """WHEN one older item is recalled THEN pruning chooses the untouched newer item."""
    a, _ = admit(scope, tmp_path, "a")
    b, _ = admit(scope, tmp_path, "b")
    execute(Read(action="recall", limit=1, **scope))
    result = execute(Prune(action="prune", target_bytes=1, max_assets=1, **scope))
    assert result["records"] == [{"asset_id": "b", "reclaimed_bytes": 4}]
    assert result["reclaimed_bytes"] == 4
    assert Path(a["records"][0]["path"]).read_bytes() == b"1234"
    assert not Path(b["records"][0]["path"]).exists()
    execute(Pin(action="pin", collection="media", expected_revision=current(scope), asset_id="a", pinned=True, **scope))
    assert execute(Prune(action="prune", target_bytes=8, **scope))["reclaimed_bytes"] == 0
    assert execute(Read(action="health", **scope))["storage"]["reserved_bytes"] == 4


def test_active_and_collection_pin_preserve_exact_bytes(scope, tmp_path):
    """WHEN deletion or prune targets active/pinned evidence THEN bytes and index survive."""
    asset, _ = admit(scope, tmp_path, "a")
    target = Path(asset["records"][0]["path"])
    execute(Select(action="select", collection="media", **scope))
    with pytest.raises(PermissionError, match="Active or pinned"):
        execute(Delete(action="delete", collection="media", expected_revision=current(scope), **scope))
    assert execute(Prune(action="prune", target_bytes=8, **scope))["reclaimed_bytes"] == 0
    execute(Select(action="select", collection=None, **scope))
    execute(Pin(action="pin", collection="media", expected_revision=current(scope), pinned=True, **scope))
    assert execute(Prune(action="prune", target_bytes=8, **scope))["reclaimed_bytes"] == 0
    assert target.read_bytes() == b"1234"


def test_delete_canonical_index_preserves_shared_reference_and_external_original(scope, tmp_path):
    """WHEN an inactive collection is deleted THEN referenced owned bytes remain until released."""
    admitted, original = admit(scope, tmp_path, "a")
    target = admitted["records"][0]["path"]
    digest = hashlib.sha256(b"1234").hexdigest()
    execute(Create(action="create", collection="other", expected_revision=0, kind="transcript", label="Other", **scope))
    obs = {"video_id": "v-a", "observation_id": "speech", "source_revision": "r1", "media_digest": digest,
           "kind": "speech", "start_seconds": 0.25, "end_seconds": 1.75, "text": "preserved shared evidence",
           "artifact_refs": [{"artifact_id": "a", "kind": "transcript", "path": target, "sha256": digest}]}
    for name in ("media", "other"):
        mutate(IndexRequest(action="index", collection=name, index_path=scope["index_path"], expected_revision=current(scope, name), observations=[obs]))
    result = execute(Delete(action="delete", collection="media", expected_revision=current(scope), **scope))
    assert result["removed_observations"] == 1
    assert result["reclaimed_bytes"] == 0
    assert Path(target).read_bytes() == b"1234"
    with connect(scope["index_path"]) as db:
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM terms").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    later = execute(Delete(action="delete", collection="other", expected_revision=current(scope, "other"), **scope))
    assert later["reclaimed_bytes"] == 0
    reclaimed = execute(Prune(action="prune", target_bytes=8, **scope))
    assert reclaimed["reclaimed_bytes"] == 4
    assert not Path(target).exists()
    assert original.read_bytes() == b"1234"


def test_partial_cleanup_is_persistent_and_charge_retained(scope, tmp_path, monkeypatch):
    """WHEN unlink fails THEN restart retains the liability and exact unreclaimed quota charge."""
    asset, _ = admit(scope, tmp_path, "a")
    target = Path(asset["records"][0]["path"])
    def refuse(*args, **kwargs):
        raise PermissionError("fixture unlink refusal")
    monkeypatch.setattr("video_research_mcp.collections_media.os.unlink", refuse)
    result = execute(Prune(action="prune", target_bytes=8, **scope))
    assert result["reclaimed_bytes"] == 0
    assert result["status"] == "partial"
    assert result["cleanup_liabilities"][0]["reason"] == "fixture unlink refusal"
    health = execute(Read(action="health", **scope))["storage"]
    assert health["reserved_bytes"] == 4
    assert health["cleanup_liabilities"][0]["state"] == "cleanup"
    assert target.read_bytes() == b"1234"


def test_changed_digest_symlink_and_hardlink_cleanup_refusals(scope, tmp_path):
    """WHEN owned content changes THEN cleanup refuses it and preserves every outside byte."""
    asset, _ = admit(scope, tmp_path, "a")
    target = Path(asset["records"][0]["path"])
    target.write_bytes(b"evil")
    refused = execute(Prune(action="prune", target_bytes=4, **scope))
    assert refused["status"] == "partial"
    assert refused["reclaimed_bytes"] == 0
    assert target.read_bytes() == b"evil"
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    target.symlink_to(outside)
    refused = execute(Prune(action="prune", target_bytes=4, **scope))
    assert refused["cleanup_liabilities"]
    assert outside.read_bytes() == b"keep"
    target.unlink()
    target.hardlink_to(outside)
    refused = execute(Prune(action="prune", target_bytes=4, **scope))
    assert refused["reclaimed_bytes"] == 0
    assert outside.read_bytes() == b"keep"


def test_bad_admission_hash_charges_liability_without_claiming_success(scope, tmp_path):
    """WHEN the supplied digest is wrong THEN copied bytes remain an explicit charged liability."""
    result, source = admit(scope, tmp_path, "bad", digest="b" * 64)
    assert result["status"] == "partial"
    health = execute(Read(action="health", **scope))["storage"]
    assert health["reserved_bytes"] == 4
    assert health["cleanup_liabilities"][0]["state"] == "failed"
    assert source.read_bytes() == b"1234"
    assert execute(Prune(action="prune", target_bytes=4, **scope))["reclaimed_bytes"] == 0


def test_attach_analysis_is_recalled_and_never_unlinked(scope, tmp_path):
    """WHEN an analysis is attached THEN recall reports lineage and deletion preserves its original."""
    result, source = admit(scope, tmp_path, "analysis", data=b'{"result":1}', action="attach")
    assert result["status"] == "attached"
    recalled = execute(Read(action="recall", **scope))["records"][0]
    assert recalled["kind"] == "analysis"
    assert recalled["source_id"] == "v-analysis@r1"
    assert recalled["owned"] is False
    assert recalled["availability"]["state"] == "present"
    deleted = execute(Delete(action="delete", collection="media", expected_revision=current(scope), **scope))
    assert deleted["reclaimed_bytes"] == 0
    assert json.loads(source.read_bytes()) == {"result": 1}


def test_cross_workspace_source_and_outside_root_input_refused(scope, tmp_path):
    """WHEN a caller references another owned root or the local fence THEN admission fails."""
    other = {**scope, "workspace": "other"}
    execute(Configure(action="configure", owned_root=str(tmp_path / "other-owned"), quota_bytes=8, **other))
    execute(Create(action="create", collection="other", expected_revision=0, kind="media", label="Other", **other))
    asset, _ = admit(other, tmp_path, "foreign", collection="other")
    evidence = {"asset_id": "cross", "video_id": "v", "source_revision": "r", "media_digest": "a" * 64,
                "kind": "analysis", "path": asset["records"][0]["path"], "sha256": hashlib.sha256(b"1234").hexdigest(), "size_bytes": 4}
    with pytest.raises(PermissionError, match="Cross-workspace"):
        execute(Put(action="attach", collection="media", expected_revision=current(scope), evidence=evidence, **scope))
    evidence["path"] = str(tmp_path.parent / "outside.source")
    with pytest.raises(PermissionError):
        execute(Put(action="admit", collection="media", expected_revision=current(scope), evidence=evidence, **scope))


def test_stale_revision_duplicate_and_untracked_content_refuse(scope, tmp_path):
    """WHEN stale or unowned input is presented THEN no new media is admitted."""
    asset, source = admit(scope, tmp_path, "a")
    with pytest.raises(ValueError, match="already exists"):
        admit(scope, tmp_path, "a")
    evidence = {"asset_id": "stale", "video_id": "v", "source_revision": "r", "media_digest": "a" * 64,
                "kind": "video", "path": str(source), "sha256": hashlib.sha256(b"1234").hexdigest(), "size_bytes": 4}
    with pytest.raises(ValueError, match="revision conflict"):
        execute(Put(action="admit", collection="media", expected_revision=1, evidence=evidence, **scope))
    (tmp_path / "owned" / "untracked").write_bytes(b"private")
    with pytest.raises(PermissionError, match="Untracked"):
        admit(scope, tmp_path, "new")
    assert Path(asset["records"][0]["path"]).read_bytes() == b"1234"
