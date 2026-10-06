"""Offline exports over real dummy canonical stores; no native decoder or provider."""

import base64
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

import pytest

from video_research_mcp import evidence_export as implementation
from video_research_mcp.corpus_index import mutate
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.models.wiki import Write
from video_research_mcp.tools.evidence_export import evidence_export
from video_research_mcp.wiki_store import write

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6u8AAAAASUVORK5CYII=")
ATTACK = '<script src="https://evil.invalid/a.js"></script><img src=x onerror=alert(1)>'


class Tags(HTMLParser):
    """Observe active tags/URLs without opening a browser or requesting any bytes."""

    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.fixture
def sample(tmp_path, monkeypatch, clean_config):
    """A tiny authored frame plus actual canonical SQLite evidence, never source truth."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    frame = tmp_path / "frame.png"
    frame.write_bytes(PNG)
    sha = hashlib.sha256(PNG).hexdigest()
    obs = {"video_id": "v", "observation_id": "o", "source_revision": "r1", "media_digest": "a" * 64,
           "kind": "OCR", "start_seconds": 1.125, "end_seconds": 2.875, "text": "copper " + ATTACK,
           "artifact_refs": [{"artifact_id": "frame", "kind": "frame", "path": str(frame), "sha256": sha}]}
    index = tmp_path / "corpus.sqlite3"
    mutate(IndexRequest(action="index", index_path=str(index), collection="c", expected_revision=0, observations=[obs]))
    record = {**obs, "title": ATTACK, "citation_id": "fixture-citation", "basis": "inferred",
              "model": "authored-fixture-model", "method": "authored-fixture-method"}
    source = {"kind": "fixture", "records": [record]}
    return tmp_path, frame, obs, source, index


def request(sample, **values):
    """One explicit dummy fixture export with a fresh output bundle."""
    root, _, _, source, _ = sample
    return {"source": source, "output_directory": str(root / "export"), "title": ATTACK, **values}


def report(result):
    """Read only unit-created artifacts from the successful receipt."""
    return {a["path"].rsplit("/", 1)[-1]: Path(a["path"]).read_text() for a in result["artifacts"]}


@pytest.mark.parametrize("basis", ["observed", "inferred"])
async def test_standalone_escaping_timeline_frame_and_exact_provenance(sample, mock_gemini_client, basis):
    """All four original criteria: inert HTML, precise metadata and exact inline bytes."""
    sample[3]["records"][0]["basis"] = basis
    result = await evidence_export(request(sample))
    assert result["status"] == "exported" and result["complete"] and result["provider_calls"] == 0
    files = report(result)
    tags = Tags(files["report.html"])
    assert not any(tag in {"script", "iframe", "object", "embed", "link", "video", "audio"} for tag, _ in tags.tags)
    for tag, attrs in tags.tags:
        assert not any(k.startswith("on") for k in attrs)
        for k in ("src", "href"):
            if k in attrs:
                assert attrs[k].startswith(("data:image/", "#record-"))
    assert '&lt;script' in files["report.html"] and "1.125–2.875 seconds" in files["report.html"]
    assert "capture time not recorded" in files["report.html"]
    uri = next(attrs["src"] for tag, attrs in tags.tags if tag == "img")
    assert base64.b64decode(uri.split(",", 1)[1]) == PNG
    data = json.loads(files["report.json"])
    record = data["records"][0]
    assert (record["start_seconds"], record["end_seconds"], record["media_digest"]) == (1.125, 2.875, "a" * 64)
    assert record["origin"] == "caller_fixture" and record["basis"] == basis
    for value in ("fixture-citation", "authored-fixture-model", "authored-fixture-method", basis, "a" * 64):
        assert value.replace("-", "\\-") in files["report.md"]
    for item in result["artifacts"]:
        raw = Path(item["path"]).read_bytes()
        assert (len(raw), hashlib.sha256(raw).hexdigest()) == (item["bytes"], item["sha256"])
    mock_gemini_client["get"].assert_not_called()
    mock_gemini_client["generate_structured"].assert_not_called()


async def test_actual_corpus_retrieval_and_no_evidence(sample, monkeypatch):
    root, _, obs, _, index = sample
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("network attempted"))
    source = {"kind": "corpus", "request": {"action": "query", "index_path": str(index), "collection": "c",
              "query": "copper", "source_revisions": {"v": "r1"}, "mode": "fts"}}
    result = await evidence_export(request(sample, source=source))
    record = json.loads(report(result)["report.json"])["records"][0]
    assert result["selection"]["route"] == "corpus_retrieve.query" and result["selection"]["index_revision"] == 1
    assert record["text"] == obs["text"] and record["origin"] == "canonical_corpus"
    assert record["basis"] == "unknown" and record["model"] is None and record["method"] == "not_recorded"
    source["request"]["query"] = "absent"
    absent = await evidence_export(request(sample, source=source, output_directory=str(root / "empty")))
    assert absent["status"] == "no_evidence" and absent["records"] == 0


async def test_actual_wiki_context_retains_citations_claim_and_page_binding(sample):
    _, _, obs, _, index = sample
    link = {"evidence_id": "e", "collection": "c", **{k: obs[k] for k in ("video_id", "observation_id", "source_revision", "media_digest")},
            "attribution": "Caller speaker", "claim": "uncertain copper", "stance": "unknown"}
    page = write(Write(action="write", index_path=str(index), concept_id="concept", expected_revision=0, kind="concept", title=ATTACK, evidence=[link]))["pages"][0]
    source = {"kind": "wiki", "request": {"action": "ask", "index_path": str(index), "question": "copper", "concept_ids": ["concept"]}}
    result = await evidence_export(request(sample, source=source))
    record = json.loads(report(result)["report.json"])["records"][0]
    assert record["source_state"] == "recorded_observation_matches" and record["text"] == obs["text"]
    assert record["claim"] == "uncertain copper" and record["stance"] == "unknown"
    assert record["page_revision"] == 1 and record["page_sha256"] == page["page_sha256"]
    assert len(record["citation_id"]) == 64 and record["origin"] == "canonical_wiki"


@pytest.mark.parametrize("kind", ["keyframe", "transcript"])
async def test_actual_collection_recall_preserves_asset_hash_and_unknown_timing(sample, kind):
    from video_research_mcp.tools.collections import collections_manage

    root, frame, _, _, index = sample
    scope = {"index_path": str(index), "workspace": "w"}
    assert (await collections_manage({**scope, "action": "configure", "owned_root": str(root / "owned"), "quota_bytes": 1024}))["status"] == "configured"
    assert (await collections_manage({**scope, "action": "create", "collection": "media", "kind": "media", "label": ATTACK, "expected_revision": 0}))["status"] == "created"
    asset = {"asset_id": "asset", "video_id": "v", "source_revision": "r1", "media_digest": "a" * 64,
             "kind": kind, "path": str(frame), "sha256": hashlib.sha256(PNG).hexdigest(), "size_bytes": len(PNG)}
    assert (await collections_manage({**scope, "action": "attach", "collection": "media", "expected_revision": 1, "evidence": asset}))["status"] == "attached"
    source = {"kind": "collections", "request": {**scope, "action": "recall", "collection": "media"}}
    result = await evidence_export(request(sample, source=source))
    record = json.loads(report(result)["report.json"])["records"][0]
    assert result["selection"]["route"] == "collections_manage.recall"
    assert record["citation_id"] == "asset" and record["source_id"] == "v@r1"
    assert record["start_seconds"] is None and record["end_seconds"] is None and not record["text"]
    assert record["artifact_refs"][0]["sha256"] == asset["sha256"] and record["origin"] == "canonical_collections"
    assert record["kind"] == kind
    assert sum(tag == "img" for tag, _ in Tags(report(result)["report.html"]).tags) == (kind == "keyframe")


async def test_current_corpus_revision_refuses_stale_source_selection(sample):
    root, _, obs, _, index = sample
    changed = {**obs, "source_revision": "r2", "text": "new copper"}
    mutate(IndexRequest(action="index", index_path=str(index), collection="c", expected_revision=1, observations=[changed]))
    source = {"kind": "corpus", "request": {"action": "query", "index_path": str(index), "collection": "c",
              "query": "copper", "source_revisions": {"v": "r1"}, "mode": "fts"}}
    result = await evidence_export(request(sample, source=source, output_directory=str(root / "stale")))
    assert result["status"] == "no_evidence" and result["selection"]["index_revision"] == 2


@pytest.mark.parametrize("policy", ["report", "refuse"])
async def test_missing_frame_is_named_without_apparent_image(sample, policy):
    _, frame, _, _, _ = sample
    frame.unlink()
    result = await evidence_export(request(sample, missing_frames=policy))
    if policy == "refuse":
        assert "frame" in result["error"] and not (sample[0] / "export").exists()
    else:
        assert result["status"] == "partial" and not result["complete"]
        assert result["frame_issues"][0]["artifact_id"] == "frame" and result["frame_issues"][0]["state"] == "missing"
        assert not any(tag == "img" for tag, _ in Tags(report(result)["report.html"]).tags)


@pytest.mark.parametrize("change", ["digest", "symlink", "svg", "oversize"])
async def test_refused_frames_are_explicit_and_bounded_before_read(sample, monkeypatch, change):
    root, frame, _, source, _ = sample
    if change == "digest":
        frame.write_bytes(PNG + b"changed")
    elif change == "symlink":
        frame.unlink()
        other = root / "other.png"
        other.write_bytes(PNG)
        frame.symlink_to(other)
    elif change == "svg":
        raw = b'<svg><script>alert(1)</script></svg>'
        frame.write_bytes(raw)
        source["records"][0]["artifact_refs"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    else:
        with frame.open("r+b") as stream:
            stream.truncate(262145)  # sparse, not a large allocated fixture
        original = implementation._open_regular
        class Reader:
            def __enter__(self):
                self.stream = original(frame)
                return self
            def __exit__(self, *args):
                self.stream.close()
            def fileno(self):
                return self.stream.fileno()
            def read(self, *args):
                pytest.fail("oversize frame read before refusal")
        monkeypatch.setattr(implementation, "_open_regular", lambda path: Reader() if path == frame else original(path))
    result = await evidence_export(request(sample))
    assert result["status"] == "partial" and result["frame_issues"][0]["state"] == "refused"
    assert not any(tag == "img" for tag, _ in Tags(report(result)["report.html"]).tags)


async def test_inline_and_aggregate_output_bounds_preserve_absence(sample):
    result = await evidence_export(request(sample, max_inline_bytes=1, missing_frames="refuse"))
    assert "bound" in result["error"] and not (sample[0] / "export").exists()
    result = await evidence_export(request(sample, max_export_bytes=1024))
    assert "max_export_bytes" in result["error"] and not (sample[0] / "export").exists()


async def test_repeated_inline_images_charge_expanded_html_before_publication(sample):
    """A shared byte reference still consumes output space on every HTML occurrence."""
    root, frame, _, source, _ = sample
    raw = PNG + b"authored bounded padding" * 50
    frame.write_bytes(raw)
    ref = {**source["records"][0]["artifact_refs"][0], "sha256": hashlib.sha256(raw).hexdigest()}
    source["records"][0]["artifact_refs"] = [ref] * 16
    result = await evidence_export(request(sample, formats=["html"], max_export_bytes=10000))
    assert "max_export_bytes" in result["error"] and not (root / "export").exists()


async def test_existing_output_and_scope_are_preserved(sample, tmp_path):
    directory = sample[0] / "export"
    directory.mkdir()
    marker = directory / "keep"
    marker.write_bytes(b"original")
    assert "error" in await evidence_export(request(sample))
    assert marker.read_bytes() == b"original"
    result = await evidence_export(request(sample, output_directory=str(tmp_path.parent / "outside-export")))
    assert result["category"] == "PERMISSION_DENIED"


async def test_frame_growth_during_read_is_refused(sample, monkeypatch):
    _, frame, _, _, _ = sample
    original = implementation._open_regular
    class Reader:
        def __enter__(self):
            self.stream = original(frame)
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self, amount):
            raw = self.stream.read(amount)
            with frame.open("ab") as writer:
                writer.write(b"growth")
            return raw
    monkeypatch.setattr(implementation, "_open_regular", lambda p: Reader() if p == frame else original(p))
    result = await evidence_export(request(sample))
    assert result["status"] == "partial" and "changed during" in result["frame_issues"][0]["reason"]


async def test_partial_publication_failure_removes_only_owned_outputs(sample, monkeypatch):
    original = implementation.os.fsync
    calls = []
    def fail(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("authored write failure")
        return original(fd)
    monkeypatch.setattr(implementation.os, "fsync", fail)
    result = await evidence_export(request(sample))
    assert "authored write failure" in result["error"] and not (sample[0] / "export").exists()


async def test_parent_substitution_during_selection_never_creates_outside_output(
    sample, monkeypatch, tmp_path_factory
):
    """A replaced allowed parent must refuse before writing through its new symlink."""
    root = sample[0]
    parent = root / "parent"
    parent.mkdir()
    moved = root / "held-parent"
    outside = tmp_path_factory.mktemp("viewer-outside")
    marker = outside / "keep"
    marker.write_text("unrelated")

    async def substitute(source):
        parent.rename(moved)
        parent.symlink_to(outside, target_is_directory=True)
        return [], {}

    monkeypatch.setattr(implementation, "select", substitute)
    result = await evidence_export(request(sample, output_directory=str(parent / "export")))
    assert "error" in result
    assert not (outside / "export").exists() and not (moved / "export").exists()
    assert marker.read_text() == "unrelated"


async def test_child_open_failure_cleans_new_directory(sample, monkeypatch):
    """Descriptor acquisition failure must clean the empty directory just created."""
    def refuse(directory):
        raise PermissionError("authored child open refusal")

    monkeypatch.setattr(implementation, "open_owned", refuse)
    result = await evidence_export(request(sample))
    assert "authored child open refusal" in result["error"]
    assert not (sample[0] / "export").exists()


async def test_created_directory_identity_failure_reports_cleanup_liability(sample, monkeypatch):
    """Unknown created-directory identity retains the primary failure and cleanup path."""
    original = implementation.os.stat

    def refuse(path, *args, **kwargs):
        if path == "export" and "dir_fd" in kwargs and kwargs.get("follow_symlinks") is False:
            raise OSError("authored directory identity refusal")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(implementation.os, "stat", refuse)
    result = await evidence_export(request(sample))
    directory = sample[0] / "export"
    assert "authored directory identity refusal" in result["error"]
    assert "cleanup incomplete" in result["error"] and str(directory) in result["error"]
    assert directory.exists() and not any(directory.iterdir())


async def test_cleanup_refusal_retains_primary_and_names_remaining_directory(sample, monkeypatch):
    """An OS cleanup failure must retain the original write error and its liability."""
    def fail_write(fd):
        raise OSError("authored write failure")
    def fail_unlink(*args, **kwargs):
        raise OSError("authored cleanup refusal")
    monkeypatch.setattr(implementation.os, "fsync", fail_write)
    monkeypatch.setattr(implementation.os, "unlink", fail_unlink)
    result = await evidence_export(request(sample))
    assert "authored write failure" in result["error"] and "authored cleanup refusal" in result["error"]
    assert str(sample[0] / "export") in result["error"] and (sample[0] / "export" / "report.html").exists()


@pytest.mark.parametrize("source", [
    {"kind": "corpus", "request": {"action": "query", "index_path": "x.sqlite3", "collection": "c", "query": "x", "source_revisions": {"v": "r"}, "graph": {"endpoint": "http://127.0.0.1:9", "hl_keywords": ["x"], "ll_keywords": ["y"]}}},
    {"kind": "wiki", "request": {"action": "ask", "index_path": "x.sqlite3", "question": "x", "mode": "gemini"}},
])
async def test_model_and_network_routes_refused_at_typed_boundary(sample, source):
    assert "error" in await evidence_export(request(sample, source=source))
    assert not (sample[0] / "export").exists()
