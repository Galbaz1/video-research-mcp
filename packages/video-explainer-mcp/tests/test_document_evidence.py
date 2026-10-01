"""Located extraction wire compatibility at the standalone planning boundary."""

from copy import deepcopy
import hashlib
import json

import pytest

from video_explainer_mcp.evidence import validate_evidence_packet
from video_explainer_mcp.models.evidence import EvidencePacket
from video_explainer_mcp.models.ingestion_location import IngestionLocation


def document_packet(root):
    """Build explicit synthetic binary-original observations, without a parser claim."""
    original = b"Synthetic binary fixture; source revision stays separate from observation."
    (root / "original.docx").write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    location = IngestionLocation(table=0, row=1, column=0).model_dump(mode="json")
    quote, method = "Measured cell", "fixture-ooxml-cell"
    passage = {"id": "cell", "quote": quote, "start_ms": None, "end_ms": None,
               "location": location, "method": method}
    record = {"asset_sha256": digest, "revision": "r1", "observed_intervals": [],
              "passages": [{k: passage[k] for k in ("id", "quote", "start_ms", "end_ms")}],
              "locations": {"cell": location}, "methods": {"cell": method},
              "extraction_sha256": "e" * 64}
    snapshot = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return {"packet_id": "located-document", "sources": [{
        "id": "original", "revision": "r1", "sha256": digest, "path": "original.docx",
        "modality": "document", "asset_kind": "original", "passages": [passage],
        "snapshot": {"text": snapshot, "sha256": hashlib.sha256(snapshot.encode()).hexdigest()},
        "extraction_sha256": "e" * 64,
    }], "claims": [{"id": "cell-claim", "text": quote,
                     "support": [{"source_id": "original", "passage_id": "cell"}]}]}


def test_document_observations_keep_binary_original_separate(tmp_path):
    """GIVEN located binary observations WHEN admitted THEN positions survive unchanged."""
    packet = document_packet(tmp_path)
    validated = EvidencePacket.model_validate(packet).model_dump(mode="json")
    result = validate_evidence_packet(validated, tmp_path)
    assert result["source_errors"] == []
    assert result["claim_support"]["cell-claim"] == "exact_source_text"
    assert validated["sources"][0]["passages"][0]["location"]["row"] == 1


@pytest.mark.parametrize("field,value", [
    ("location", {"row": 1}),
    ("location", {"page": 1, "bbox": [0.0, 0.0, 4.0, 4.0]}),
    ("location", {"table": 0, "row": 2, "column": 0}),
    ("location", {"coordinate_origin": "top_left"}),
    ("method", "invented-method"),
])
def test_document_mutation_cannot_become_source_support(tmp_path, field, value):
    """GIVEN changed locations or methods WHEN checked THEN source support is unknown."""
    packet = document_packet(tmp_path)
    packet["sources"][0]["passages"][0][field] = value
    result = validate_evidence_packet(packet, tmp_path)
    assert result["source_errors"]
    assert result["claim_support"]["cell-claim"] == "unknown"


def test_document_scalar_snapshot_returns_issues(tmp_path):
    """GIVEN malformed externally supplied observations THEN validation rejects cleanly."""
    packet = document_packet(tmp_path)
    packet["sources"][0]["snapshot"] = {
        "text": "[]", "sha256": hashlib.sha256(b"[]").hexdigest(),
    }
    result = validate_evidence_packet(packet, tmp_path)
    assert any("JSON observation object" in issue for issue in result["source_errors"])


def test_text_original_does_not_gain_binary_observation_semantics(tmp_path):
    """GIVEN the old text modality THEN original/snapshot equality remains mandatory."""
    packet = deepcopy(document_packet(tmp_path))
    packet["sources"][0]["modality"] = "text"
    result = validate_evidence_packet(packet, tmp_path)
    assert any("snapshot" in issue for issue in result["source_errors"])
