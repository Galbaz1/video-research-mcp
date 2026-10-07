"""Causal regressions from independent R695 source and MCP reproductions."""

from io import BytesIO
import importlib

from fastmcp import Client
import httpx
from PIL import Image
import pytest

from tests import test_image_generation as fixtures
from video_explainer_mcp import generation_references
from video_explainer_mcp import image_generation as lifecycle
from video_explainer_mcp import image_generation_assets as assets
from video_explainer_mcp import image_generation_request as admission
from video_explainer_mcp.server import app

project = fixtures.project


@pytest.mark.parametrize("format", ["PNG", "JPEG", "BMP", "WEBP"])
def test_real_supported_i2v_frames_verify_before_metadata_load(format):
    """GIVEN actual format bytes, THEN real Pillow inspection preserves opaque frame metadata."""
    stream = BytesIO()
    Image.new("RGB", (640, 480), "red").save(stream, format=format)
    result = generation_references.inspect_image(stream.getvalue())
    assert result["format"] == format and result["width"] == 640 and result["height"] == 480


@pytest.mark.parametrize("mode", ["P", "RGBA"])
def test_actual_transparency_rejected_across_palette_and_alpha_modes(mode):
    """GIVEN a transparent valid PNG, THEN decoding cannot qualify an opaque output."""
    image = Image.new(mode, (512, 512), 0)
    stream = BytesIO()
    image.save(stream, format="PNG", **({"transparency": 0} if mode == "P" else {}))
    with pytest.raises(ValueError, match="transparent"):
        assets.raster(stream.getvalue(), output=True)


async def test_full_translation_model_json_reaches_actual_mcp(project, monkeypatch):
    """GIVEN the public model's full dump, THEN native MCP submits the same normalized request."""
    from video_explainer_mcp import materials_remote

    monkeypatch.setattr(materials_remote, "_fetch", lambda url, headers, hosts, limit, deadline:
                        (fixtures.image_bytes(), url))
    calls = []

    def handler(http):
        calls.append(http)
        return httpx.Response(200, json={"request_id": "synthetic", "output": {
            "task_id": "synthetic-task", "task_status": "PENDING"}})

    fixtures.transport(monkeypatch, handler)
    req = fixtures.request(project, "image_translate")
    full = req.model_dump(mode="json")
    assert full["watermark"] is None
    async with Client(app) as client:
        result = (await client.call_tool("explainer_image_generation_submit", {
            "project_id": "scene", "request": full})).data
    assert result["provider_task_id"] == "synthetic-task" and len(calls) == 1


@pytest.mark.parametrize("watermark", [False, True])
def test_translation_explicit_watermark_intent_stays_unsupported(project, watermark):
    """GIVEN a real watermark instruction, THEN translation refuses it before any effect."""
    req = fixtures.request(project, "image_translate", watermark=watermark)
    with pytest.raises(ValueError, match="watermark"):
        admission.freeze_request("scene", req)


def test_translation_known_region_limit_checked_before_reservation(project, monkeypatch):
    """GIVEN the unavailable Singapore legacy model, THEN current contract admission refuses it."""
    cfg = admission.get_config()
    cfg.dashscope_image_base_url = "https://example.ap-southeast-1.maas.aliyuncs.com/api/v1"
    req = fixtures.request(project, "image_translate")
    with pytest.raises(ValueError, match="Beijing"):
        admission.freeze_request("scene", req)


async def test_partial_images_checkpoint_then_resume_only_missing_url(project, monkeypatch):
    """GIVEN a second failed download, THEN restart retains and reuses the first original without POST."""
    urls = [fixtures.URL.replace("example.png", f"{index}.png") for index in range(2)]
    calls = []
    recovering = False

    def handler(http):
        calls.append((http.method, str(http.url)))
        if http.method == "POST":
            response = fixtures.sync_response(2)
            response["output"]["choices"][0]["message"]["content"] = [{"image": url} for url in urls]
            return httpx.Response(200, json=response)
        if str(http.url) == urls[0]:
            assert not recovering, "Previously captured URL must not be fetched again"
            return httpx.Response(200, content=fixtures.image_bytes())
        return httpx.Response(200, content=fixtures.image_bytes()) if recovering else httpx.Response(403)

    fixtures.transport(monkeypatch, handler)
    req = fixtures.request(project, n=2)
    submitted = await lifecycle.submit_image_generation("scene", req)
    first = await lifecycle.recover_image_generation(submitted["job_id"], fixtures.op("first"), finalize=True)
    assert first["status"] == "unknown" and len(first["state"]["assets"]) == 1
    assert len(first["artifact_hashes"]) == 1
    saved = first["state"]["assets"][0]
    recovering = True
    importlib.reload(lifecycle)
    completed = await lifecycle.recover_image_generation(submitted["job_id"], fixtures.op("resume"), finalize=True)
    assert completed["status"] == "completed" and completed["state"]["assets"][0] == saved
    assert len(completed["artifact_hashes"]) == 2
    assert [method for method, url in calls].count("POST") == 1
    assert [url for method, url in calls].count(urls[0]) == 1
