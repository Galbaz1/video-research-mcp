"""Quota reservations and digest-fenced cleanup of exclusively owned local copies."""

import json
import os
import stat
import uuid

from .collections_store import advance, expect, protected, tick, transaction, workspace
from .collections_owned_io import copy_owned, open_owned, verify_output
from .media_local_io import _copy_hash
from .media_snapshot import checked_path


def storage(db, name: str, *, offset: int = 0, limit: int = 20) -> dict:
    """Count reservations and unresolved cleanup against the immutable media quota."""
    scope = workspace(db, name)
    used = db.execute("SELECT coalesce(sum(size),0) FROM collection_assets WHERE workspace=? AND owned=1", (name,)).fetchone()[0]
    count = db.execute("SELECT count(*) FROM collection_assets WHERE workspace=? AND state!='ready'", (name,)).fetchone()[0]
    liabilities = [dict(row) for row in db.execute("SELECT asset,state,substr(liability,1,256) AS liability,size FROM collection_assets WHERE workspace=? AND state!='ready' ORDER BY asset LIMIT ? OFFSET ?", (name, limit, offset))]
    return {"quota_bytes": scope["quota"], "reserved_bytes": used, "owned_root": scope["root"],
            "cleanup_liabilities": liabilities, "liability_count": count,
            "next_offset": offset + len(liabilities) if offset + len(liabilities) < count else None}


def owned_root(db, name: str):
    """Refuse an altered root or untracked files instead of silently excluding bytes."""
    root = checked_path(workspace(db, name)["root"])
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise PermissionError("Owned root must remain a private directory")
    tracked = {row["path"]: row for row in db.execute("SELECT * FROM collection_assets WHERE workspace=? AND owned=1", (name,))}
    for path in root.iterdir():
        if str(path) not in tracked or path.is_symlink() or not path.is_file():
            raise PermissionError("Untracked or nonregular content in owned root")
        asset = tracked[str(path)]
        actual = path.stat()
        if actual.st_size > asset["size"]:
            raise PermissionError("Owned bytes exceed reservation; quota accounting cannot admit more media")
        if asset["state"] == "ready" and (actual.st_size, actual.st_dev, actual.st_ino) != (asset["size"], asset["device"], asset["inode"]):
            raise PermissionError("Owned bytes changed; quota accounting cannot admit more media")
    return root


def _reserve(request):
    """Reject quota, ownership and identity conflicts before admission writes any bytes."""
    evidence = request.evidence
    source = checked_path(evidence.path)
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != evidence.size_bytes:
        raise ValueError("Artifact size or regular-file identity differs")
    descriptor = None
    try:
        with transaction(request.index_path) as db:
            expect(db, request)
            root = owned_root(db, request.workspace)
            if db.execute("SELECT 1 FROM collection_assets WHERE asset=?", (evidence.asset_id,)).fetchone():
                raise ValueError("Artifact identity already exists")
            if db.execute("SELECT count(*) FROM collection_assets WHERE workspace=?", (request.workspace,)).fetchone()[0] >= 5000:
                raise ValueError("Workspace exceeds 5000 artifact identities")
            if request.action == "admit" and storage(db, request.workspace)["reserved_bytes"] + evidence.size_bytes > workspace(db, request.workspace)["quota"]:
                raise ValueError("Quota rejects admission before any copy")
            if request.action == "attach" and (source == root or root in source.parents):
                if not db.execute("SELECT 1 FROM collection_assets WHERE workspace=? AND path=? AND state='ready'", (request.workspace, str(source))).fetchone():
                    raise PermissionError("Cannot attach unregistered owned bytes")
            for row in db.execute("SELECT root FROM collection_workspaces WHERE workspace!=?", (request.workspace,)):
                other = checked_path(row[0])
                if source == other or other in source.parents:
                    raise PermissionError("Cross-workspace artifact reference refused")
            target = root / (uuid.uuid4().hex + ".blob") if request.action == "admit" else source
            if request.action == "admit":
                descriptor = open_owned(root)
            db.execute("INSERT INTO collection_assets(asset,workspace,collection,video,revision,media_digest,kind,path,digest,size,owned,used,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (evidence.asset_id, request.workspace, request.collection, evidence.video_id, evidence.source_revision, evidence.media_digest, evidence.kind, str(target), evidence.sha256, evidence.size_bytes, int(request.action == "admit"), tick(db, request.workspace), "pending"))
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise
    return source, target, descriptor


def put(request) -> dict:
    """Reserve before copying; persist every failure as a charged cleanup liability."""
    evidence = request.evidence
    source, target, descriptor = _reserve(request)
    try:
        if descriptor is not None:
            actual, identity = copy_owned(source, target, descriptor, evidence.size_bytes)
        else:
            actual = _copy_hash(source, max_bytes=evidence.size_bytes)
            identity = target.lstat()
        if actual != (evidence.sha256, evidence.size_bytes):
            raise ValueError("Artifact digest differs from supplied provenance")
        checked_path(str(target))
        with transaction(request.index_path) as db:
            expect(db, request)
            if descriptor is not None:
                verify_output(target, descriptor, identity)
            db.execute("UPDATE collection_assets SET state='ready',device=?,inode=? WHERE asset=?", (identity.st_dev, identity.st_ino, evidence.asset_id))
            value = advance(db, request.collection)
    except Exception as error:
        with transaction(request.index_path) as db:
            db.execute("UPDATE collection_assets SET state='failed',liability=? WHERE asset=?", (str(error)[:1000], evidence.asset_id))
        return {"status": "partial", "workspace": request.workspace, "collection": request.collection,
                "cleanup_liabilities": [{"asset": evidence.asset_id, "path": str(target), "reason": str(error)[:1000]}]}
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return {"status": "admitted" if request.action == "admit" else "attached", "workspace": request.workspace,
            "collection": request.collection, "index_revision": value,
            "records": [{"asset_id": evidence.asset_id, "path": str(target), "sha256": evidence.sha256, "size_bytes": evidence.size_bytes}]}


def referenced(db, asset) -> bool:
    """Protect every retained corpus revision and explicit artifact link across the index."""
    rows = db.execute("SELECT payload FROM observations LIMIT 5001").fetchall()
    if len(rows) > 5000:
        raise ValueError("Cleanup reference scan exceeds 5000 retained observations")
    for row in rows:
        payload = json.loads(row[0])
        if payload["media_digest"] == asset["digest"]:
            return True
        for ref in payload["artifact_refs"]:
            if str(checked_path(ref["path"])) == asset["path"]:
                return True
    return bool(db.execute("SELECT 1 FROM collection_assets WHERE asset!=? AND path=? AND state='ready'", (asset["asset"], asset["path"])).fetchone())


def removable(db, asset) -> bool:
    """Only unpinned, inactive, unreferenced ready owned artifacts may be reclaimed."""
    return bool(asset["owned"] and asset["state"] in ("ready", "cleanup") and not asset["pinned"]
                and not protected(db, asset["collection"]) and not referenced(db, asset))


def _unlink(db, asset) -> int:
    """Verify recorded inode and full digest, then unlink relative to the owned directory."""
    root = owned_root(db, asset["workspace"])
    path = checked_path(asset["path"])
    if path.parent != root:
        raise PermissionError("Cleanup path is outside the exact owned root")
    if not path.exists():
        raise FileNotFoundError("Cleanup outcome is unknown; owned bytes are absent")
    before = path.lstat()
    if before.st_nlink != 1 or (before.st_dev, before.st_ino) != (asset["device"], asset["inode"]):
        raise PermissionError("Owned artifact inode or hard-link identity changed")
    if _copy_hash(path, max_bytes=asset["size"]) != (asset["digest"], asset["size"]):
        raise ValueError("Owned artifact digest changed; cleanup refused")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        actual = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        current_root = checked_path(str(root)).stat()
        opened_root = os.fstat(fd)
        if (current_root.st_dev, current_root.st_ino) != (opened_root.st_dev, opened_root.st_ino):
            raise PermissionError("Owned root changed during cleanup")
        if (actual.st_dev, actual.st_ino, actual.st_size, actual.st_mtime_ns, actual.st_ctime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            raise PermissionError("Owned artifact changed during cleanup")
        os.unlink(path.name, dir_fd=fd)
        os.fsync(fd)
    finally:
        os.close(fd)
    return asset["size"]


def cleanup(index_path: str, name: str, assets: list[str]) -> dict:
    """Journal before filesystem effects and retain charged liabilities after partial cleanup."""
    result = {"reclaimed_bytes": 0, "cleanup_liabilities": [], "records": []}
    for identity in assets:
        with transaction(index_path) as db:
            asset = db.execute("SELECT * FROM collection_assets WHERE asset=? AND workspace=?", (identity, name)).fetchone()
            if asset is None:
                continue
            try:
                allowed = removable(db, asset)
            except (OSError, ValueError) as error:
                result["cleanup_liabilities"].append({"asset_id": identity, "reason": str(error)[:1000]})
                db.execute("UPDATE collection_assets SET state='cleanup',liability=? WHERE asset=?", (str(error)[:1000], identity))
                continue
            if not allowed:
                result["records"].append({"asset_id": identity, "state": "preserved", "reclaimed_bytes": 0})
                continue
            db.execute("UPDATE collection_assets SET state='cleanup',liability='unlink outcome pending' WHERE asset=?", (identity,))
            intent = {key: asset[key] for key in ("workspace", "collection", "path", "digest", "size", "device", "inode", "video", "revision", "media_digest", "kind", "owned")}
        with transaction(index_path) as db:
            asset = db.execute("SELECT * FROM collection_assets WHERE asset=? AND workspace=?", (identity, name)).fetchone()
            if asset is None or any(asset[key] != value for key, value in intent.items()):
                result["records"].append({"asset_id": identity, "state": "stale_cleanup_skipped", "reclaimed_bytes": 0})
                continue
            try:
                if not removable(db, asset):
                    raise PermissionError("Artifact became protected before cleanup")
                size = _unlink(db, asset)
                db.execute("DELETE FROM collection_assets WHERE asset=?", (identity,))
                advance(db, asset["collection"])
                result["reclaimed_bytes"] += size
                result["records"].append({"asset_id": identity, "reclaimed_bytes": size})
            except (OSError, ValueError) as error:
                reason = str(error)[:1000]
                db.execute("UPDATE collection_assets SET liability=? WHERE asset=?", (reason, identity))
                result["cleanup_liabilities"].append({"asset_id": identity, "reason": reason})
    return result
