"""Verify local readiness classification, redaction, budgets and read embargo."""

import ast
import copy
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import urllib.request

import pytest

from scripts import inspect_provider_readiness as inspector


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Provide isolated current source and deterministic local presence results."""
    manifest = json.loads((inspector.ROOT / inspector.MANIFEST).read_text())
    paths = [
        inspector.MANIFEST,
        inspector.DEV_INPUTS,
        *manifest["config_sources"].values(),
        *manifest["additional_source_contracts"],
    ]
    for fixture in manifest["development_fixtures"]:
        for source in fixture.get("source_receipts", [fixture]):
            if not Path(source["path"]).is_absolute():
                paths.append(source["path"])
    for name in set(paths):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inspector.ROOT / name, target)
    private_dev = tmp_path / "private-original-development"
    private_dev.mkdir()
    original = private_dev / "test-original.mp4"
    original.write_bytes(b"isolated original development fixture; no provider inference")
    native = manifest["development_fixtures"][-1]
    native["path"], native["sha256"] = str(original), inspector.digest(original)
    manifest["live_run_proposal"]["plans"][1]["source_receipts"] = copy.deepcopy(native)
    (tmp_path / inspector.MANIFEST).write_text(json.dumps(manifest))
    monkeypatch.setattr(inspector, "PRIVATE_DEV_ROOT", private_dev)
    monkeypatch.setattr(inspector.metadata, "version", lambda name: "9.0.0")
    monkeypatch.setattr(inspector.shutil, "which", lambda name: "/private/not-executed")
    env_file = tmp_path / "private.env"
    env_file.write_text("")
    return tmp_path, env_file, manifest


def run(workspace, env=None):
    """Inspect isolated declared inputs with an explicit environment dictionary."""
    root, env_file, _ = workspace
    return inspector.inspect_readiness(root, env={} if env is None else env, env_file=env_file)


def rows(report):
    """Index the compared integration observations."""
    return {row["id"]: row for row in report["integrations"]}


def write_manifest(workspace, manifest):
    """Update only the isolated test manifest for a negative boundary case."""
    (workspace[0] / inspector.MANIFEST).write_text(json.dumps(manifest))


def test_every_adopted_and_optional_group_has_a_honest_state(workspace):
    """GIVEN no credentials THEN local presence and mock output are not live proof."""
    report = run(workspace)
    observed = rows(report)
    assert len(observed) == 27
    assert sum(row["adopted"] for row in observed.values()) == 15
    assert observed["gemini-generation"]["state"] == "missing"
    assert observed["semantic-scholar"]["state"] == "installed"
    assert observed["weaviate-store"]["state"] == "disabled"
    assert observed["explainer-tts"]["state"] == "mocked"
    assert all(row["state"] == "disabled" for row in observed.values() if not row["adopted"])
    assert all(
        row["live_verified"] is False and row["run_authority"] == "not-granted"
        for row in observed.values()
    )
    assert report["provider_calls"] == report["network_requests"] == 0


def test_credential_presence_never_promotes_live_verification(workspace):
    """GIVEN a configured key THEN the service remains configured and unverified."""
    row = rows(run(workspace, {"GEMINI_API_KEY": "secret-key"}))["gemini-generation"]
    assert row["state"] == "configured-but-unverified"
    assert row["credential_presence"] == {"GEMINI_API_KEY": True}
    assert row["live_verified"] is False


def test_secret_endpoint_model_and_path_values_are_redacted(workspace):
    """GIVEN tokens in multiple configuration shapes THEN none reach JSON output."""
    marker = "SECRET-READINESS-987654"
    env = {
        "GEMINI_API_KEY": marker,
        "GEMINI_MODEL": "https://example.invalid/model?token=" + marker,
        "GEMINI_RETRY_MAX_ATTEMPTS": "https://example.invalid/?token=" + marker,
        "WEAVIATE_URL": "https://user:" + marker + "@example.invalid/?token=" + marker,
        "WEAVIATE_API_KEY": marker,
        "MLFLOW_TRACKING_URI": "http://127.0.0.1:5000/?token=" + marker,
        "GEMINI_TRACING_ENABLED": "true",
        "EXPLAINER_PATH": "/private/" + marker,
        "EXPLAINER_TTS_PROVIDER": marker,
        "AGENT_MODEL": marker,
    }
    output = json.dumps(run(workspace, env))
    assert marker not in output
    assert "example.invalid" not in output
    assert "127.0.0.1" not in output
    assert "https://" not in output
    assert "http://" not in output
    assert '"value": "invalid"' in output


def test_dotenv_precedence_is_mirrored_without_environment_injection(workspace):
    """GIVEN a shared env file THEN process values win and placeholders are filled privately."""
    _, env_file, _ = workspace
    env_file.write_text('GEMINI_API_KEY="file-secret"\nGEMINI_RETRY_MAX_ATTEMPTS=1\n')
    supplied = {
        "GEMINI_API_KEY": "process-secret",
        "GEMINI_RETRY_MAX_ATTEMPTS": "${GEMINI_RETRY_MAX_ATTEMPTS}",
    }
    original = dict(supplied)
    before = dict(os.environ)
    report = run(workspace, supplied)
    assert supplied == original
    assert dict(os.environ) == before
    assert (
        rows(report)["gemini-generation"]["config_observation"]["retry_max_attempts"]["value"] == 1
    )
    assert "file-secret" not in json.dumps(report)
    assert "process-secret" not in json.dumps(report)


def test_unresolved_credentials_are_missing(workspace):
    """GIVEN an unresolved shell placeholder THEN it is no configured credential."""
    assert (
        rows(run(workspace, {"GEMINI_API_KEY": "${GEMINI_API_KEY}"}))["gemini-generation"]["state"]
        == "missing"
    )


def test_current_media_limit_is_resolved_from_source_arithmetic(workspace):
    """GIVEN current config byte-size defaults THEN the inspector reports the real bound."""
    row = rows(run(workspace))["gemini-file-api"]
    default = row["config_observation"]["media_max_input_bytes"]
    assert default["environment_variable"] == "MEDIA_MAX_INPUT_BYTES"
    assert default["value"] == 512 * 1024 * 1024
    override = rows(run(workspace, {"MEDIA_MAX_INPUT_BYTES": "6107"}))["gemini-file-api"]
    assert override["config_observation"]["media_max_input_bytes"]["value"] == 6107


def test_ast_default_reader_never_executes_calls():
    """GIVEN executable-looking source syntax THEN it cannot execute during inspection."""
    assert inspector.literal_default(ast.parse("open('private-file')", mode="eval").body) is None


def test_missing_runtime_package_is_not_configured_ready(workspace, monkeypatch):
    """GIVEN credentials but a missing SDK THEN dependency absence wins."""

    def absent(name):
        if name == "google-genai":
            raise metadata.PackageNotFoundError(name)
        return "9.0.0"

    monkeypatch.setattr(inspector.metadata, "version", absent)
    row = rows(run(workspace, {"GEMINI_API_KEY": "secret-key"}))["gemini-generation"]
    assert row["state"] == "missing"
    assert row["packages"]["google-genai"] == {"installed": False, "version": None}


def test_tts_mock_and_real_provider_readiness_remain_distinct(workspace):
    """GIVEN provider selection THEN mock and credential-missing states stay explicit."""
    assert (
        rows(run(workspace, {"EXPLAINER_TTS_PROVIDER": "mock", "ELEVENLABS_API_KEY": "secret"}))[
            "explainer-tts"
        ]["state"]
        == "mocked"
    )
    assert (
        rows(run(workspace, {"EXPLAINER_TTS_PROVIDER": "elevenlabs"}))["explainer-tts"]["state"]
        == "missing"
    )
    assert (
        rows(
            run(workspace, {"EXPLAINER_TTS_PROVIDER": "elevenlabs", "ELEVENLABS_API_KEY": "secret"})
        )["explainer-tts"]["state"]
        == "configured-but-unverified"
    )


def test_renderer_follows_current_source_auto_detection(workspace):
    """GIVEN its source-defined sibling checkout THEN unset EXPLAINER_PATH is not disabled."""
    root = workspace[0] / "packages/video-explainer"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    observed = rows(run(workspace))["explainer-renderer"]
    assert observed["state"] == "missing"
    assert observed["details"]["path_selection"] == "current-source-auto-detection"
    assert observed["details"]["license_clearance"] == "blocked-until-selected-runtime-receipt"


def test_vectorizer_uses_current_source_key_presence_fallback(workspace):
    """GIVEN enabled storage THEN current config chooses its actual fallback provider."""
    observed = rows(run(workspace, {"WEAVIATE_URL": "http://private.invalid"}))
    assert observed["weaviate-vectorizer"]["details"]["vectorizer"] == "weaviate"
    observed = rows(
        run(workspace, {"WEAVIATE_URL": "http://private.invalid", "OPENAI_API_KEY": "secret"})
    )
    assert observed["weaviate-vectorizer"]["details"]["vectorizer"] == "openai"
    observed = rows(
        run(workspace, {"WEAVIATE_URL": "http://private.invalid", "WEAVIATE_VECTORIZER": "openai"})
    )
    assert observed["weaviate-vectorizer"]["state"] == "missing"


def test_alias_credentials_are_presence_only(workspace):
    """GIVEN the supported S2 alias THEN its presence is visible without its value."""
    observed = rows(run(workspace, {"SEMANTIC_SCHOLAR_API_KEY": "alias-secret"}))[
        "semantic-scholar"
    ]
    assert observed["credential_presence"]["SEMANTIC_SCHOLAR_API_KEY"] is True
    assert "alias-secret" not in json.dumps(observed)


def test_inspection_never_requests_network_or_executes_or_writes(workspace, monkeypatch):
    """GIVEN all presence THEN any service request, execution or file write fails the test."""

    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only inspector attempted a side effect")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    report = run(
        workspace,
        {
            "GEMINI_API_KEY": "secret",
            "WEAVIATE_URL": "https://private.invalid",
            "MLFLOW_TRACKING_URI": "https://private.invalid",
            "GEMINI_TRACING_ENABLED": "true",
        },
    )
    assert report["provider_calls"] == report["network_requests"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "authorized",
        "live",
        "spend",
        "attempts",
        "concurrency",
        "nan",
        "negative",
        "aggregate-infinity",
        "aggregate-spend",
        "aggregate-concurrency",
        "aggregate-attempts",
    ],
)
def test_unbounded_or_authorized_manifest_cannot_pass_offline(workspace, change):
    """GIVEN weakened plan limits or a live claim THEN the offline path rejects it."""
    manifest = copy.deepcopy(workspace[2])
    proposal = manifest["live_run_proposal"]
    if change == "authorized":
        proposal["authority"] = "granted"
    elif change == "live":
        manifest["live_verification_receipts"] = [{"status": "success"}]
    elif change == "spend":
        proposal["plans"][0]["allocated_spend_ceiling_usd"] = 100
    elif change == "attempts":
        proposal["plans"][0]["generation_or_synthesis_attempts_max"] = 100
    elif change == "concurrency":
        proposal["plans"][0]["concurrency_max"] = 2
    elif change == "nan":
        proposal["plans"][0]["allocated_spend_ceiling_usd"] = float("nan")
    elif change == "aggregate-infinity":
        proposal["aggregate_spend_ceiling_usd"] = float("inf")
    elif change == "aggregate-spend":
        proposal["aggregate_spend_ceiling_usd"] = 11
    elif change == "aggregate-concurrency":
        proposal["concurrency_max"] = 2
    elif change == "aggregate-attempts":
        proposal["total_generation_or_synthesis_attempts_max"] = float("inf")
    else:
        proposal["plans"][0]["logical_calls_max"] = -1
    write_manifest(workspace, manifest)
    with pytest.raises(ValueError, match="authority|acceptance|ceiling|bound|concurrency"):
        run(workspace)


def test_private_heldout_source_is_rejected_before_reading(workspace, monkeypatch):
    """GIVEN a heldout path THEN the read embargo applies before content hashing."""
    manifest = copy.deepcopy(workspace[2])
    manifest["development_fixtures"][0]["source_receipts"][0]["path"] = (
        "/private/heldout-v1/inputs.json"
    )
    write_manifest(workspace, manifest)
    read = inspector.digest

    def guarded(path):
        assert path != Path("/private/heldout-v1/inputs.json")
        return read(path)

    monkeypatch.setattr(inspector, "digest", guarded)
    with pytest.raises(ValueError, match="only consume declared development"):
        run(workspace)


def test_arbitrary_snapshot_cannot_be_smuggled_into_source_contracts(workspace):
    """GIVEN another private file as code THEN the fixed current-source contract rejects it."""
    manifest = copy.deepcopy(workspace[2])
    manifest["additional_source_contracts"].append("/private/heldout-v1/source-snapshot.txt")
    write_manifest(workspace, manifest)
    with pytest.raises(ValueError, match="Unexpected source contract"):
        run(workspace)


def test_development_hash_drift_blocks_launch_preparation(workspace):
    """GIVEN changed declared source bytes THEN a stale pilot receipt cannot pass."""
    (workspace[0] / "tests/evaluation/fixtures/sources/current.txt").write_text("changed source")
    with pytest.raises(ValueError, match="development artifact hash drift"):
        run(workspace)


def test_development_question_drift_blocks_launch_preparation(workspace):
    """GIVEN changed input questions THEN the exact case/manifest receipt no longer holds."""
    inputs = workspace[0] / inspector.DEV_INPUTS
    cases = json.loads(inputs.read_text())
    cases[0]["question"] = "Unreviewed replacement question"
    inputs.write_text(json.dumps(cases))
    with pytest.raises(ValueError, match="case or input manifest hash drift"):
        run(workspace)


def test_total_plan_bounds_and_source_hashes_are_frozen(workspace):
    """GIVEN the current six drafts THEN one aggregate budget covers all operations."""
    report = run(workspace)
    proposal = workspace[2]["live_run_proposal"]
    assert len(proposal["plans"]) == 6
    assert sum(p["allocated_spend_ceiling_usd"] for p in proposal["plans"]) == 10
    assert sum(p["generation_or_synthesis_attempts_max"] for p in proposal["plans"]) == 10
    assert sum(p["provider_http_operations_max"] for p in proposal["plans"]) == 25
    assert report["source_sha256"]["src/video_research_mcp/config.py"] == inspector.digest(
        workspace[0] / "src/video_research_mcp/config.py"
    )
