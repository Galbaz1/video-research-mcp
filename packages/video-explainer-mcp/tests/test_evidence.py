"""Evidence injection keeps original bytes and separates storage from fact checks."""

from copy import deepcopy
import hashlib
import json
from unittest.mock import patch

import pytest

from video_explainer_mcp.evidence import validate_evidence_packet
from video_explainer_mcp.tools.project import explainer_inject


def packet_fixture(root):
    """Original owned text and a complete exact factual lineage."""
    root.mkdir(exist_ok=True)
    text = "The demonstration lamp is green."
    (root / "original.txt").write_text(text)
    sha = hashlib.sha256(text.encode()).hexdigest()
    packet = {
        "schema_version": 1,
        "packet_id": "owned-packet",
        "sources": [
            {
                "id": "original",
                "revision": "r1",
                "sha256": sha,
                "path": "original.txt",
                "modality": "text",
                "asset_kind": "original",
                "snapshot": {"text": text, "sha256": sha},
                "passages": [{"id": "passage", "quote": text}],
            }
        ],
        "claims": [
            {
                "id": "claim",
                "text": text,
                "editorial_approved": True,
                "support": [{"source_id": "original", "passage_id": "passage"}],
            }
        ],
        "lineage": [],
    }
    parent = "claim"
    for stage in ["script", "narration", "storyboard", "rendered_text"]:
        packet["lineage"].append(
            {
                "id": stage,
                "stage": stage,
                "text": text,
                "claim_ids": ["claim"],
                "parent_ids": [parent],
            }
        )
        parent = stage
    return packet


def configure(monkeypatch, project):
    """Keep every injection under an isolated project root."""
    monkeypatch.setenv("EXPLAINER_PATH", str(project.parent.parent))
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(project.parent))


async def test_packet_injection_retains_bytes_extensions_and_retries(monkeypatch, mock_project_dir):
    project = mock_project_dir()
    configure(monkeypatch, project)
    packet = packet_fixture(project / "input")
    packet["sources"][0]["provider_citation"] = {"unverified": True}
    content = json.dumps(packet, indent=2)
    for _ in range(2):
        result = await explainer_inject(project.name, content, "evidence-packet.json")
        assert "error" not in result
        assert result["evidence_validation"]["contract_passed"] is True
        assert result["evidence_validation"]["factual_success"] is False
        assert (project / "input/evidence-packet.json").read_text() == content


@pytest.mark.parametrize("change", ["missing", "stale", "snapshot", "escape", "malformed"])
async def test_packet_integrity_failure_promotes_no_path_or_overwrite(
    change, monkeypatch, mock_project_dir, tmp_path
):
    project = mock_project_dir()
    configure(monkeypatch, project)
    packet = packet_fixture(project / "input")
    target = project / "input/evidence-packet.json"
    target.write_text("previous packet")
    if change == "missing":
        (project / "input/original.txt").unlink()
    elif change == "stale":
        (project / "input/original.txt").write_text("Changed source")
    elif change == "snapshot":
        packet["sources"][0]["snapshot"]["sha256"] = "0" * 64
    elif change == "escape":
        packet["sources"][0]["path"] = "../../outside.txt"
        (tmp_path / "outside.txt").write_text("outside")
    else:
        packet["schema_version"] = 2
    result = await explainer_inject(project.name, json.dumps(packet), "evidence-packet.json")
    assert "error" in result
    assert "files_written" not in result
    assert target.read_text() == "previous packet"
    assert not list((project / "input").glob(".inject-*"))


async def test_unreviewed_narrative_is_stored_as_flagged_data(monkeypatch, mock_project_dir):
    project = mock_project_dir()
    configure(monkeypatch, project)
    packet = packet_fixture(project / "input")
    packet["lineage"][-1]["text"] += " It cures disease."
    result = await explainer_inject(project.name, json.dumps(packet), "evidence-packet.json")
    assert "error" not in result
    assert result["evidence_validation"]["contract_passed"] is False
    assert result["evidence_validation"]["lineage_errors"]
    assert result["evidence_validation"]["factual_success"] is False


async def test_failed_atomic_promotion_keeps_existing_file(monkeypatch, mock_project_dir):
    project = mock_project_dir()
    configure(monkeypatch, project)
    packet = packet_fixture(project / "input")
    target = project / "input/evidence-packet.json"
    target.write_text("original")
    with patch("video_explainer_mcp.evidence.os.replace", side_effect=OSError("promotion failed")):
        result = await explainer_inject(project.name, json.dumps(packet), "evidence-packet.json")
    assert "error" in result
    assert "files_written" not in result
    assert target.read_text() == "original"
    assert not list((project / "input").glob(".inject-*"))


def test_companion_validator_flags_rendered_voiceover_addition(tmp_path):
    packet = packet_fixture(tmp_path)
    assert validate_evidence_packet(packet, tmp_path)["contract_passed"] is True
    bad = deepcopy(packet)
    bad["lineage"][-1].update(channel="voiceover", text="An unsupported spoken addition.")
    report = validate_evidence_packet(bad, tmp_path)
    assert report["lineage_errors"]
    assert report["contract_passed"] is False
