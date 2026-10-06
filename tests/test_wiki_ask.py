"""Evidence/context disclosure and optional mocked synthesis boundaries."""

import hashlib
import json
from pathlib import Path

import pytest

from video_research_mcp.corpus_index import canonical, connect, mutate
from video_research_mcp.job_execution import single_submission
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.models.wiki import Prose, Write
from video_research_mcp.tools.wiki import wiki_manage
from video_research_mcp.wiki_store import write


@pytest.fixture
def wiki(tmp_path, monkeypatch, clean_config):
    """GIVEN an existing source record and an attributed unknown wiki contribution."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    scope = {"index_path": str(tmp_path / "corpus.sqlite3")}
    path = tmp_path / "transcript.txt"
    path.write_bytes(b"source admits uncertainty")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    obs = {"video_id": "v", "observation_id": "o", "source_revision": "r", "media_digest": digest,
           "kind": "speech", "start_seconds": 1.25, "end_seconds": 2.75, "text": "source admits uncertainty",
           "artifact_refs": [{"artifact_id": "a", "kind": "transcript", "path": str(path), "sha256": digest}]}
    mutate(IndexRequest(action="index", collection="c", expected_revision=0, observations=[obs], **scope))
    link = {"evidence_id": "link", "collection": "c", "video_id": "v", "observation_id": "o", "source_revision": "r",
            "media_digest": digest, "attribution": "speaker", "claim": "uncertain mechanism", "stance": "unknown"}
    page = write(Write(action="write", concept_id="concept", kind="concept", title="Mechanism", expected_revision=0,
                       body="Caller text with attributed uncertainty", evidence=[link], **scope))["pages"][0]
    return scope, page, path


async def test_context_only_discloses_and_opens_exact_evidence_no_provider(wiki, mock_gemini_client):
    """WHEN default wiki ask runs THEN exact retrieved source context is exposed without synthesis."""
    scope, page, _ = wiki
    result = await wiki_manage({"action": "ask", "question": "mechanism", **scope})
    assert result["status"] == "found"
    assert result["model_generated"] is False
    assert result["synthesis_origin"] == "none"
    assert result["provider_calls"] == 0
    assert result["context"][0]["page_sha256"] == page["page_sha256"]
    source = result["context"][0]["evidence"][0]
    assert (source["start_seconds"], source["end_seconds"]) == (1.25, 2.75)
    assert source["observation_text"] == "source admits uncertainty"
    assert source["stance"] == "unknown"
    ref = source["artifact_refs"][0]
    assert hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
    assert hashlib.sha256(canonical(result["context"]).encode()).hexdigest() == result["context_sha256"]
    mock_gemini_client["get"].assert_not_called()
    mock_gemini_client["generate_structured"].assert_not_called()


async def test_mocked_gemini_labels_synthesis_and_frozen_context(wiki, mock_gemini_client):
    """WHEN explicitly requested mocked prose succeeds THEN origin/model/citations and context are visible."""
    scope, _, _ = wiki
    def synthesize(contents, **kwargs):
        assert single_submission.get() is True
        context = json.loads(contents)["context"]
        assert context[0]["evidence"][0]["stance"] == "unknown"
        assert kwargs["tools"] == []
        assert kwargs["schema"] is Prose
        assert kwargs["model"] == "fixture-model"
        return Prose(text="The speaker reports uncertainty; no verified fact is established.",
                     evidence_ids=[context[0]["evidence"][0]["citation_id"]])
    mock_gemini_client["generate_structured"].side_effect = synthesize
    result = await wiki_manage({"action": "ask", "question": "Explain the mechanism", "concept_ids": ["concept"],
                               "mode": "gemini", "model": "fixture-model", **scope})
    assert result["status"] == "answered"
    assert result["model_generated"] is True
    assert result["synthesis_origin"] == "model_generated"
    assert result["model"] == "fixture-model"
    assert result["cited_evidence_ids"] == [result["context"][0]["evidence"][0]["citation_id"]]
    assert result["provider_calls"] == 1  # Mocked invocation, not native/provider qualification.
    assert single_submission.get() is False
    mock_gemini_client["generate_structured"].assert_awaited_once()


async def test_no_evidence_never_generates_and_caller_text_is_labeled(wiki, mock_gemini_client):
    """WHEN retrieval is empty THEN no model runs; caller prose remains explicitly caller supplied."""
    scope, _, _ = wiki
    absent = await wiki_manage({"action": "ask", "question": "unrepresented", "mode": "gemini", **scope})
    assert absent["status"] == "no_evidence"
    assert absent["model_generated"] is False
    mock_gemini_client["generate_structured"].assert_not_called()
    caller = await wiki_manage({"action": "ask", "question": "mechanism", "mode": "caller",
                               "caller_text": "Caller interpretation, still uncertain", **scope})
    assert caller["synthesis_origin"] == "caller_text"
    assert caller["model_generated"] is False
    assert caller["provider_calls"] == 0


async def test_invalid_citation_and_provider_failure_do_not_mutate_history(wiki, mock_gemini_client):
    """WHEN mocked generation fails or invents a citation THEN page history remains exact."""
    scope, page, _ = wiki
    mock_gemini_client["generate_structured"].return_value = Prose(text="Invalid citation", evidence_ids=["invented"])
    request = {"action": "ask", "question": "mechanism", "mode": "gemini", **scope}
    error = await wiki_manage(request)
    assert "outside retrieved context" in error["error"]
    mock_gemini_client["generate_structured"].side_effect = RuntimeError("fixture provider refusal")
    failed = await wiki_manage(request)
    assert "fixture provider refusal" in failed["error"]
    assert single_submission.get() is False
    history = await wiki_manage({"action": "history", "concept_id": "concept", **scope})
    assert history["pages"] == [page]


async def test_missing_changed_sources_and_symlink_are_honestly_exposed(wiki):
    """WHEN evidence disappears or its canonical record changes THEN context does not claim verification."""
    scope, _, path = wiki
    path.unlink()
    result = await wiki_manage({"action": "ask", "question": "mechanism", **scope})
    assert result["context"][0]["evidence"][0]["artifact_availability"][0]["state"] == "missing"
    outside = path.parent / "outside"
    outside.write_bytes(b"private")
    path.symlink_to(outside)
    result = await wiki_manage({"action": "ask", "question": "mechanism", **scope})
    assert result["context"][0]["evidence"][0]["artifact_availability"][0]["state"] == "refused"
    with connect(scope["index_path"], mode="rw") as db:
        db.execute("UPDATE observations SET payload=replace(payload,'uncertainty','changed text')")
        db.commit()
    changed = await wiki_manage({"action": "ask", "question": "mechanism", **scope})
    source = changed["context"][0]["evidence"][0]
    assert source["source_state"] == "observation_changed"
    assert source["observation_text"] is None
    assert source["media_digest"] == result["context"][0]["evidence"][0]["media_digest"]


async def test_context_budget_omission_is_explicit_and_never_generates(wiki, mock_gemini_client):
    """WHEN a selected page cannot fit THEN its omission is explicit rather than fake coverage."""
    scope, _, _ = wiki
    result = await wiki_manage({"action": "ask", "question": "mechanism", "context_bytes": 1024,
                               "mode": "gemini", **scope})
    assert result["status"] == "no_evidence"
    assert result["omitted_pages"] == 1
    assert result["context_bytes"] <= 1024
    mock_gemini_client["generate_structured"].assert_not_called()
