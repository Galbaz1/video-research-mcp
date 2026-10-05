"""Collection metadata transactions in the existing canonical corpus database."""

from contextlib import contextmanager

from .corpus_index import MAX_INDEX_BYTES, connect, revision
from .media_snapshot import checked_path

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS collection_workspaces (workspace TEXT PRIMARY KEY, root TEXT UNIQUE, quota INTEGER, active TEXT, clock INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS collection_catalog (name TEXT PRIMARY KEY REFERENCES collections(name), workspace TEXT NOT NULL REFERENCES collection_workspaces(workspace), kind TEXT, label TEXT, pinned INTEGER NOT NULL DEFAULT 0, retired INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS collection_assets (asset TEXT PRIMARY KEY, workspace TEXT NOT NULL, collection TEXT NOT NULL, video TEXT, revision TEXT, media_digest TEXT, kind TEXT, path TEXT, digest TEXT, size INTEGER, owned INTEGER, pinned INTEGER NOT NULL DEFAULT 0, used INTEGER, state TEXT, liability TEXT, device INTEGER, inode INTEGER)",
)


@contextmanager
def transaction(path: str, *, initialize: bool = False):
    """Fence the path and join the canonical application ID and write lock."""
    checked_path(path)
    with connect(path, mode="rwc" if initialize else "rw") as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if initialize:
                for statement in _SCHEMA:
                    db.execute(statement)
            yield db
            size = db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]
            if size > MAX_INDEX_BYTES:
                raise ValueError("Canonical index exceeds 64 MiB")
            db.commit()
        except Exception:
            db.rollback()
            raise


def workspace(db, name: str):
    """Require a configured explicit workspace context."""
    row = db.execute("SELECT * FROM collection_workspaces WHERE workspace=?", (name,)).fetchone()
    if row is None:
        raise ValueError("Workspace is not configured")
    return row


def collection(db, scope, name: str):
    """Refuse another workspace's collection, including retired identities."""
    workspace(db, scope.workspace)
    row = db.execute("SELECT * FROM collection_catalog WHERE name=?", (name,)).fetchone()
    if row is None or row["workspace"] != scope.workspace or row["retired"]:
        raise PermissionError("Collection is absent or outside this workspace context")
    return row


def expect(db, request):
    """Require the same optimistic revision used by canonical corpus mutations."""
    row = collection(db, request, request.collection)
    actual = revision(db, request.collection)
    if actual != request.expected_revision:
        raise ValueError(f"Index revision conflict: current {actual}, expected {request.expected_revision}")
    return row


def advance(db, name: str) -> int:
    """Advance the shared canonical revision without resetting a retired identity."""
    value = revision(db, name) + 1
    db.execute("INSERT OR REPLACE INTO collections VALUES(?,?)", (name, value))
    return value


def tick(db, name: str) -> int:
    """Use a persisted logical clock for deterministic LRU ordering across restart."""
    db.execute("UPDATE collection_workspaces SET clock=clock+1 WHERE workspace=?", (name,))
    return workspace(db, name)["clock"]


def protected(db, name: str) -> bool:
    """Active and pinned collections protect their media and indexed evidence."""
    row = db.execute("SELECT pinned FROM collection_catalog WHERE name=? AND retired=0", (name,)).fetchone()
    active = db.execute("SELECT 1 FROM collection_workspaces WHERE active=?", (name,)).fetchone()
    return bool(active or (row and row[0]))


def metadata(request) -> dict:
    """Configure, create, select or pin with one canonical metadata transaction."""
    with transaction(request.index_path, initialize=request.action == "configure") as db:
        if request.action == "configure":
            root = checked_path(request.owned_root)
            index = checked_path(request.index_path)
            if root == index or root in index.parents:
                raise PermissionError("Owned root may not contain the canonical database")
            old = db.execute("SELECT * FROM collection_workspaces WHERE workspace=?", (request.workspace,)).fetchone()
            if old:
                if (old["root"], old["quota"]) != (str(root), request.quota_bytes):
                    raise ValueError("Workspace root and quota are immutable")
            else:
                for row in db.execute("SELECT root FROM collection_workspaces"):
                    other = checked_path(row[0])
                    if root == other or root in other.parents or other in root.parents:
                        raise PermissionError("Owned roots may not overlap")
                if root.exists() and (not root.is_dir() or any(root.iterdir())):
                    raise PermissionError("Enroll only an empty owned root")
                root.mkdir(mode=0o700, parents=True, exist_ok=True)
                if root.stat().st_mode & 0o077:
                    raise PermissionError("Owned root must be private (0700)")
                db.execute("INSERT INTO collection_workspaces(workspace,root,quota) VALUES(?,?,?)", (request.workspace, str(root), request.quota_bytes))
            return {"status": "configured", "workspace": request.workspace}
        workspace(db, request.workspace)
        return _edit(db, request)


def _edit(db, request) -> dict:
    """Apply the concrete selection, naming and pin operations."""
    result = {"workspace": request.workspace}
    if request.action == "create":
        if db.execute("SELECT 1 FROM collection_catalog WHERE name=?", (request.collection,)).fetchone():
            raise ValueError("Collection identity already enrolled")
        if revision(db, request.collection) != request.expected_revision:
            raise ValueError("Index revision conflict")
        count = db.execute("SELECT count(*) FROM collection_catalog WHERE workspace=?", (request.workspace,)).fetchone()[0]
        if count >= 100:
            raise ValueError("Workspace exceeds 100 retained collection identities")
        value = advance(db, request.collection)
        db.execute("INSERT INTO collection_catalog(name,workspace,kind,label) VALUES(?,?,?,?)", (request.collection, request.workspace, request.kind, request.label))
        result.update(status="created", collection=request.collection, index_revision=value)
    elif request.action == "select":
        if request.collection is not None:
            collection(db, request, request.collection)
            used = tick(db, request.workspace)
            db.execute("UPDATE collection_assets SET used=? WHERE collection=?", (used, request.collection))
        db.execute("UPDATE collection_workspaces SET active=? WHERE workspace=?", (request.collection, request.workspace))
        result.update(status="selected" if request.collection else "cleared", active_collection=request.collection)
    elif request.action == "pin":
        expect(db, request)
        if request.asset_id is None:
            db.execute("UPDATE collection_catalog SET pinned=? WHERE name=?", (request.pinned, request.collection))
        else:
            row = db.execute("UPDATE collection_assets SET pinned=? WHERE asset=? AND collection=? AND workspace=?", (request.pinned, request.asset_id, request.collection, request.workspace))
            if row.rowcount != 1:
                raise ValueError("Artifact is absent from this collection")
        result.update(status="pinned", collection=request.collection, index_revision=advance(db, request.collection))
    return result
