"""Verified citation text must not assert support for a different caller claim."""

import os
from pathlib import Path

import pytest

from tests.test_grounding_support import cite, claim, grounding_request
from tests.test_grounding_support import grounding_corpus as grounding_corpus
from tests.test_grounding_escalation import case as case, run as run_escalation
from tests.test_temporal_ocr_mcp import scene_fixture as scene_fixture
from video_research_mcp import grounding, grounding_escalation
from video_research_mcp.tools.grounding import grounded_answer


@pytest.mark.parametrize("text", [
    "The copper circuit is closed", "The circuit is open", "The warning light is off", " \t ",
])
async def test_different_claim_keeps_semantic_support_unverified(grounding_corpus, text):
    """A true quotation alone cannot verify either a contradiction or a paraphrase."""
    result = await grounded_answer(request=grounding_request(
        grounding_corpus, "copper circuit",
        [claim("c1", text, cite("speech-1", 0.2, 0.8, "copper circuit is open"))],
    ))
    assert result["claims"][0]["citations"][0]["quote_verified"] is True
    assert result["claims"][0]["support"] == "citation_available_semantics_unverified"
    assert result["status"] == "partially_grounded"
    assert result["missing_evidence"] == [
        {"scope": "claim", "claim_id": "c1", "reason": "no_verbatim_support"},
    ]


async def test_exact_claim_quote_allows_only_whitespace_normalization(grounding_corpus):
    """The grounded label verifies the caller's exact text in the retrieved observation."""
    result = await grounded_answer(request=grounding_request(
        grounding_corpus, "copper circuit",
        [claim("c1", "copper   circuit is open", cite("speech-1", 0.2, 0.8, "copper circuit is open"))],
    ))
    assert result["claims"][0]["support"] == "verbatim_quote"
    assert result["status"] == "grounded" and result["missing_evidence"] == []


async def test_blank_quote_cannot_support_any_claim(grounding_corpus):
    """Whitespace contains no evidence and cannot repair a missing quotation."""
    result = await grounded_answer(request=grounding_request(
        grounding_corpus, "copper circuit",
        [claim("c1", "The circuit is closed", cite("speech-1", 0.2, 0.8, " \t "))],
    ))
    assert result["status"] == "abstained"
    assert result["claims"][0]["support"] == "unsupported"
    assert result["claims"][0]["rejected"] == [
        {"citation_index": 0, "reason": "quote_not_in_observation"},
    ]


async def test_cleanup_refusal_preserves_budget_stop_and_frame_receipt(case, monkeypatch):
    """A cleanup failure must retain the primary refusal and the still-owned artifact."""
    real = grounding_escalation.frame_at

    async def oversized(*args, **kwargs):
        metadata = await real(*args, **kwargs)
        metadata["frames"][0]["bytes"] = 5 * 1024 * 1024
        return metadata

    def refuse_cleanup(*args):
        raise PermissionError("fixture cleanup refusal")

    monkeypatch.setattr(grounding_escalation, "frame_at", oversized)
    monkeypatch.setattr(grounding_escalation, "_discard_views", refuse_cleanup)
    result = await run_escalation(case)
    report = result["escalation"]
    assert report["status"] == "stopped" and report["stop_reason"] == "byte_budget"
    (attempt,) = report["attempts"]
    assert attempt["status"] == "discarded_byte_budget"
    assert attempt["actual_seconds"] == pytest.approx(0.2)
    assert attempt["original_pts"] == 7200 and attempt["source"]["sha256"] == case[1]["digest"]
    assert attempt["cleanup_error"]["category"] == "PERMISSION_DENIED"
    assert Path(attempt["cleanup_error"]["artifact"]["path"]).is_file()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX file substitution boundary")
def test_hash_refuses_regular_file_replaced_by_fifo_without_blocking(tmp_path, monkeypatch):
    """The open must be nonblocking and reject a changed fd before reading it."""
    source = tmp_path / "source.json"
    source.write_bytes(b"fixture")
    original_open = os.open

    def substitute(path, flags, *args, **kwargs):
        if Path(path) == source:
            # Fail before substitution on the unsafe preimage, avoiding a hung test.
            assert flags & os.O_NONBLOCK
            source.unlink()
            os.mkfifo(source)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", substitute)
    with pytest.raises(PermissionError, match="regular files"):
        grounding._bounded_digest(source, 7)
