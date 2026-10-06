"""Deterministic local notebooks: scoped notes over exact canonical corpus observations.

Notebook revisions live in the existing canonical corpus SQLite index (same application ID,
filesystem fence and 64 MiB bound). No model, provider, network or generation backend is used.
"""

from contextlib import contextmanager
import hashlib
from html import escape

from .collections_store import collection, workspace
from .corpus_index import MAX_INDEX_BYTES, canonical, connect
from .media_snapshot import checked_path
from .models.corpus import Observation
from .models.notebooks import AddNote, Export, Import, NotebookDocument, Query, Status

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS notebook_revisions (workspace TEXT NOT NULL, notebook TEXT NOT NULL, revision INTEGER NOT NULL,"
    " digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(workspace,notebook,revision))",
    "CREATE TRIGGER IF NOT EXISTS notebook_history_no_update BEFORE UPDATE ON notebook_revisions BEGIN SELECT RAISE(ABORT,'Notebook history is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS notebook_history_no_delete BEFORE DELETE ON notebook_revisions BEGIN SELECT RAISE(ABORT,'Notebook history is immutable'); END",
)
MAX_OUTPUT = 65536


@contextmanager
def database(path: str, *, write: bool = False):
    """Join the canonical index transaction; create notebook tables only when writing."""
    checked_path(path)
    with connect(path, mode="rw" if write else "ro") as db:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            if write:
                for statement in _SCHEMA:
                    db.execute(statement)
            yield db
            if write and db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0] > MAX_INDEX_BYTES:
                raise ValueError("Canonical index exceeds 64 MiB")
            db.commit()
        except Exception:
            db.rollback()
            raise


def _current(db, scope, notebook: str) -> tuple[dict, str] | None:
    """Latest immutable revision of this workspace's notebook, integrity-checked."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='notebook_revisions'").fetchone():
        return None
    row = db.execute("SELECT * FROM notebook_revisions WHERE workspace=? AND notebook=? ORDER BY revision DESC LIMIT 1",
                     (scope.workspace, notebook)).fetchone()
    if row is None:
        return None
    if hashlib.sha256(row["payload"].encode()).hexdigest() != row["digest"]:
        raise ValueError("Notebook payload digest mismatch")
    value = NotebookDocument.model_validate_json(row["payload"]).model_dump(mode="json")
    if (value["notebook_id"], value["revision"]) != (row["notebook"], row["revision"]):
        raise ValueError("Notebook revision identity mismatch")
    return value, row["digest"]


def _required(db, scope, notebook: str) -> dict:
    found = _current(db, scope, notebook)
    if found is None:
        raise ValueError("Notebook is absent in this workspace")
    for name in found[0]["collections"]:
        collection(db, scope, name)
    return found[0]


def _passage(db, citation: dict) -> dict:
    """Bind a citation to the exact stored observation version and return its supporting passage."""
    row = db.execute("SELECT * FROM observations WHERE collection=? AND observation=? AND revision=?",
                     (citation["collection"], citation["observation_id"], citation["source_revision"])).fetchone()
    if row is None:
        raise ValueError("Cited observation version is absent")
    obs = Observation.model_validate_json(row["payload"])
    identity = (obs.observation_id, obs.source_revision, obs.video_id, obs.media_digest)
    if identity != (row["observation"], row["revision"], row["video"], row["digest"]) or obs.media_digest != citation["media_digest"]:
        raise ValueError("Cited observation identity or digest mismatch")
    return {**citation, "source_id": obs.video_id + "@" + obs.source_revision, "kind": obs.kind,
            "start_seconds": obs.start_seconds, "end_seconds": obs.end_seconds, "text": obs.text,
            "observation_sha256": hashlib.sha256(row["payload"].encode()).hexdigest()}


def _save(db, scope, document: NotebookDocument) -> str:
    payload = canonical(document.model_dump(mode="json"))
    if len(payload.encode()) > 262144:
        raise ValueError("Notebook revision exceeds 256 KiB")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db.execute("INSERT INTO notebook_revisions VALUES(?,?,?,?,?)", (scope.workspace, document.notebook_id, document.revision, digest, payload))
    return digest


def bounded(result: dict) -> dict:
    if len(canonical(result).encode()) > MAX_OUTPUT:
        raise ValueError("Notebook output exceeds 64 KiB; narrow the query or notebook")
    return result


def import_document(request: Import) -> dict:
    """Store an exact document revision; identical re-import is unchanged, older or divergent ones refuse."""
    document = request.document
    with database(request.index_path, write=True) as db:
        workspace(db, request.workspace)
        for name in document.collections:
            collection(db, request, name)
        for note in document.notes:
            for citation in note.citations:
                _passage(db, citation.model_dump(mode="json"))
        found = _current(db, request, document.notebook_id)
        payload_digest = hashlib.sha256(canonical(document.model_dump(mode="json")).encode()).hexdigest()
        if found and found[0]["revision"] == document.revision and found[1] == payload_digest:
            status, digest = "unchanged", found[1]
        elif found and found[0]["revision"] >= document.revision:
            raise ValueError("Notebook revision conflict: import must be identical or newer")
        else:
            status, digest = "imported", _save(db, request, document)
    return {"status": status, "workspace": request.workspace, "notebook_id": document.notebook_id,
            "revision": document.revision, "document_sha256": digest}


def add_note(request: AddNote) -> dict:
    """Append one cited note as the next notebook revision under optimistic concurrency."""
    with database(request.index_path, write=True) as db:
        value = _required(db, request, request.notebook_id)
        if value["revision"] != request.expected_revision:
            raise ValueError(f"Notebook revision conflict: current {value['revision']}, expected {request.expected_revision}")
        note = {"note_id": request.note_id, "revision": 1, "text": request.text,
                "citations": [c.model_dump(mode="json") for c in request.citations]}
        document = NotebookDocument.model_validate({**value, "revision": value["revision"] + 1, "notes": value["notes"] + [note]})
        for citation in note["citations"]:
            _passage(db, citation)
        digest = _save(db, request, document)
    return {"status": "noted", "workspace": request.workspace, "notebook_id": request.notebook_id,
            "revision": document.revision, "document_sha256": digest}


def query(request: Query) -> dict:
    """Literal casefold search over this notebook's collections and notes only."""
    needle = request.query.casefold()
    with database(request.index_path) as db:
        value = _required(db, request, request.notebook_id)
        rows = db.execute(f"SELECT collection, observation, revision, digest FROM observations WHERE collection IN ({','.join('?' * len(value['collections']))})"
                          " ORDER BY collection, observation, revision", value["collections"]).fetchall()
        passages = [p for p in (_passage(db, {"collection": r["collection"], "observation_id": r["observation"],
                                              "source_revision": r["revision"], "media_digest": r["digest"]}) for r in rows)
                    if needle in p["text"].casefold()]
    notes = [n for n in value["notes"] if needle in n["text"].casefold()]
    total = len(passages) + len(notes)
    return bounded({"status": "found" if total else "no_evidence", "workspace": request.workspace,
                    "notebook_id": request.notebook_id, "revision": value["revision"],
                    "algorithm": "literal_unicode_casefold_substring_v1", "total_matches": total,
                    "passages": passages[:request.limit], "notes": notes[:max(0, request.limit - len(passages))]})


def export(request: Export) -> dict:
    """Portable document, Markdown and escaped HTML linking citations to exact supporting passages."""
    with database(request.index_path) as db:
        value = _required(db, request, request.notebook_id)
        digest = _current(db, request, request.notebook_id)[1]
        appendix, keys, lines = [], {}, ["# " + value["title"], ""]
        title = escape(value["title"])
        html_lines = ['<!DOCTYPE html>', '<html lang="en"><head><meta charset="utf-8">',
                      f'<title>{title}</title></head><body>', f'<h1>{title}</h1>']
        for note in value["notes"]:
            marks, links = [], []
            for citation in note["citations"]:
                key = canonical(citation)
                if key not in keys:
                    keys[key] = len(keys) + 1
                    p = _passage(db, citation)
                    appendix.append(f"[{keys[key]}] {p['source_id']} {p['observation_id']} {p['start_seconds']}–{p['end_seconds']} s"
                                    f" ({p['kind']}, sha256 {p['observation_sha256']}): \"{p['text']}\"")
                marks.append(f"[{keys[key]}]")
                links.append(f'<a href="#passage-{keys[key]}">[{keys[key]}]</a>')
            lines.append(note["text"] + " " + "".join(marks))
            html_lines.append(f'<p>{escape(note["text"])} {"".join(links)}</p>')
    markdown = "\n".join(lines + ["", "## Sources", ""] + appendix) + "\n"
    targets = [f'<li id="passage-{number}"><pre>{escape(passage)}</pre></li>'
               for number, passage in enumerate(appendix, start=1)]
    html = "\n".join(html_lines + ['<h2>Sources</h2><ol>'] + targets + ['</ol></body></html>']) + "\n"
    return bounded({"status": "exported", "workspace": request.workspace, "notebook_id": request.notebook_id,
                    "revision": value["revision"], "document": value, "document_sha256": digest,
                    "markdown": markdown, "html": html})


def status(request: Status) -> dict:
    """List this workspace's notebooks; no external service, credential or provider state exists here."""
    with database(request.index_path) as db:
        workspace(db, request.workspace)
        names = [] if not db.execute("SELECT 1 FROM sqlite_master WHERE name='notebook_revisions'").fetchone() else [
            r[0] for r in db.execute("SELECT DISTINCT notebook FROM notebook_revisions WHERE workspace=? ORDER BY notebook", (request.workspace,))]
        books = [{"notebook_id": n, "revision": d["revision"], "notes": len(d["notes"]), "collections": d["collections"]}
                 for n in names for d in [_current(db, request, n)[0]]]
    return bounded({"status": "listed", "workspace": request.workspace, "notebooks": books, "external_services": []})


def execute(request) -> dict:
    """Dispatch one validated notebook request."""
    handlers = {"import": import_document, "note": add_note, "query": query, "export": export, "status": status}
    return handlers[request.action](request)
