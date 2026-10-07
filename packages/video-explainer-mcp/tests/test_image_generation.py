"""One cached/offline cohort: real image logic and fake external HTTP boundaries."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from video_explainer_mcp import generation_assets as collector
from video_explainer_mcp import image_generation as lifecycle
from video_explainer_mcp import image_generation_request as admission
from video_explainer_mcp import planning_sources
from video_explainer_mcp.models.image_generation import ImageGenerationRequest, ImageOperation
from video_explainer_mcp.planning_sources import digest

BASE = "https://example.cn-beijing.maas.aliyuncs.com/api/v1"
URL = "https://dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com/example.png?Expires=1&Signature=example"


def image_bytes(fmt="PNG", size=(512, 512)):
    """Create public synthetic raster bytes without media services or inference."""
    stream = BytesIO()
    Image.new("RGB", size, "red").save(stream, format=fmt)
    return stream.getvalue()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Isolate the real controller and approved project, never using user files."""
    root = tmp_path / "projects"
    root.mkdir()
    project = root / "scene"
    project.mkdir()
    cfg = SimpleNamespace(dashscope_api_key="synthetic-test-key", dashscope_image_base_url=BASE,
                          projects_path=str(root), resolved_projects_path=root, explainer_enabled=False)
    monkeypatch.setattr(admission, "get_config", lambda: cfg)
    monkeypatch.setattr(planning_sources, "get_config", lambda: cfg)
    return project


def pin(project, name, value):
    """Write and pin immutable synthetic fixture bytes."""
    body = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
    (project / name).write_bytes(body)
    return {"path": name, "sha256": hashlib.sha256(body).hexdigest()}


def request(project, mode="text_to_image", **changes):
    """Build actual typed request and exact price/access/quote files, not fake admission."""
    value = dict(logical_job_id="synthetic", operation={"operation_id": "submit", "principal": "operator", "authorize": True},
                 mode=mode, model="qwen-mt-image" if mode == "image_translate" else "qwen-image-2.0-pro",
                 script=pin(project, "script.json", {"id": "script"}), scene=pin(project, "scene.json", {"id": "scene"}),
                 script_id="script", scene_id="scene", quote={"path": "quote.json", "sha256": "0" * 64},
                 spend_authorized=True, max_cost="1", currency="USD")
    if mode == "image_translate":
        value.update(source_lang="en", target_lang="ja", references=[{"role": "input",
                     "source": pin(project, "reference.png", image_bytes()), "public_url": "https://example.org/reference.png"}])
    else:
        value.update(prompt="synthetic red square", size="512*512", seed=7)
        if mode == "image_edit":
            value["references"] = [{"role": "identity", "source": pin(project, "identity.png", image_bytes())},
                                   {"role": "style", "source": pin(project, "style.png", image_bytes("PNG", (512, 768)))}]
    value.update(changes)
    selected = ImageGenerationRequest.model_validate(value)
    price = {"evidence_kind": "operator_declaration", "provider": "dashscope", "model": selected.model,
             "mode": mode, "unit": "image", "price_per_image": "0.01", "currency": "USD",
             "principal": "operator", "source_url": next(iter(admission.CONTRACT)),
             "source_revision": "synthetic-public-fixture", "recorded_at": "2026-01-01T00:00:00Z"}
    access = {"evidence_kind": "operator_declaration", "provider": "dashscope", "model": selected.model,
              "api_origin": BASE, "principal": "operator", "access": "operator_declares_access",
              "source_url": BASE + "/model-access", "source_revision": "synthetic-public-fixture",
              "recorded_at": "2026-01-01T00:00:00Z"}
    body = selected.model_dump(mode="json")
    body.pop("quote")
    now = datetime.now(timezone.utc)
    quote = {"evidence_kind": "operator_declaration", "provider": "dashscope", "model": selected.model,
             "mode": mode, "unit": "image", "price_per_image": "0.01", "currency": "USD", "principal": "operator",
             "api_origin": BASE, "request_sha256": digest(body), "contract_sha256": digest(admission.CONTRACT),
             "issued_at": (now - timedelta(minutes=1)).isoformat(), "valid_until": (now + timedelta(hours=1)).isoformat(),
             "price_source": pin(project, "price.json", price), "model_access_source": pin(project, "access.json", access)}
    value["quote"] = pin(project, "quote.json", quote)
    return ImageGenerationRequest.model_validate(value)


def op(name):
    """Supply an explicit fresh operation; never infer authorization from a timeout."""
    return ImageOperation(operation_id=name, principal="operator", authorize=True)


def transport(monkeypatch, handler):
    """Mock only HTTP transport while executing the actual collector and lifecycle."""
    monkeypatch.setattr(collector, "http_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False))


def sync_response(n=1):
    """Represent the documented synchronous HTTP response, not an SDK response."""
    return {"request_id": "provider-request", "output": {"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": [{"image": URL}] * n}}]}}


@pytest.mark.parametrize("mode", ["text_to_image", "image_edit"])
def test_exact_sync_payload_and_references(project, mode):
    """GIVEN mapped requests, THEN actual bytes and every documented control reach wire."""
    req = request(project, mode, n=2)
    frozen, _ = admission.freeze_request("scene", req)
    wire = admission.provider_payload(frozen)
    assert wire["model"] == "qwen-image-2.0-pro"
    assert wire["parameters"] == {"n": 2, "size": "512*512", "seed": 7,
           "prompt_extend": False, "watermark": True, "negative_prompt": ""}
    content = wire["input"]["messages"][0]["content"]
    assert content[-1] == {"text": req.prompt}
    for part, ref in zip(content[:-1], req.references, strict=True):
        assert base64.b64decode(part["image"].split(",", 1)[1]) == (project / ref.source.path).read_bytes()


@pytest.mark.parametrize("mode,changes", [
    ("text_to_image", {"transparent_background": True}),
    ("text_to_image", {"size": "513*512"}),
    ("text_to_image", {"size": "256*256"}),
    ("text_to_image", {"spend_authorized": False}),
    ("text_to_image", {"max_cost": "0.005"}),
    ("text_to_image", {"source_lang": "en"}),
    ("text_to_image", {"image_segment": True}),
    ("image_edit", {"references": []}),
    ("image_translate", {"prompt": "must not drop"}),
    ("image_translate", {"seed": 9}),
    ("image_translate", {"size": "512*512"}),
    ("image_translate", {"watermark": False}),
    ("image_translate", {"n": 2}),
    ("image_translate", {"source_lang": "ja", "target_lang": "ko"}),
    ("image_translate", {"target_lang": "de"}),
])
async def test_unsupported_intent_refuses_before_post(project, monkeypatch, mode, changes):
    """GIVEN unsupported or unauthorized intent, THEN no HTTP effect or durable submit exists."""
    calls = []
    transport(monkeypatch, lambda req: calls.append(req))
    req = request(project, mode, **changes)
    with pytest.raises(ValueError):
        await lifecycle.submit_image_generation("scene", req)
    assert not calls


@pytest.mark.parametrize("name", ["identity.png", "script.json", "scene.json", "price.json", "access.json", "quote.json"])
async def test_changed_sources_refuse_before_post(project, monkeypatch, name):
    """GIVEN a changed admitted file, THEN hash integrity prevents the provider effect."""
    req = request(project, "image_edit")
    (project / name).write_bytes(b"changed")
    transport(monkeypatch, lambda req: pytest.fail("provider effect before integrity refusal"))
    with pytest.raises(ValueError):
        await lifecycle.submit_image_generation("scene", req)


async def test_sync_restart_finalize_real_raster_and_tamper(project, monkeypatch):
    """GIVEN a captured sync result, THEN restart finalizes bytes once and tampering downgrades proof."""
    calls = []
    def handler(http):
        calls.append(http)
        if http.method == "POST":
            assert "X-DashScope-Async" not in http.headers
            assert http.url.path.endswith("/multimodal-generation/generation")
            return httpx.Response(200, json=sync_response())
        assert "Authorization" not in http.headers
        return httpx.Response(200, content=image_bytes())
    transport(monkeypatch, handler)
    req = request(project)
    submitted = await lifecycle.submit_image_generation("scene", req)
    assert submitted["status"] == "unknown" and submitted["provider_task_id"] is None
    assert submitted["provider_request_id"] == "provider-request"
    import importlib
    importlib.reload(lifecycle)
    completed = await lifecycle.recover_image_generation(submitted["job_id"], op("finalize"), finalize=True)
    assert completed["status"] == "completed"
    proof = completed["state"]["assets"][0]["qualification"]
    assert proof["format"] == "PNG" and proof["width"] == 512 and proof["full_decode"]
    assert completed["state"]["request"]["label"] == "synthetic illustrative"
    assert completed["state"]["assets"][0]["handoff"]["continuation_settings"]["controls"]["seed"] == 7
    await lifecycle.submit_image_generation("scene", req)
    await lifecycle.recover_image_generation(submitted["job_id"], op("finalize"), finalize=True)
    assert len(calls) == 2
    Path(completed["state"]["assets"][0]["path"]).write_bytes(b"tampered")
    assert (await lifecycle.submit_image_generation("scene", req))["status"] == "unknown"


async def test_ambiguous_submit_has_no_restart_resubmit_or_invented_poll(project, monkeypatch):
    """GIVEN timeout after intent, THEN fresh recovery preserves UNKNOWN without new POST."""
    calls = []
    def handler(http):
        calls.append(http)
        raise httpx.ReadTimeout("ambiguous", request=http)
    transport(monkeypatch, handler)
    req = request(project)
    row = await lifecycle.submit_image_generation("scene", req)
    assert row["state"]["generation_intent_count"] == 1
    assert row["state"]["failures"][0]["action"] == "submit"
    await lifecycle.submit_image_generation("scene", req)
    recovered = await lifecycle.recover_image_generation(row["job_id"], op("poll"))
    cancelled = await lifecycle.cancel_image_generation(row["job_id"], op("cancel"))
    assert recovered["status"] == "unknown"
    assert "No recoverable" in recovered["state"]["recovery_seam"]
    assert cancelled["state"]["cancel_supported"] is False
    assert len(calls) == 1


async def test_translation_exact_task_payload_and_real_jpeg(project, monkeypatch):
    """GIVEN a pinned public image, THEN distinct IDs and real translation task GET are retained."""
    from video_explainer_mcp import materials_remote
    monkeypatch.setattr(materials_remote, "_fetch", lambda url, headers, hosts, limit, deadline:
                        (image_bytes(), url))
    calls = []
    def handler(http):
        calls.append(http)
        if http.method == "POST":
            assert http.url.path.endswith("/image2image/image-synthesis")
            assert http.headers["X-DashScope-Async"] == "enable"
            assert json.loads(http.content) == {"model": "qwen-mt-image", "input": {
                "image_url": "https://example.org/reference.png", "source_lang": "en", "target_lang": "ja",
                "ext": {"config": {"imageSegment": False}}}}
            return httpx.Response(200, json={"request_id": "submit-request", "output": {
                "task_id": "translation-task", "task_status": "PENDING"}})
        if http.url.path.endswith("/tasks/translation-task"):
            return httpx.Response(200, json={"request_id": "poll-request", "output": {
                "task_id": "translation-task", "task_status": "SUCCEEDED", "image_url": URL,
                "message": "No text detected for translation"}})
        assert "Authorization" not in http.headers
        return httpx.Response(200, content=image_bytes("JPEG"))
    transport(monkeypatch, handler)
    row = await lifecycle.submit_image_generation("scene", request(project, "image_translate"))
    done = await lifecycle.recover_image_generation(row["job_id"], op("poll"))
    assert done["status"] == "completed"
    assert done["provider_request_id"] == "submit-request" and done["provider_task_id"] == "translation-task"
    assert done["state"]["last_provider_request_id"] == "poll-request"
    assert done["state"]["translation_message"] == "No text detected for translation"
    assert done["state"]["assets"][0]["qualification"]["format"] == "JPEG"
    assert len(calls) == 3


async def test_translation_remote_bytes_changed_prevents_generation(project, monkeypatch):
    """GIVEN a different public file, THEN the local pin cannot authorize that remote content."""
    from video_explainer_mcp import materials_remote
    monkeypatch.setattr(materials_remote, "_fetch", lambda url, headers, hosts, limit, deadline: (b"changed", url))
    calls = []
    transport(monkeypatch, lambda http: calls.append(http))
    row = await lifecycle.submit_image_generation("scene", request(project, "image_translate"))
    assert not calls and row["state"]["generation_intent_count"] == 0


@pytest.mark.parametrize("result", [b"not-image", image_bytes("JPEG"), image_bytes(size=(512, 768))])
async def test_actual_format_and_dimensions_refuse_false_completion(project, monkeypatch, result):
    """GIVEN a mislabeled or mismatched result, THEN actual decoded bytes govern acceptance."""
    transport(monkeypatch, lambda http: httpx.Response(200, json=sync_response()) if http.method == "POST"
              else httpx.Response(200, content=result))
    row = await lifecycle.submit_image_generation("scene", request(project))
    final = await lifecycle.recover_image_generation(row["job_id"], op("final"), finalize=True)
    assert final["status"] == "unknown" and not final["artifact_hashes"]


def test_continuation_controls_and_unaffected_bytes(project):
    """GIVEN explicit anchor continuation, THEN every reused control and unaffected hash is compared."""
    unaffected = pin(project, "unaffected.png", image_bytes())
    req = request(project, "image_edit", unaffected_artifacts=[unaffected])
    value = req.model_dump(mode="json")
    prior = {"model": req.model, "controls": admission.controls(value), "references": value["references"],
             "unaffected_artifacts": value["unaffected_artifacts"]}
    continuation = pin(project, "continuation.json", prior)
    req = request(project, "image_edit", unaffected_artifacts=[unaffected], continuation=continuation)
    frozen, _ = admission.freeze_request("scene", req)
    assert frozen["continuation_settings"] == prior
    (project / "unaffected.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        admission.freeze_request("scene", req)


@pytest.mark.parametrize("status", [302, 400, 500])
async def test_collector_never_redirects_or_retries(project, monkeypatch, status):
    """GIVEN unsuccessful HTTP, THEN the generation intent remains occupied with one effect."""
    calls = []
    def handler(http):
        calls.append(http)
        return httpx.Response(status, headers={"Location": "https://example.org/redirect"})
    transport(monkeypatch, handler)
    row = await lifecycle.submit_image_generation("scene", request(project))
    assert row["status"] == "unknown" and len(calls) == 1


async def test_bounded_collector_keeps_oversize_unknown(project, monkeypatch):
    """GIVEN excessive provider JSON, THEN collector refuses rather than retrying generation."""
    transport(monkeypatch, lambda http: httpx.Response(200, content=b"x" * 65537))
    row = await lifecycle.submit_image_generation("scene", request(project))
    assert row["status"] == "unknown" and row["state"]["generation_intent_count"] == 1


async def test_pending_translation_cancel_requires_confirming_fetch(project, monkeypatch):
    """GIVEN fresh PENDING, THEN a JSON-string ACK alone does not establish cancellation."""
    from video_explainer_mcp import materials_remote
    monkeypatch.setattr(materials_remote, "_fetch", lambda url, headers, hosts, limit, deadline: (image_bytes(), url))
    calls = []
    def handler(http):
        calls.append(http)
        if http.url.path.endswith("/cancel"):
            return httpx.Response(200, json="cancel-request")
        status = "CANCELED" if len(calls) == 4 else "PENDING"
        return httpx.Response(200, json={"request_id": "provider-request", "output": {
            "task_id": "translation-task", "task_status": status}})
    transport(monkeypatch, handler)
    row = await lifecycle.submit_image_generation("scene", request(project, "image_translate"))
    done = await lifecycle.cancel_image_generation(row["job_id"], op("cancel"))
    assert done["status"] == "cancelled" and done["state"]["cancellation_confirmed"]
    assert done["state"]["cancel_ack_request_id"] == "cancel-request"
    assert [c.method for c in calls] == ["POST", "GET", "POST", "GET"]


@pytest.mark.parametrize("failure", ["missing", "symlink"])
async def test_invalid_reference_has_no_effect(project, monkeypatch, failure):
    """GIVEN absent or indirect anchors, THEN refusal precedes provider POST."""
    req = request(project, "image_edit")
    (project / "identity.png").unlink()
    if failure == "symlink":
        (project / "identity.png").symlink_to(project / "style.png")
    transport(monkeypatch, lambda http: pytest.fail("generation of invalid reference"))
    with pytest.raises((ValueError, OSError)):
        await lifecycle.submit_image_generation("scene", req)


async def test_operation_conflict_and_provider_task_substitution(project, monkeypatch):
    """GIVEN a foreign task ID in a fetch, THEN no foreign output can enter local custody."""
    from video_explainer_mcp import materials_remote
    monkeypatch.setattr(materials_remote, "_fetch", lambda url, headers, hosts, limit, deadline: (image_bytes(), url))
    calls = []
    def handler(http):
        calls.append(http)
        return httpx.Response(200, json={"request_id": "provider-request", "output": {
            "task_id": "translation-task" if http.method == "POST" else "foreign-task",
            "task_status": "PENDING"}})
    transport(monkeypatch, handler)
    row = await lifecycle.submit_image_generation("scene", request(project, "image_translate"))
    with pytest.raises(ValueError, match="another action"):
        await lifecycle.recover_image_generation(row["job_id"], op("submit"))
    final = await lifecycle.recover_image_generation(row["job_id"], op("poll"))
    assert final["status"] == "unknown" and final["provider_task_id"] == "translation-task"
    assert final["state"]["failures"][-1]["action"] == "poll" and len(calls) == 2
