"""Render fact-check: verified support vs asserted judgment, load failures, rendered additions, quality split."""

import hashlib
import json

import pytest

from video_explainer_mcp.models.render_factcheck import RenderFactcheckRequest
from video_explainer_mcp.tools.render_factcheck import explainer_render_factcheck

SOURCE = "The demonstration lamp is green. The lamp draws 40 watts."
GREEN, WATTS = "The demonstration lamp is green.", "The lamp draws 40 watts."
OUTPUT = b"fixture bytes standing in for a render output"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_packet(project, claims):
    """Owned original text source with two exact passages."""
    (project / "input").mkdir(parents=True, exist_ok=True)
    (project / "input/lab.txt").write_text(SOURCE)
    digest = sha(SOURCE.encode())
    packet = {"schema_version": 1, "packet_id": "fc", "lineage": [], "claims": claims, "sources": [{
        "id": "lab", "revision": "r1", "sha256": digest, "path": "lab.txt", "modality": "text",
        "asset_kind": "original", "snapshot": {"text": SOURCE, "sha256": digest},
        "passages": [{"id": "p_green", "quote": GREEN}, {"id": "p_watts", "quote": WATTS}]}]}
    (project / "input/evidence-packet.json").write_text(json.dumps(packet))


CLAIMS = [
    {"id": "c_supported", "text": GREEN, "editorial_approved": True,
     "support": [{"source_id": "lab", "passage_id": "p_green"}]},
    {"id": "c_false", "text": "The lamp draws 60 watts.", "editorial_approved": False, "support": []},
    {"id": "c_unsupported", "text": "The lamp was invented in 1802.", "editorial_approved": False, "support": []},
]
JUDGMENTS = [
    {"claim_id": "c_false", "verdict": "false", "method": "fixture_literal", "judge": "fixture-author",
     "correction_refs": [{"source_id": "lab", "passage_id": "p_watts"}]},
    {"claim_id": "c_unsupported", "verdict": "supported", "method": "model_judgment", "judge": "any-model"},
]


def observation(oid, channel, text, claim_ids, start=None, method="fixture"):
    item = {"id": oid, "channel": channel, "text": text, "method": method, "claim_ids": claim_ids}
    return item | ({"start_ms": start, "end_ms": start + 2000} if start is not None else {})


CLEAN = [observation("cap1", "caption", GREEN, ["c_supported"], 0),
         observation("asr1", "voiceover_asr", "the demonstration lamp is green", ["c_supported"], 300, "asr:fixture"),
         observation("ocr1", "frame_ocr", "THE DEMONSTRATION LAMP IS GREEN", ["c_supported"], 0, "ocr:fixture")]


@pytest.fixture()
def project(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    path = root / "fc-project"
    (path / "output").mkdir(parents=True)
    (path / "output/final.mp4").write_bytes(OUTPUT)
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(root))
    write_packet(path, CLAIMS)
    return path


async def run(project, **request):
    return await explainer_render_factcheck(project.name, RenderFactcheckRequest.model_validate(request))


def receipt(digest=sha(OUTPUT), status="completed", path="output/final.mp4"):
    return {"output_path": path, "expected_sha256": digest, "status": status}


async def test_known_claims_carry_references_corrections_and_method(project):
    result = await run(project, judgments=JUDGMENTS, observations=CLEAN)
    claims = {c["claim_id"]: c for c in result["claims"]}
    supported, false, unsupported = claims["c_supported"], claims["c_false"], claims["c_unsupported"]
    assert (supported["factual_status"], supported["status_method"]) == ("supported", "deterministic_exact_quote")
    assert supported["support_references"][0] | {} == {"source_id": "lab", "passage_id": "p_green", "quote": GREEN,
                                                      "source_sha256": sha(SOURCE.encode()), "start_ms": None, "end_ms": None}
    assert supported["judgment"] is None
    assert (false["factual_status"], false["status_method"]) == ("false", "asserted:fixture_literal+verified_correction_quote")
    assert false["judgment"]["verified"] is False and false["judgment"]["judge"] == "fixture-author"
    assert [c["quote"] for c in false["judgment"]["corrections"]] == [WATTS]
    assert unsupported["factual_status"] == "unsupported" and unsupported["verified_support"] == "no_exact_source_text"
    assert "not promoted" in unsupported["judgment"]["issues"][0]
    assert (result["evidence_scope"], result["semantic_support"]) == ("deterministic_literal_fixture_evidence", "not_verified")


async def test_false_verdict_needs_a_verified_correction(project):
    judgment = {"claim_id": "c_false", "verdict": "false", "method": "author_review", "judge": "author"}
    claim = {c["claim_id"]: c for c in (await run(project, judgments=[judgment]))["claims"]}["c_false"]
    assert claim["factual_status"] == "unsupported"
    assert "lacks a verified correction" in claim["judgment"]["issues"][0]


async def test_source_load_failure_is_surfaced_and_never_passes(project):
    (project / "input/lab.txt").unlink()
    result = await run(project, judgments=JUDGMENTS, observations=CLEAN)
    claim = {c["claim_id"]: c for c in result["claims"]}["c_supported"]
    assert result["source_errors"] and claim["verified_support"] == "source_unavailable"
    assert claim["factual_status"] == "unknown" and claim["support_references"][0]["quote"] is None
    false = {c["claim_id"]: c for c in result["claims"]}["c_false"]
    assert false["factual_status"] == "unsupported"  # its correction source failed too
    assert result["quality"]["factual_support"]["status"] == "fail" and result["factual_pass"] is False


async def test_missing_packet_is_a_structured_error(project):
    (project / "input/evidence-packet.json").unlink()
    result = await run(project, observations=CLEAN)
    assert set(result) >= {"error", "category", "hint"} and "factual_pass" not in result


async def test_empty_or_unobserved_input_is_not_a_pass(project):
    write_packet(project, [])
    result = await run(project, observations=CLEAN)
    assert result["quality"]["factual_support"]["status"] == "fail"
    assert "empty input" in result["quality"]["factual_support"]["reasons"][0]
    write_packet(project, CLAIMS)
    result = await run(project)
    assert result["quality"]["factual_support"]["status"] == "UNKNOWN" and result["factual_pass"] is False
    assert result["unobserved_approved_claim_ids"] == ["c_supported"]


@pytest.mark.parametrize("approved,changed", [
    ("Temperature is -5 degrees.", "Temperature is 5 degrees."),
    ("Temperature is −5 degrees.", "Temperature is 5 degrees."),
    ("Value is +5.", "Value is 5."),
    ("Value < 5.", "Value > 5."),
    ("Value ≤ 5.", "Value ≥ 5."),
    ("Value is 5%.", "Value is 5."),
    ("Value is 1/2.", "Value is 1 2."),
    ("Value is .5.", "Value is 5."),
    ("Value is 5-3.", "Value is 5 3."),
    ("The expression is x-y.", "The expression is x y."),
    ("The expression is ab-cd.", "The expression is ab cd."),
])
async def test_rendered_numeric_content_must_match_approved_source(project, monkeypatch, approved, changed):
    monkeypatch.setitem(globals(), "SOURCE", approved + " " + WATTS)
    monkeypatch.setitem(globals(), "GREEN", approved)
    write_packet(project, [CLAIMS[0] | {"text": approved}])
    clean = await run(project, observations=[observation("number", "caption", approved, ["c_supported"])])
    assert clean["factual_pass"] is True
    altered = await run(project, observations=[observation("number", "caption", changed, ["c_supported"])])
    assert altered["factual_pass"] is False
    assert altered["quality"]["factual_support"]["status"] == "fail"


async def test_ambiguous_hyphen_difference_stays_unverified(project, monkeypatch):
    approved = "The cost-effective lamp is green."
    monkeypatch.setitem(globals(), "SOURCE", approved + " " + WATTS)
    monkeypatch.setitem(globals(), "GREEN", approved)
    write_packet(project, [CLAIMS[0] | {"text": approved}])
    unchanged = await run(project, observations=[observation(
        "asr", "voiceover_asr", approved, ["c_supported"], method="asr:fixture")])
    assert unchanged["factual_pass"] is True
    result = await run(project, observations=[observation(
        "asr", "voiceover_asr", "The cost effective lamp is green.", ["c_supported"], method="asr:fixture")])
    assert result["factual_pass"] is False


async def test_rendered_additions_reconciled_against_approved_claims(project):
    observed = CLEAN + [
        observation("asr2", "voiceover_asr", "The demonstration lamp is green, and it never fails!", ["c_supported"], 4000),
        observation("ocr2", "frame_ocr", "The lamp draws 60 watts", ["c_supported"], 4000, "ocr:fixture"),
        observation("ovl1", "overlay_text", "Invented in 1802", [], 4000)]
    result = await run(project, judgments=JUDGMENTS, observations=observed)
    checks = {o["id"]: o for o in result["observations"]}
    assert all(checks[k]["reconciled"] for k in ("cap1", "asr1", "ocr1"))
    assert checks["asr2"]["additions"] == ["and it never fails"] and checks["asr2"]["matched_claim_ids"] == ["c_supported"]
    assert checks["ocr2"]["matched_claim_ids"] == ["c_false"] and checks["ocr2"]["false_claim_ids"] == ["c_false"]
    assert checks["ocr2"]["declared_matches"] is False and checks["ocr2"]["unapproved_claim_ids"] == ["c_false"]
    assert checks["ovl1"]["additions"] == ["invented in 1802"] and not checks["ovl1"]["reconciled"]
    reasons = result["quality"]["factual_support"]["reasons"]
    assert any("and it never fails" in r for r in reasons) and any("c_false" in r for r in reasons)
    assert result["factual_pass"] is False


async def test_quality_dimensions_stay_separate(project):
    result = await run(project, observations=CLEAN, render=receipt())
    quality = result["quality"]
    assert {k: v["status"] for k, v in quality.items()} == {
        "factual_support": "pass", "narration_clarity": "UNKNOWN", "legibility": "pass",
        "synchronization": "pass", "render_completion": "pass"}
    assert quality["synchronization"]["details"][0]["start_delta_ms"] == 300
    result = await run(project, observations=CLEAN, render=receipt("0" * 64), sync_tolerance_ms=100)
    statuses = {k: v["status"] for k, v in result["quality"].items()}
    assert statuses["factual_support"] == "pass" and result["factual_pass"] is True
    assert (statuses["synchronization"], statuses["render_completion"]) == ("fail", "fail")
    result = await run(project, observations=CLEAN[:1])
    assert {k: v["status"] for k, v in result["quality"].items() if k != "factual_support"} == {
        "narration_clarity": "UNKNOWN", "legibility": "UNKNOWN", "synchronization": "UNKNOWN", "render_completion": "UNKNOWN"}


async def test_render_receipt_failures(project):
    for bad in (receipt(status="failed"), receipt(path="../outside.mp4"), receipt(path="output/missing.mp4")):
        dimension = (await run(project, observations=CLEAN, render=bad))["quality"]["render_completion"]
        assert dimension["status"] == "fail" and dimension["reasons"]


async def test_judgments_must_name_distinct_packet_claims(project):
    unknown = {"claim_id": "nope", "verdict": "false", "method": "author_review", "judge": "a"}
    assert "error" in await run(project, judgments=[unknown])
    assert "error" in await run(project, judgments=[JUDGMENTS[1], JUDGMENTS[1]])
