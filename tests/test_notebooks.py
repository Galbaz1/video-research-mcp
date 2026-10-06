"""Local notebooks: ID/revision-preserving import/export, scoped query, cited passages, no secrets."""

import hashlib
from html.parser import HTMLParser
import json

import pytest

from video_research_mcp.collections import execute as collections
from video_research_mcp.corpus_index import connect, mutate, revision
from video_research_mcp.models.collections import Configure, Create
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.notebooks import execute
from video_research_mcp.tools.notebooks import _REQUEST, notebook_manage

SECRET = "sk-r363-never-export"


def run(**request):
    return execute(_REQUEST.validate_python(request))


def index(scope, name, tmp_path, items):
    """Index real canonical observations into an existing workspace collection."""
    transcript = tmp_path / f"{name}.txt"
    transcript.write_text("transcript")
    digest = hashlib.sha256(b"transcript").hexdigest()
    observations = [{"video_id": "v1", "observation_id": oid, "source_revision": "r1", "media_digest": digest,
                     "kind": "speech", "start_seconds": start, "end_seconds": start + 2.5, "text": text,
                     "artifact_refs": [{"artifact_id": f"{name}-t", "kind": "transcript", "path": str(transcript), "sha256": digest}]}
                    for oid, start, text in items]
    with connect(scope["index_path"]) as db:
        expected = revision(db, name)
    mutate(IndexRequest(action="index", collection=name, expected_revision=expected, observations=observations,
                        index_path=scope["index_path"]))
    return digest


@pytest.fixture
def corpus(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    path = str(tmp_path / "corpus.sqlite3")
    scopes = {}
    for space, name in (("creator", "talks"), ("other", "private")):
        scope = {"index_path": path, "workspace": space}
        collections(Configure(action="configure", owned_root=str(tmp_path / f"owned-{space}"), quota_bytes=1024, **scope))
        collections(Create(action="create", collection=name, kind="transcript", label=name, expected_revision=0, **scope))
        scopes[space] = scope
    digest = index(scopes["creator"], "talks", tmp_path, [("o1", 1.25, "The lamp is green at noon."), ("o2", 9.0, "Budget rose 4%.")])
    index(scopes["other"], "private", tmp_path, [("p1", 0.0, "Private green memo.")])
    cite = {"collection": "talks", "observation_id": "o1", "source_revision": "r1", "media_digest": digest}
    return {"scope": scopes["creator"], "other": scopes["other"], "cite": cite, "tmp_path": tmp_path}


def document(notebook_id="nb-a", revision=1, notes=()):
    return {"notebook_id": notebook_id, "revision": revision, "title": "Lamp study", "collections": ["talks"], "notes": list(notes)}


def test_import_note_export_reimport_preserves_ids_and_revisions(corpus, tmp_path):
    scope = corpus["scope"]
    assert run(action="import", document=document(), **scope)["status"] == "imported"
    noted = run(action="note", notebook_id="nb-a", expected_revision=1, note_id="n1", text="Green at noon.", citations=[corpus["cite"]], **scope)
    assert noted["revision"] == 2
    exported = run(action="export", notebook_id="nb-a", **scope)
    doc = exported["document"]
    assert (doc["notebook_id"], doc["revision"], doc["notes"][0]["note_id"], doc["collections"]) == ("nb-a", 2, "n1", ["talks"])
    assert run(action="import", document=doc, **scope)["status"] == "unchanged"
    with pytest.raises(ValueError, match="revision conflict"):
        run(action="import", document=document(), **scope)
    with pytest.raises(ValueError, match="revision conflict"):
        run(action="note", notebook_id="nb-a", expected_revision=1, note_id="n2", text="x", citations=[corpus["cite"]], **scope)


def test_export_cites_supporting_passage_not_title(corpus):
    scope = corpus["scope"]
    run(action="import", document=document(), **scope)
    run(action="note", notebook_id="nb-a", expected_revision=1, note_id="n1", text="Observed colour.", citations=[corpus["cite"]], **scope)
    markdown = run(action="export", notebook_id="nb-a", **scope)["markdown"]
    assert "Observed colour. [1]" in markdown
    appendix = markdown.split("## Sources", 1)[1]
    assert '[1] v1@r1 o1 1.25–3.75 s (speech' in appendix and '"The lamp is green at noon."' in appendix
    assert "Lamp study" not in appendix


def test_query_is_scoped_to_its_own_notebook_and_workspace(corpus):
    scope = corpus["scope"]
    run(action="import", document=document("nb-a"), **scope)
    run(action="import", document=document("nb-b"), **scope)
    run(action="note", notebook_id="nb-a", expected_revision=1, note_id="n1", text="secret plan alpha", citations=[corpus["cite"]], **scope)
    other = run(action="query", notebook_id="nb-b", query="secret plan", **scope)
    assert (other["status"], other["notes"], other["passages"]) == ("no_evidence", [], [])
    green = run(action="query", notebook_id="nb-b", query="GREEN", **scope)
    assert [p["observation_id"] for p in green["passages"]] == ["o1"] and "Private" not in json.dumps(green)
    assert run(action="query", notebook_id="nb-a", query="secret plan", **scope)["notes"][0]["note_id"] == "n1"
    with pytest.raises(PermissionError):
        run(action="import", document={**document("nb-x"), "collections": ["private"]}, **scope)
    with pytest.raises(ValueError, match="absent"):
        run(action="query", notebook_id="nb-a", query="green", **corpus["other"])


def test_unbound_citation_refused_before_storage(corpus):
    scope = corpus["scope"]
    run(action="import", document=document(), **scope)
    bad = corpus["cite"] | {"media_digest": "0" * 64}
    with pytest.raises(ValueError, match="digest"):
        run(action="note", notebook_id="nb-a", expected_revision=1, note_id="n1", text="x", citations=[bad], **scope)
    assert run(action="export", notebook_id="nb-a", **scope)["revision"] == 1


async def test_tool_receipts_never_contain_configured_secret_and_use_no_service(corpus):
    scope = corpus["scope"]
    outputs = [await notebook_manage({"action": "import", "document": document(), **scope}),
               await notebook_manage({"action": "note", "notebook_id": "nb-a", "expected_revision": 1, "note_id": "n1",
                                      "text": "Green.", "citations": [corpus["cite"]], **scope}),
               await notebook_manage({"action": "query", "notebook_id": "nb-a", "query": "green", **scope}),
               await notebook_manage({"action": "export", "notebook_id": "nb-a", **scope}),
               await notebook_manage({"action": "status", **scope}),
               await notebook_manage({"action": "query", "notebook_id": "missing", "query": "x", **scope})]
    assert all(SECRET not in json.dumps(out) for out in outputs)
    assert outputs[4]["external_services"] == [] and outputs[4]["notebooks"][0]["revision"] == 2
    assert "error" in outputs[5]


@pytest.mark.parametrize("field", ["observation_id", "source_revision"])
@pytest.mark.parametrize("action", ["import", "note", "export"])
async def test_corrupted_passage_identity_refuses_without_new_revision(corpus, field, action):
    """A schema-valid substituted passage cannot inherit another citation's identity."""
    scope = corpus["scope"]
    run(action="import", document=document(), **scope)
    run(action="note", notebook_id="nb-a", expected_revision=1, note_id="n1",
        text="Green.", citations=[corpus["cite"]], **scope)
    saved = run(action="export", notebook_id="nb-a", **scope)["document"]
    with connect(scope["index_path"], mode="rw") as db:
        row = db.execute("SELECT id,payload FROM observations WHERE collection='talks' AND observation='o1'").fetchone()
        payload = json.loads(row["payload"])
        payload[field] = "other"
        db.execute("UPDATE observations SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))
        db.commit()
    requests = {
        "import": {"document": {**saved, "revision": 3}},
        "note": {"notebook_id": "nb-a", "expected_revision": 2, "note_id": "n2",
                 "text": "Green again.", "citations": [corpus["cite"]]},
        "export": {"notebook_id": "nb-a"},
    }
    result = await notebook_manage({"action": action, **requests[action], **scope})
    assert "error" in result
    assert run(action="status", **scope)["notebooks"][0]["revision"] == 2


class ExportHTML(HTMLParser):
    """Read actual citation destinations and passage text without executing a browser."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.links, self.passages, self.tags, self.attributes = [], {}, [], []
        self.target = None
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs.get("href"))
        if "id" in attrs:
            self.target = attrs["id"]
            assert self.target not in self.passages, "Duplicate HTML destination"
            self.passages[self.target] = ""

    def handle_endtag(self, tag):
        if tag == "li":
            self.target = None

    def handle_data(self, data):
        if self.target is not None:
            self.passages[self.target] += data


async def test_html_citations_resolve_to_exact_bound_passages(corpus):
    """Inline links must resolve to the cited quote and identity, not the notebook title."""
    scope = corpus["scope"]
    citations = [corpus["cite"], corpus["cite"] | {"observation_id": "o2"}]
    notes = [{"note_id": "n1", "revision": 1, "text": "Two passages.", "citations": citations}]
    await notebook_manage({"action": "import", "document": document(notes=notes), **scope})
    exported = await notebook_manage({"action": "export", "notebook_id": "nb-a", **scope})
    parsed = ExportHTML(exported["html"])
    assert parsed.links == ["#passage-1", "#passage-2"]
    for link, marker, quote in zip(parsed.links, ("[1]", "[2]"),
                                   ("The lamp is green at noon.", "Budget rose 4%.")):
        target = parsed.passages[link[1:]]
        assert target == exported["markdown"].split("## Sources\n\n", 1)[1].splitlines()[int(marker[1]) - 1]
        assert quote in target and "Lamp study" not in target
    assert "v1@r1 o1 1.25–3.75 s" in parsed.passages["passage-1"]
    assert "v1@r1 o2 9.0–11.5 s" in parsed.passages["passage-2"]
    assert exported["document"] == document(notes=notes)
    assert run(action="import", document=exported["document"], **scope)["status"] == "unchanged"


async def test_html_export_escapes_title_note_and_supporting_quote(corpus):
    """Malicious user strings stay text in a portable document with no active/external assets."""
    scope = corpus["scope"]
    title = '<script>alert("title")</script> & \'heading\''
    note = '<img src="https://invalid.example/n" onerror="alert(1)"> & \'note\''
    quote = '<svg onload="alert(2)"> & "quote" \'source\''
    index(scope, "talks", corpus["tmp_path"], [("o3", 4.5, quote)])
    cite = corpus["cite"] | {"observation_id": "o3"}
    notes = [{"note_id": "n1", "revision": 1, "text": note, "citations": [cite]}]
    doc = document(notes=notes) | {"title": title}
    assert run(action="import", document=doc, **scope)["status"] == "imported"
    exported = await notebook_manage({"action": "export", "notebook_id": "nb-a", **scope})
    markup = exported["html"]
    parsed = ExportHTML(markup)
    assert markup.startswith("<!DOCTYPE html>")
    assert not ({"script", "img", "svg", "link", "iframe", "style", "base"} & set(parsed.tags))
    assert all(not name.startswith("on") and name not in {"src", "srcset", "style"}
               for name, value in parsed.attributes)
    assert parsed.links == ["#passage-1"] and quote in parsed.passages["passage-1"]
    assert title not in markup and note not in markup and quote not in markup
    for escaped in ("&lt;script&gt;", "&lt;img", "&lt;svg", "&amp;", "&quot;", "&#x27;"):
        assert escaped in markup
    assert exported["document"] == doc and title in exported["markdown"] and quote in exported["markdown"]


async def test_html_repeated_citation_uses_one_destination_across_notes(corpus):
    """Repeated citations keep each note's link while sharing the single bound source target."""
    scope = corpus["scope"]
    notes = [{"note_id": name, "revision": 1, "text": name,
              "citations": [corpus["cite"], corpus["cite"]]} for name in ("n1", "n2")]
    run(action="import", document=document(notes=notes), **scope)
    exported = await notebook_manage({"action": "export", "notebook_id": "nb-a", **scope})
    parsed = ExportHTML(exported["html"])
    assert parsed.links == ["#passage-1"] * 4
    assert list(parsed.passages) == ["passage-1"]
    assert parsed.passages["passage-1"].count("The lamp is green at noon.") == 1
    assert exported["markdown"].count('[1] v1@r1 o1') == 1


async def test_html_expansion_counts_toward_complete_response_bound(corpus):
    """Escaping can exceed 64 KiB even when document and Markdown fit; export must refuse."""
    scope = corpus["scope"]
    notes = [{"note_id": name, "revision": 1, "text": "&" * 5000,
              "citations": [corpus["cite"]]} for name in ("n1", "n2")]
    imported = run(action="import", document=document(notes=notes), **scope)
    result = await notebook_manage({"action": "export", "notebook_id": "nb-a", **scope})
    assert "error" in result and "64 KiB" in json.dumps(result)
    assert "html" not in result and "document" not in result
    assert run(action="status", **scope)["notebooks"][0]["revision"] == 1
    again = run(action="import", document=document(notes=notes), **scope)
    assert again["status"] == "unchanged" and again["document_sha256"] == imported["document_sha256"]
