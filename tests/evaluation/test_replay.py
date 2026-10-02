"""Negative citation, timestamp, denominator and freeze-control regressions."""

import copy
import json
from pathlib import Path

import pytest

from scripts.evaluation.comparison import compare
from scripts.evaluation.models import Case, Label
from scripts.evaluation.replay import replay
from scripts.evaluation.scoring import score_case
from scripts.evaluation.support import evaluator_hash, read_json, sha256
from scripts.validate_capability_programme import validate_source_audit

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = Path(__file__).parent / "fixtures"
PROTOCOL = ROOT / "docs/metrics/multimodal-evaluation-protocol.json"


@pytest.fixture
def frozen_run(tmp_path):
    """Create a receipt for fixed development outputs, without a provider."""
    receipt = {
        "run_id": "development-replay",
        "split": "development",
        "mode": "offline_contract",
        "candidate_revision": "335e8babbeebd783255f67cda2da62b22abb2612",
        "baseline_revision": "a3d75f6ab87bd893c7d167394fb5bace717f23ec",
        "system": "fixture",
        "provider_settings": {"provider": "none"},
        "prompt_sha256": sha256(BUNDLE / "prompt.txt"),
        "protocol_sha256": sha256(PROTOCOL),
        "evaluator_sha256": evaluator_hash(),
        "inputs_sha256": sha256(BUNDLE / "inputs.json"),
        "labels_sha256": sha256(BUNDLE / "labels.json"),
        "outputs_sha256": sha256(BUNDLE / "outputs.json"),
        "source_snapshots_sha256": None,
        "experiment_sha256": sha256(BUNDLE / "experiment.json"),
        "case_ids": [c["id"] for c in read_json(BUNDLE / "inputs.json")],
        "budget": {"provider_calls": 0, "usd": 0},
        "authority_receipt": None,
        "human_audit": {},
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    return path


def fixture_case(case_id="dev-research-current"):
    """Read one public development case, labels and example output."""
    case = next(c for c in read_json(BUNDLE / "inputs.json") if c["id"] == case_id)
    label = read_json(BUNDLE / "labels.json")[case_id]
    output = next(c for c in read_json(BUNDLE / "outputs.json") if c["case_id"] == case_id)
    return Case.model_validate(case), Label.model_validate(label), output


def test_replay_is_deterministic_and_never_claims_superiority(frozen_run):
    """GIVEN frozen outputs WHEN replayed twice THEN all measures match."""
    first = replay(BUNDLE, BUNDLE / "outputs.json", frozen_run, PROTOCOL)
    assert first == replay(BUNDLE, BUNDLE / "outputs.json", frozen_run, PROTOCOL)
    assert first["summary"]["completion"] == 1
    assert first["summary"]["cost_usd"] is None
    assert first["summary"]["cost_usd_observed_cases"] == 0
    comparison = compare(first, first, read_json(PROTOCOL))
    assert comparison["material_advantage"] is False
    assert comparison["numerical_criteria_passed"] is False


@pytest.mark.parametrize("corruption", ["unrelated", "invented", "wrong_source", "wrong_fact"])
def test_citation_judge_rejects_false_support(corruption):
    """GIVEN a correct-looking answer WHEN citation support is false THEN it fails."""
    case, label, output = fixture_case()
    claim = output["claims"][0]
    if corruption == "unrelated":
        claim["citations"][0]["quote"] = "The earlier trial used 8 units."
    elif corruption == "invented":
        claim["citations"][0]["quote"] = "the trial used 120 units."
    elif corruption == "wrong_source":
        claim["citations"][0]["source_id"] = "stale"
    else:
        claim["text"] = "The Atlas trial used 8 units."
    result = score_case(case, label, output, BUNDLE, 500)
    assert result["facts_supported"] == 0
    assert result["citations_supported"] == 0
    assert result["complete"] is False


def test_extra_false_citation_and_duplicate_claim_cannot_pass():
    case, label, output = fixture_case()
    output["claims"][0]["citations"].append({"source_id": "current", "quote": "wrong"})
    assert not score_case(case, label, output, BUNDLE, 500)["complete"]
    output["claims"][0]["citations"].pop()
    output["claims"].append(copy.deepcopy(output["claims"][0]))
    result = score_case(case, label, output, BUNDLE, 500)
    assert result["facts_correct"] == 1
    assert result["claims"] == 2
    assert not result["complete"]


def test_temporal_correctness_is_independent_of_prose():
    case, label, output = fixture_case("dev-visual-time")
    output["temporal"][0]["start_ms"] += 501
    result = score_case(case, label, output, BUNDLE, 500)
    assert result["facts_correct"] == result["facts_supported"] == 1
    assert result["temporal_correct"] == 0
    assert not result["complete"]


def test_fabricated_answer_to_absent_evidence_is_not_abstention():
    case, label, output = fixture_case("dev-research-absent")
    output["status"] = "ok"
    output["claims"] = [{"fact_id": "shipment", "text": "Tomorrow", "citations": []}]
    result = score_case(case, label, output, BUNDLE, 500)
    assert not result["abstention_correct"]
    assert not result["complete"]


def test_failures_and_missing_outputs_stay_in_denominator(frozen_run, tmp_path):
    rows = read_json(BUNDLE / "outputs.json")[:-1]
    rows[0]["status"] = "timeout"
    rows[1] = {"case_id": rows[1]["case_id"], "unexpected": "invalid schema"}
    outputs = tmp_path / "outputs.json"
    outputs.write_text(json.dumps(rows))
    receipt = read_json(frozen_run)
    receipt["outputs_sha256"] = sha256(outputs)
    frozen_run.write_text(json.dumps(receipt))
    report = replay(BUNDLE, outputs, frozen_run, PROTOCOL)
    counts = report["summary"]["statuses"]
    assert report["summary"]["cases"] == 15
    assert counts["timeout"] == 2
    assert counts["invalid"] == counts["missing"] == 1
    assert report["summary"]["calls"] is None


@pytest.mark.parametrize(
    "field",
    [
        "protocol_sha256",
        "evaluator_sha256",
        "inputs_sha256",
        "labels_sha256",
        "outputs_sha256",
        "case_ids",
    ],
)
def test_run_control_drift_is_rejected(frozen_run, field):
    receipt = read_json(frozen_run)
    receipt[field] = [] if field == "case_ids" else "f" * 64
    frozen_run.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="changed|denominator"):
        replay(BUNDLE, BUNDLE / "outputs.json", frozen_run, PROTOCOL)


def test_duplicate_or_extra_attempt_is_rejected(frozen_run, tmp_path):
    rows = read_json(BUNDLE / "outputs.json")
    rows.append(copy.deepcopy(rows[0]))
    path = tmp_path / "outputs.json"
    path.write_text(json.dumps(rows))
    receipt = read_json(frozen_run)
    receipt["outputs_sha256"] = sha256(path)
    frozen_run.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="duplicate attempt"):
        replay(BUNDLE, path, frozen_run, PROTOCOL)


def test_source_drift_and_path_escape_are_rejected():
    case, label, output = fixture_case()
    case.sources[0].sha256 = "0" * 64
    with pytest.raises(ValueError, match="source hash"):
        score_case(case, label, output, BUNDLE, 500)
    case.sources[0].path = "../outside.txt"
    with pytest.raises(ValueError, match="escapes"):
        score_case(case, label, output, BUNDLE, 500)


def test_empty_input_cannot_be_success_or_undefined_precision_perfect():
    case, label, output = fixture_case("dev-research-absent")
    label.expected_status = "ok"
    with pytest.raises(ValueError, match="empty input"):
        score_case(case, label, output, BUNDLE, 500)


def test_comparison_rejects_unmatched_budget(frozen_run):
    first = replay(BUNDLE, BUNDLE / "outputs.json", frozen_run, PROTOCOL)
    second = copy.deepcopy(first)
    second["receipt"]["budget"]["usd"] = 10
    with pytest.raises(ValueError, match="budget"):
        compare(first, second, read_json(PROTOCOL))


def test_protocol_covers_frozen_inventory_and_all_families():
    protocol = read_json(PROTOCOL)
    inventory_path = ROOT / "docs/research/2026-09-30-capability-transfer.json"
    inventory = read_json(inventory_path)
    # This is the original inventory at freeze_source; target paths may evolve.
    assert protocol["inventory_sha256"] == "deacee9b11e9b853a6534949320b5c708c2f72c40413c84bcfc3170a83da6683"
    for name, lane in inventory["source_lanes"].items():
        validate_source_audit(name, lane)
    # Native Codex installation was added after the comparison cohort was frozen.
    assert "codex-install" not in protocol["workflows"]
    assert set(protocol["workflows"]) | {"codex-install"} == {
        p["key"] for p in inventory["work_packages"]
    }
    assert set(protocol["families"]) == {p["family"] for p in inventory["work_packages"]}
    assert protocol["minimum_cases_per_family"] == 30


def test_claim_ids_are_not_hidden_label_requirements():
    case, label, output = fixture_case()
    output["claims"][0]["fact_id"] = "candidate-generated-id"
    assert score_case(case, label, output, BUNDLE, 500)["complete"]


def test_cross_source_claim_requires_every_labeled_source():
    case, label, output = fixture_case("dev-cross-video")
    assert score_case(case, label, output, BUNDLE, 500)["complete"]
    output["claims"][0]["citations"].pop()
    result = score_case(case, label, output, BUNDLE, 500)
    assert result["citations_supported"] == 1
    assert result["facts_supported"] == 0
    assert not result["complete"]


def test_unknown_usage_does_not_discard_a_supported_answer(frozen_run, tmp_path):
    rows = read_json(BUNDLE / "outputs.json")
    for key in ("latency_ms", "calls", "auxiliary_calls"):
        rows[0][key] = None
    path = tmp_path / "outputs.json"
    path.write_text(json.dumps(rows))
    receipt = read_json(frozen_run)
    receipt["outputs_sha256"] = sha256(path)
    frozen_run.write_text(json.dumps(receipt))
    report = replay(BUNDLE, path, frozen_run, PROTOCOL)
    assert report["cases"][0]["complete"]
    assert report["cases"][0]["facts_correct"] == 1
    assert report["summary"]["calls"] is None
    assert report["summary"]["calls_observed_cases"] == len(rows) - 1


def test_invalid_answer_retains_observed_calls_and_cost():
    case, label, output = fixture_case()
    output["claims"] = "malformed answer"
    output["calls"] = 2
    output["auxiliary_calls"] = 3
    output["cost_usd"] = 0.12
    result = score_case(case, label, output, BUNDLE, 500)
    assert result["status"] == "invalid"
    assert result["usage"]["calls"] == 2
    assert result["usage"]["auxiliary_calls"] == 3
    assert result["usage"]["cost_usd"] == 0.12


def test_separately_frozen_specialist_settings_are_comparable(frozen_run, tmp_path):
    first = replay(BUNDLE, BUNDLE / "outputs.json", frozen_run, PROTOCOL)
    receipt = read_json(frozen_run)
    receipt["system"] = "specialist-fixture"
    receipt["provider_settings"] = {"provider": "another-offline-fixture"}
    path = tmp_path / "baseline-receipt.json"
    path.write_text(json.dumps(receipt))
    second = replay(BUNDLE, BUNDLE / "outputs.json", path, PROTOCOL)
    assert compare(first, second, read_json(PROTOCOL))["material_advantage"] is False
    receipt["provider_settings"] = {"provider": "unfrozen"}
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="system settings"):
        replay(BUNDLE, BUNDLE / "outputs.json", path, PROTOCOL)


def test_media_support_binds_separate_snapshot_and_original_asset(tmp_path):
    """GIVEN media evidence WHEN its binding changes THEN support cannot pass."""
    asset = tmp_path / "sound.wav"
    import wave

    with wave.open(str(asset), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 800)
    snapshot = tmp_path / "observations.txt"
    snapshot.write_text("A silent segment occupies 0 through 100 ms.")
    index = {
        "audio": {"path": snapshot.name, "sha256": sha256(snapshot), "asset_sha256": sha256(asset)}
    }
    (tmp_path / "source-snapshots.json").write_text(json.dumps(index))
    case = Case(
        id="audio-case",
        family="Audio",
        workflow="events",
        modalities=["audio"],
        question="Describe segment",
        sources=[
            {
                "id": "audio",
                "path": asset.name,
                "sha256": sha256(asset),
                "modality": "audio",
                "content_type": "audio/wav",
            }
        ],
        sampling={"temporal_targets": ["segment"]},
    )
    evidence = {"source_id": "audio", "quote": snapshot.read_text(), "start_ms": 0, "end_ms": 100}
    label = Label(
        facts=[{"id": "hidden-fact", "text": "The segment is silent.", "evidence": [evidence]}],
        expected_abstention=False,
        temporal=[],
        required_artifacts=[],
        expected_status="ok",
    )
    _, _, output = fixture_case()
    output["case_id"] = case.id
    output["claims"] = [
        {
            "fact_id": "own-id",
            "text": "The segment is silent.",
            "citations": [{**evidence, "quote": None}],
        }
    ]
    assert score_case(case, label, output, tmp_path, 500)["complete"]
    output["claims"][0]["citations"][0]["end_ms"] = 200
    assert not score_case(case, label, output, tmp_path, 500)["complete"]
    index["audio"]["asset_sha256"] = "0" * 64
    (tmp_path / "source-snapshots.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="snapshot hash"):
        score_case(case, label, output, tmp_path, 500)
