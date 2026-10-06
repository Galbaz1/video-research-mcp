"""Bounded prior-work recall over canonical observations and local artifact metadata."""

import json
import os

from .collections_media import storage
from .collections_store import collection, tick, transaction, workspace
from .corpus_index import canonical
from .media_local_io import _open_regular
from .media_snapshot import checked_path


def availability(path: str, size: int | None = None) -> dict:
    """Report regular-file presence separately from unverified current content integrity."""
    try:
        target = checked_path(path)
        with _open_regular(target) as reader:
            actual = os.fstat(reader.fileno()).st_size
        return {"state": "present" if size is None or size == actual else "size_changed",
                "size_bytes": actual, "digest_verification": "not_rehashed_on_recall"}
    except FileNotFoundError:
        return {"state": "missing"}
    except (OSError, ValueError) as error:
        return {"state": "refused", "reason": str(error)[:256]}


def _collections(db, request):
    """List exact canonical revisions and persisted collection membership counts."""
    return [dict(row) for row in db.execute("""SELECT c.name AS collection,c.kind,c.label,c.pinned,i.revision AS index_revision,
        (SELECT count(*) FROM observations o WHERE o.collection=c.name) AS observations,
        (SELECT count(*) FROM collection_assets a WHERE a.collection=c.name) AS assets
        FROM collection_catalog c JOIN collections i ON i.name=c.name
        WHERE c.workspace=? AND c.retired=0 ORDER BY c.name LIMIT ? OFFSET ?""",
        (request.workspace, request.limit + 1, request.offset))]


def _evidence(db, request, focus):
    """Page both existing observations and linked assets without duplicating their contents."""
    rows = db.execute("""SELECT 'observation' AS type,printf('%020d',o.id) AS identity,o.collection,o.payload,
        (s.revision=o.revision AND s.digest=o.digest) AS current
        FROM observations o JOIN collection_catalog c ON c.name=o.collection
        LEFT JOIN sources s ON s.collection=o.collection AND s.video=o.video
        WHERE c.workspace=? AND c.retired=0 AND (? IS NULL OR c.name=?)
        UNION ALL SELECT 'asset',a.asset,a.collection,NULL,1 FROM collection_assets a
        JOIN collection_catalog c ON c.name=a.collection
        WHERE c.workspace=? AND c.retired=0 AND (? IS NULL OR c.name=?)
        ORDER BY collection,type,identity LIMIT ? OFFSET ?""",
        (request.workspace, focus, focus, request.workspace, focus, focus, request.limit + 1, request.offset)).fetchall()
    result = []
    for row in rows:
        if row["type"] == "observation":
            value = json.loads(row["payload"])
            value.update(type="observation", collection=row["collection"], current=bool(row["current"]),
                         source_id=value["video_id"] + "@" + value["source_revision"])
            for ref in value["artifact_refs"]:
                ref["availability"] = availability(ref["path"])
        else:
            asset = dict(db.execute("SELECT * FROM collection_assets WHERE asset=?", (row["identity"],)).fetchone())
            value = {"type": "asset", "asset_id": asset["asset"], "collection": asset["collection"],
                     "video_id": asset["video"], "source_revision": asset["revision"], "media_digest": asset["media_digest"],
                     "source_id": asset["video"] + "@" + asset["revision"], "path": asset["path"],
                     "sha256": asset["digest"], "kind": asset["kind"], "owned": bool(asset["owned"]),
                     "pinned": bool(asset["pinned"]), "admission_state": asset["state"],
                     "availability": availability(asset["path"], asset["size"])}
        result.append(value)
    return result


def read(request) -> dict:
    """Recall without providers, report quota liabilities, or enumerate named collections."""
    with transaction(request.index_path) as db:
        scope = workspace(db, request.workspace)
        focus = request.collection if request.collection is not None else scope["active"]
        if focus is not None:
            collection(db, request, focus)
        result = {"status": "recalled" if request.action == "recall" else "listed" if request.action == "list" else "health",
                  "workspace": request.workspace, "active_collection": scope["active"]}
        if request.action == "health":
            result["storage"] = storage(db, request.workspace, offset=request.offset, limit=request.limit)
            if len(canonical(result).encode()) + 512 > request.output_bytes:
                raise ValueError("Health page exceeds output_bytes; reduce limit")
            return result
        records = _evidence(db, request, focus) if request.action == "recall" else _collections(db, request)
        chosen = []
        for item in records[:request.limit]:
            if len(canonical({**result, "records": chosen + [item]}).encode()) + 512 > request.output_bytes:
                if not chosen:
                    raise ValueError("First recall record exceeds output_bytes; increase the finite budget")
                break
            chosen.append(item)
        result.update(records=chosen, next_offset=request.offset + len(chosen) if len(records) > len(chosen) else None)
        if request.action == "recall":
            used = tick(db, request.workspace)
            for item in chosen:
                if item["type"] == "asset":
                    db.execute("UPDATE collection_assets SET used=? WHERE asset=?", (used, item["asset_id"]))
        return result
