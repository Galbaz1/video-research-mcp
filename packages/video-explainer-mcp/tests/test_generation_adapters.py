"""Finite selected mocked lifecycle and one opt-in deterministic native decode."""

import asyncio
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import wave
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from video_explainer_mcp import config, generation as service, generation_assets as assets
from video_explainer_mcp import generation_request as admission
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.models.generation import GenerationOperation, GenerationRequest
from video_explainer_mcp.planning_sources import digest
from video_explainer_mcp.tools.generation import (
    explainer_generation_cancel, explainer_generation_poll, explainer_generation_submit,
    generation_server,
)

BASE = "https://fixture.ap-southeast-1.maas.aliyuncs.com/api/v1"
URL = "https://dashscope-result-sh.oss-accelerate.aliyuncs.com/fixture.mp4?Signature=private-output-token"


def sha(body):
    return hashlib.sha256(body).hexdigest()


def operation(name):
    return GenerationOperation(operation_id=name, principal="fixture-caller", authorize=True)


def task(status="PENDING", **output):
    return httpx.Response(200, json={"request_id": "safe-request", "output": {
        "task_id": "provider-task", "task_status": status, **output}})


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """Provide only first-party project inputs and a closed mocked HTTP transport."""
    project = tmp_path / "fixture"
    project.mkdir()
    for name in ("script.json", "scene.json"):
        (project / name).write_text(json.dumps({"id": name, "label": "first-party fixture"}))
    config._config = SimpleNamespace(projects_path=str(tmp_path), explainer_enabled=False,
                                     resolved_projects_path=tmp_path, dashscope_api_key="private-api-token",
                                     dashscope_base_url=BASE)
    # Default source mocks must not depend on an installed native decoder.
    monkeypatch.setattr(service, "executable_identity", lambda: {"fixture": "mocked decoder readiness"})
    responses, requests = [], []

    async def handler(request):
        requests.append(request)
        assert responses, "Unexpected HTTP request; no network fallback exists"
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(assets, "http_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False, timeout=10))
    return project, requests, responses, datetime.now(timezone.utc)


def pinned_json(project, name, value):
    """Pin exact synthetic operator JSON without asserting a real provider price."""
    body = json.dumps(value, sort_keys=True).encode()
    (project / name).write_bytes(body)
    return {"path": name, "sha256": sha(body)}


def quote_fixture(wire, req, **changes):
    project, _, _, now = wire
    common = dict(evidence_kind="operator_declaration", provider="dashscope", model=req.model,
                  principal="fixture-caller", recorded_at=now.isoformat(),
                  source_revision="SYNTHETIC_TEST_ONLY_NOT_PROVIDER_EVIDENCE")
    price = pinned_json(project, "price-source.json", {**common, "resolution": req.resolution,
        "currency": "USD", "price_per_second": "0.01",
        "source_url": "https://www.alibabacloud.com/help/en/model-studio/model-pricing"})
    access = pinned_json(project, "access-source.json", {**common, "api_origin": BASE,
        "access": "operator_declares_access", "source_url": BASE + "/tasks/operator-declared-evidence"})
    body = req.model_dump(mode="json")
    body.pop("quote")
    value = dict(evidence_kind="operator_declaration", provider="dashscope", api_origin=BASE,
                 model=req.model, resolution=req.resolution, currency="USD", price_per_second="0.01",
                 principal="fixture-caller", request_sha256=digest(body), contract_sha256=digest(admission.CONTRACT),
                 issued_at=now.isoformat(), valid_until=(now + timedelta(hours=1)).isoformat(),
                 price_source=price, model_access_source=access)
    value.update(changes)
    return pinned_json(project, "quote.json", value)


def request(wire, **changes):
    project = wire[0]
    value = dict(logical_job_id="one-logical-job", operation=operation("submit-1"), prompt="A red fixture",
                 quote={"path": "quote.json", "sha256": "0" * 64},
                 duration=2, script_id="script-1", scene_id="scene-1", seed=42,
                 script={"path": "script.json", "sha256": sha((project / "script.json").read_bytes())},
                 scene={"path": "scene.json", "sha256": sha((project / "scene.json").read_bytes())},
                 spend_authorized=True, max_cost="0.10", currency="USD")
    value.update(changes)
    req = GenerationRequest.model_validate(value)
    if "quote" not in changes:
        value["quote"] = quote_fixture(wire, req)
    return GenerationRequest.model_validate(value)


async def start(wire, **changes):
    wire[2].append(task())
    return await explainer_generation_submit("fixture", request(wire, **changes))


def metadata(**changes):
    video = {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720,
             "duration": "2.0", "sample_aspect_ratio": "1:1"}
    video.update(changes)
    return json.dumps({"streams": [video, {"codec_type": "audio", "codec_name": "aac", "duration": "2.0"}],
                       "format": {"duration": "2.0"}}).encode()


async def test_submit_pending_reload_conflict_and_one_post(wire):
    first = await start(wire)
    assert first["status"] == "running" and first["provider_operation_id"] == "provider-task"
    payload = json.loads(wire[1][0].content)
    assert payload["parameters"] == dict(duration=2, resolution="720P", ratio="16:9", seed=42,
                                         prompt_extend=False, watermark=True)
    assert wire[1][0].headers["X-DashScope-Async"] == "enable"
    importlib.reload(service)
    assert (await explainer_generation_submit("fixture", request(wire)))["job_id"] == first["job_id"]
    conflict = await explainer_generation_submit("fixture", request(wire, prompt="different"))
    assert "error" in conflict and len(wire[1]) == 1
    wire[2].append(task("RUNNING"))
    polled = await explainer_generation_poll(first["job_id"], operation("poll-1"))
    assert polled["state"]["submit_count"] == 1 and polled["state"]["poll_count"] == 1
    assert polled["state"]["request"] == request(wire).model_dump(mode="json")
    await explainer_generation_poll(first["job_id"], operation("poll-1"))
    assert len(wire[1]) == 2


@pytest.mark.parametrize("phase", ["submit", "poll"])
async def test_timeout_preserves_unknown_and_no_replay(wire, phase):
    if phase == "poll":
        first = await start(wire)
    wire[2].append(httpx.ReadTimeout("private-api-token " + URL))
    result = (await explainer_generation_submit("fixture", request(wire)) if phase == "submit"
              else await explainer_generation_poll(first["job_id"], operation("poll-timeout")))
    assert result["status"] == "unknown" and result["state"]["submit_count"] == 1
    assert "private-api-token" not in json.dumps(result) and "private-output-token" not in json.dumps(result)
    await explainer_generation_submit("fixture", request(wire))
    if phase == "submit":
        await explainer_generation_poll(result["job_id"], operation("no-external-id"))
        assert result["provider_operation_id"] is None
    assert len([r for r in wire[1] if r.method == "POST"]) == 1


async def test_crash_after_post_before_external_checkpoint_is_not_retried(wire, monkeypatch):
    original = service._save
    failed = False

    def checkpoint(*args, **kwargs):
        nonlocal failed
        if kwargs.get("external_id") and not failed:
            failed = True
            raise RuntimeError("Simulated crash after first POST")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_save", checkpoint)
    first = await start(wire)
    assert first["status"] == "unknown" and first["provider_operation_id"] is None
    monkeypatch.setattr(service, "_save", original)
    await explainer_generation_submit("fixture", request(wire))
    assert len(wire[1]) == 1 and first["state"]["submit_count"] == 1


@pytest.mark.parametrize("state", ["FAILED", "UNKNOWN"])
async def test_provider_failure_and_unknown_are_retained(wire, state):
    first = await start(wire)
    wire[2].append(task(state))
    result = await explainer_generation_poll(first["job_id"], operation("poll-1"))
    assert result["status"] == ("failed" if state == "FAILED" else "unknown")
    assert result["provider_operation_id"] == "provider-task" and result["request_sha256"] == first["request_sha256"]
    await explainer_generation_submit("fixture", request(wire))
    assert len(wire[1]) == 2


@pytest.mark.parametrize("confirmed", ["CANCELED", "RUNNING"])
async def test_cancel_json_string_ack_requires_fetch(wire, confirmed):
    first = await start(wire)
    wire[2].extend([task(), httpx.Response(200, json="cancel-request"), task(confirmed)])
    result = await explainer_generation_cancel(first["job_id"], operation("cancel-1"))
    assert result["status"] == ("cancelled" if confirmed == "CANCELED" else "running")
    assert result["state"]["cancellation_confirmed"] == (confirmed == "CANCELED")
    assert result["state"]["cancel_count"] == 1 and result["state"]["poll_count"] == 2
    assert result["state"]["cancel_ack_request_id"] == "cancel-request"
    await explainer_generation_cancel(first["job_id"], operation("cancel-2"))
    assert len(wire[1]) == 4


async def test_cancel_object_ack_and_running_refusal(wire):
    first = await start(wire)
    wire[2].append(task("RUNNING"))
    result = await explainer_generation_cancel(first["job_id"], operation("cancel-running"))
    assert result["status"] == "running" and result["state"]["cancel_count"] == 0
    wire[2].extend([task(), httpx.Response(200, json={"request_id": "wrong-object"})])
    result = await explainer_generation_cancel(first["job_id"], operation("cancel-object"))
    assert result["status"] == "unknown" and "cancel_ack_request_id" not in result["state"]
    assert result["state"]["cancel_count"] == 1


async def test_config_origin_change_between_cancel_fetch_and_post_refuses(wire, monkeypatch):
    first = await start(wire)

    async def transport(sent):
        assert sent.method == "GET"
        wire[1].append(sent)
        config._config.dashscope_base_url = "https://foreign.cn-beijing.maas.aliyuncs.com/api/v1"
        return task()

    monkeypatch.setattr(assets, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    result = await explainer_generation_cancel(first["job_id"], operation("origin-change"))
    assert result["status"] == "unknown" and result["state"]["cancel_count"] == 0
    assert len(wire[1]) == 2 and len([r for r in wire[1] if r.method == "POST"]) == 1


async def test_poll_budget_and_operation_action_binding(wire):
    first = await start(wire, max_polls=2)
    for name in ("poll-1", "poll-2"):
        wire[2].append(task())
        await explainer_generation_poll(first["job_id"], operation(name))
    result = await explainer_generation_poll(first["job_id"], operation("over-budget"))
    assert "error" in result and len(wire[1]) == 3
    result = await explainer_generation_cancel(first["job_id"], operation("poll-1"))
    assert "error" in result and len(wire[1]) == 3


@pytest.mark.parametrize("changes", [
    {"duration": 1}, {"duration": 16}, {"duration": 2.5}, {"duration": True},
    {"resolution": "480P"}, {"ratio": "2:1"}, {"seed": -1}, {"seed": 2147483648},
    {"prompt": "x" * 5001}, {"negative_prompt": "x" * 501}, {"max_cost": "NaN"},
    {"references": [{"role": "unsupported", "source": {"path": "missing", "sha256": "0" * 64}}]},
])
async def test_schema_limits_before_submit(wire, changes):
    with pytest.raises(ValidationError):
        request(wire, **changes)
    assert wire[1] == []


@pytest.mark.parametrize("changes", [
    {"transparent_background": True}, {"model": "wan2.7-i2v"}, {"expected_audio": "absent"},
    {"spend_authorized": False}, {"operation": GenerationOperation(operation_id="none", principal="fixture-caller")},
    {"max_cost": "0.001"}, {"currency": "CNY"},
    {"script": {"path": "missing", "sha256": "0" * 64}},
    {"scene": {"path": "../foreign", "sha256": "0" * 64}},
    {"script": {"path": "script.json", "sha256": "0" * 64}},
    {"continuation": {"path": "missing", "sha256": "0" * 64}},
    {"references": [{"role": "identity", "source": {"path": "missing", "sha256": "0" * 64}}]},
])
async def test_refusals_and_reference_integrity_before_counter(wire, changes):
    result = await explainer_generation_submit("fixture", request(wire, **changes))
    assert "error" in result and wire[1] == []


async def test_missing_quote_and_empty_configuration(wire):
    req = request(wire)
    (wire[0] / "quote.json").unlink()
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and wire[1] == []
    config._config.dashscope_api_key = ""
    result = await explainer_generation_submit("fixture", request(wire))
    assert "not configured" in result["error"] and wire[1] == []


@pytest.mark.parametrize("changes", [
    {"provider": "foreign"}, {"principal": "foreign"}, {"api_origin": "https://foreign.invalid/api/v1"},
    {"model": "wan2.7-i2v"}, {"resolution": "1080P"}, {"currency": "CNY"},
    {"price_per_second": "0"}, {"price_per_second": "-1"}, {"price_per_second": "NaN"},
    {"price_per_second": "Infinity"}, {"price_per_second": "0.02"},
    {"valid_until": "2000-01-01T00:00:00+00:00"}, {"valid_until": "2030-01-01T00:00:00"},
    {"request_sha256": "0" * 64}, {"contract_sha256": "0" * 64},
    {"model_access_source": {"path": "missing", "sha256": "0" * 64}},
])
async def test_real_quote_reader_refuses_invalid_operator_declarations(wire, changes):
    req = request(wire)
    quote = quote_fixture(wire, req, **changes)
    req = GenerationRequest.model_validate({**req.model_dump(mode="json"), "quote": quote})
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and wire[1] == []


@pytest.mark.parametrize("source", ["price-source.json", "access-source.json", "quote.json"])
async def test_quote_source_integrity_is_actual_local_hash(wire, source):
    req = request(wire)
    (wire[0] / source).write_text("{}")
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and wire[1] == []


async def test_actual_quote_calculation_and_declaration_labels(wire):
    req = request(wire, max_cost="0.02")
    quote = admission.read_operator_quote(wire[0], req, BASE)
    assert quote["total_cost"] == "0.02" and quote["evidence_kind"] == "operator_declaration"
    assert quote["provider_verification"] == "UNQUALIFIED" and quote["principal_authentication"] == "UNQUALIFIED"
    wire[2].append(task())
    result = await explainer_generation_submit("fixture", req)
    saved = JobStore().get(result["job_id"])
    assert saved["request"]["quote"] == quote and len(wire[1]) == 1
    (wire[0] / "price-source.json").unlink()
    replay = await explainer_generation_submit("fixture", req)
    assert replay["job_id"] == result["job_id"] and len(wire[1]) == 1


@pytest.mark.parametrize("filename,field,value", [
    ("price-source.json", "principal", "foreign"), ("access-source.json", "principal", "foreign"),
    ("access-source.json", "api_origin", "https://foreign.invalid/api/v1"),
    ("access-source.json", "recorded_at", "2030-01-01T00:00:00+00:00"),
    ("price-source.json", "currency", "CNY"), ("access-source.json", "access", "UNKNOWN"),
    ("price-source.json", "source_revision", ""),
    ("price-source.json", "source_url", "https://www.alibabacloud.com:private-api-token/help/en/model-studio/model-pricing"),
])
async def test_evidence_provenance_is_checked_after_valid_hash(wire, filename, field, value):
    req = request(wire)
    source = json.loads((wire[0] / filename).read_text())
    source[field] = value
    changed = pinned_json(wire[0], filename, source)
    quote = json.loads((wire[0] / "quote.json").read_text())
    quote["price_source" if filename.startswith("price") else "model_access_source"] = changed
    ref = pinned_json(wire[0], "quote.json", quote)
    req = GenerationRequest.model_validate({**req.model_dump(mode="json"), "quote": ref})
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and wire[1] == [] and "private-api-token" not in json.dumps(result)


async def test_actual_full_decode_eof_mismatch_retains_hash(wire, monkeypatch):
    first = await start(wire)
    wire[2].extend([task("SUCCEEDED", video_url=URL), httpx.Response(200, content=b"mock-container")])
    identity = {name: {"path": "/mock/" + name} for name in ("ffprobe", "ffmpeg")}
    monkeypatch.setattr(assets, "executable_identity", lambda: identity)

    async def process(command, timeout):
        return (metadata(), b"") if "-show_entries" in command else (b"frame=4\nout_time_us=3000000\nprogress=end\n", b"")

    monkeypatch.setattr(assets, "run_media_process", process)
    result = await explainer_generation_poll(first["job_id"], operation("bad-eof"))
    assert result["status"] == "failed" and result["state"]["asset"]["sha256"] == sha(b"mock-container")


def test_missing_audio_is_measured_refusal(wire):
    frozen, _ = admission.freeze_request("fixture", request(wire))
    value = json.loads(metadata())
    value["streams"] = value["streams"][:1]
    with pytest.raises(ValueError):
        assets.measured_media(json.dumps(value).encode(), frozen)


@pytest.mark.parametrize("case", ["expired", "missing", "foreign", "redirect", "task-id"])
async def test_output_acquisition_failures_retain_identity(wire, case):
    first = await start(wire)
    if case == "task-id":
        wire[2].append(task("SUCCEEDED", task_id="foreign-task", video_url=URL))
    else:
        url = None if case == "missing" else "https://foreign.invalid/a.mp4" if case == "foreign" else URL
        wire[2].append(task("SUCCEEDED", video_url=url))
        if case in {"expired", "redirect"}:
            wire[2].append(httpx.Response(403 if case == "expired" else 302, headers={"Location": URL}))
    result = await explainer_generation_poll(first["job_id"], operation("poll-result"))
    assert result["status"] in {"failed", "unknown"} and result["provider_operation_id"] == "provider-task"
    assert result["source_revision"] == first["source_revision"] and result["request_sha256"] == first["request_sha256"]
    assert "private-output-token" not in json.dumps(result)
    assert len([r for r in wire[1] if r.method == "POST"]) == 1
    for sent in wire[1]:
        if sent.url.host == admission.RESULT_HOST:
            assert "Authorization" not in sent.headers


@pytest.mark.parametrize("changes", [{"width": 1278}, {"height": 718}, {"duration": "3"},
                                        {"codec_name": "hevc"}, {"sample_aspect_ratio": "2:1"}])
def test_measured_output_mismatch(wire, changes):
    frozen, _ = admission.freeze_request("fixture", request(wire))
    with pytest.raises(ValueError):
        assets.measured_media(metadata(**changes), frozen)


async def test_full_decode_failure_retains_actual_hash(wire, monkeypatch):
    first = await start(wire)
    wire[2].extend([task("SUCCEEDED", video_url=URL), httpx.Response(200, content=b"corrupt-fixture")])

    async def failed_decode(artifact, frozen):
        raise ValueError("Full decode mismatch")

    monkeypatch.setattr(service, "qualify_asset", failed_decode)
    result = await explainer_generation_poll(first["job_id"], operation("poll-decode"))
    assert result["status"] == "failed"
    asset = result["state"]["asset"]
    assert asset["sha256"] == sha(b"corrupt-fixture") and result["artifact_hashes"] == {asset["path"]: asset["sha256"]}
    assert Path(asset["path"]).read_bytes() == b"corrupt-fixture"
    assert asset["handoff"]["label"] == "synthetic illustrative"


async def test_tools_discovery_and_concurrent_submit_do_not_duplicate(wire):
    tools = await generation_server.list_tools()
    assert {t.name for t in tools} == {"explainer_generation_submit", "explainer_generation_poll", "explainer_generation_cancel"}
    assert wire[1] == [] and "httpx" not in assets.__dict__
    wire[2].append(task())
    a, b = await asyncio.gather(explainer_generation_submit("fixture", request(wire)),
                                explainer_generation_submit("fixture", request(wire)))
    assert a["job_id"] == b["job_id"] and len(wire[1]) == 1


async def test_store_request_integrity_blocks_remote_operations(wire):
    first = await start(wire)
    row = JobStore().get(first["job_id"])
    assert row["attestation"]["request_integrity"] == "verified"
    with JobStore()._connect() as database:
        database.execute("UPDATE jobs SET request_sha256=? WHERE job_id=?", ("0" * 64, first["job_id"]))
    result = await explainer_generation_poll(first["job_id"], operation("tampered-poll"))
    assert "integrity failed" in result["error"] and len(wire[1]) == 1


@pytest.mark.skipif(os.getenv("R681_NATIVE") != "1", reason="one separately bounded native fixture attempt")
async def test_native_matched_fixture_and_handoff(wire):
    """Adapt the existing first-party red/440Hz test fixture to the exact selected pixel map."""
    from video_explainer_mcp.media_process import run_media_process

    project = wire[0]
    audio = project / "owned-audio.wav"
    samples = b"".join(struct.pack("<h", round(10000 * math.sin(2 * math.pi * 440 * n / 16000))) for n in range(32000))
    with wave.open(str(audio), "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        writer.writeframes(samples)
    fixture = project / "owned-fixture.mp4"
    binary = assets.executable_identity()["ffmpeg"]["path"]
    command = [binary, "-v", "error", "-nostdin", "-threads", "1", "-f", "lavfi", "-i",
               "color=c=red:s=1280x720:r=4:d=2", "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-n", str(fixture)]
    stdout, stderr = await run_media_process(command, 10)
    assert not stdout and not stderr
    first = await start(wire)
    body = fixture.read_bytes()
    wire[2].extend([task("SUCCEEDED", video_url=URL), httpx.Response(200, content=body)])
    result = await explainer_generation_poll(first["job_id"], operation("poll-native"))
    destination = os.getenv("R681_RECEIPT_DIR")
    if destination:
        receipt = Path(destination)
        (receipt / "native-result.json").write_text(json.dumps({"fixture_command": command,
            "fixture_sha256": sha(body), "fixture_license": "First-party deterministic fixture adapted from tests/test_media_perception_prepare.py",
            "result": result}, indent=2) + "\n")
        (receipt / "native-fixture.mp4").write_bytes(body)
    assert result["status"] == "completed", result
    asset = result["state"]["asset"]
    assert asset["sha256"] == sha(body) and asset["qualification"]["full_decode"]
    assert asset["qualification"]["media"]["width"] == 1280 and asset["qualification"]["media"]["height"] == 720
    assert asset["qualification"]["media"]["audio_present"]
    assert abs(asset["qualification"]["media"]["duration_seconds"] - 2) <= 0.1
    importlib.reload(service)
    replay = await explainer_generation_poll(first["job_id"], operation("readback-native"))
    assert replay["state"]["asset"] == asset and replay["attestation"]["verified"]
    assert replay["state"]["request"] == request(wire).model_dump(mode="json")
    assert len(wire[1]) == 3 and asset["handoff"]["scene_id"] == "scene-1"
    Path(asset["path"]).write_bytes(b"changed")
    changed = await explainer_generation_poll(first["job_id"], operation("readback-changed"))
    assert changed["status"] == "unknown" and changed["artifact_hashes"] == replay["artifact_hashes"]
