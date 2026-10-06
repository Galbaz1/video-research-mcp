"""Concrete collection operations on the canonical corpus index; no provider execution."""

from .collections_media import cleanup, put, referenced, removable
from .collections_recall import read
from .collections_store import advance, expect, metadata, protected, transaction, workspace
from .corpus_index import revision


def delete(request) -> dict:
    """Retire inactive unpinned evidence transactionally before attempting owned-file cleanup."""
    with transaction(request.index_path) as db:
        expect(db, request)
        if protected(db, request.collection):
            raise PermissionError("Active or pinned collection cannot be deleted")
        count = 0
        if request.asset_id is not None:
            asset = db.execute("SELECT * FROM collection_assets WHERE asset=? AND collection=? AND workspace=?", (request.asset_id, request.collection, request.workspace)).fetchone()
            if asset is None or asset["pinned"] or referenced(db, asset):
                raise PermissionError("Artifact absent, pinned or referenced")
            if not asset["owned"]:
                db.execute("DELETE FROM collection_assets WHERE asset=?", (request.asset_id,))
                candidates = []
            elif removable(db, asset):
                candidates = [request.asset_id]
            else:
                raise PermissionError("Artifact has unresolved admission state")
        else:
            if db.execute("SELECT 1 FROM collection_assets WHERE collection=? AND pinned=1", (request.collection,)).fetchone():
                raise PermissionError("Pinned evidence prevents collection deletion")
            if db.execute("SELECT count(*) FROM collection_assets WHERE collection=? AND owned=1", (request.collection,)).fetchone()[0] > 100:
                raise ValueError("Delete exceeds 100 owned artifacts; prune first")
            count = db.execute("SELECT count(*) FROM observations WHERE collection=?", (request.collection,)).fetchone()[0]
            db.execute("DELETE FROM vectors WHERE id IN (SELECT id FROM observations WHERE collection=?)", (request.collection,))
            db.execute("DELETE FROM terms WHERE id IN (SELECT id FROM observations WHERE collection=?)", (request.collection,))
            db.execute("DELETE FROM observations WHERE collection=?", (request.collection,))
            db.execute("DELETE FROM sources WHERE collection=?", (request.collection,))
            db.execute("DELETE FROM collection_assets WHERE collection=? AND owned=0", (request.collection,))
            db.execute("UPDATE collection_catalog SET retired=1 WHERE name=?", (request.collection,))
            candidates = [row[0] for row in db.execute("SELECT asset FROM collection_assets WHERE collection=? AND owned=1 ORDER BY used,asset LIMIT 100", (request.collection,))]
        advance(db, request.collection)
    result = cleanup(request.index_path, request.workspace, candidates)
    with transaction(request.index_path) as db:
        value = revision(db, request.collection)
    return {**result, "status": "partial" if result["cleanup_liabilities"] else "deleted",
            "workspace": request.workspace, "collection": request.collection,
            "index_revision": value, "removed_observations": count}


def prune(request) -> dict:
    """Choose a finite deterministic LRU prefix; never evict referenced or pinned evidence."""
    with transaction(request.index_path) as db:
        workspace(db, request.workspace)
        rows = db.execute("SELECT * FROM collection_assets WHERE workspace=? AND owned=1 ORDER BY used,asset LIMIT 5001", (request.workspace,)).fetchall()
        if len(rows) > 5000:
            raise ValueError("Prune exceeds 5000 retained artifact identities")
        candidates, planned = [], 0
        for row in rows:
            if removable(db, row):
                candidates.append(row["asset"])
                planned += row["size"]
                if planned >= request.target_bytes or len(candidates) >= request.max_assets:
                    break
    result = cleanup(request.index_path, request.workspace, candidates)
    return {**result, "status": "partial" if result["cleanup_liabilities"] else "pruned", "workspace": request.workspace}


def execute(request) -> dict:
    """Dispatch the finite typed operations used by the collections MCP tool."""
    if request.action in ("configure", "create", "select", "pin"):
        return metadata(request)
    if request.action in ("attach", "admit"):
        return put(request)
    if request.action == "delete":
        return delete(request)
    if request.action == "prune":
        return prune(request)
    return read(request)
