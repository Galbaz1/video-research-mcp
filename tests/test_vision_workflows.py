"""Whole local preparation/model-wire/geometry/ownership vision workflows."""

import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

from fastmcp import Client
from PIL import Image
import pytest

from video_research_mcp.config import update_config
from video_research_mcp.models.vision import VisionRequest
from video_research_mcp.tools.vision import vision_server
from video_research_mcp.vision_analysis import analyze_vision


@pytest.fixture
def vision_fixture(tmp_path, clean_config, monkeypatch):
    source = tmp_path / "source.png"
    image = Image.new("RGB", (80, 60), "white")
    image.putpixel((23, 14), (250, 0, 0))
    image.save(source)
    second = tmp_path / "second.png"
    Image.new("RGB", (40, 30), "blue").save(second)
    monkeypatch.setenv("VISION_TEST_API_KEY", "fixture-key-731")
    update_config(
        local_file_access_root=str(tmp_path),
        cache_dir=str(tmp_path / "cache"),
        vision_backends={
            "local": {
                "base_url": "http://127.0.0.1:8123/v1",
                "model": "owned-model",
                "local": True,
                "api_key_env": "VISION_TEST_API_KEY",
                "capabilities": ["images", "video", "structured_json"],
            }
        },
    )
    return source, second, tmp_path / "cache/media/views"


def source_request(path, **kw):
    """Bind the exact local fixture before each test-selected preparation."""
    return {
        "file_path": str(path),
        "expected_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **kw,
    }


def request_for(source, **kwargs):
    """Use the selected compatible mock fixture workflow."""
    return VisionRequest(
        sources=[source_request(source)],
        instruction="Find the red pixel",
        backend="local",
        **kwargs,
    )


def wire_reply(answer="owned answer", regions=None, finish="stop", **extra):
    """Return one completed external chat response with controlled model content."""
    return 200, json.dumps(
        {
            "choices": [
                {
                    "finish_reason": finish,
                    "message": {
                        "content": json.dumps({"answer": answer, "regions": regions or []})
                    },
                }
            ],
            **extra,
        }
    ).encode()


async def test_public_dry_plan_has_three_tools_zero_network_and_redacted_preview(
    vision_fixture, monkeypatch
):
    source, _, _ = vision_fixture
    wire = AsyncMock(side_effect=AssertionError("dry plans cannot submit"))
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    async with Client(vision_server) as client:
        assert {t.name for t in await client.list_tools()} == {
            "vision_chat",
            "vision_ocr",
            "vision_grounding",
        }
        reply = await client.call_tool(
            "vision_chat", {"request": request_for(source).model_dump(mode="json")}
        )
    result = reply.structured_content
    assert result["status"] == "planned" and result["model_output"] is None
    assert result["execution"]["provider_calls"] == 0
    assert not wire.called
    assert "fixture-key-731" not in json.dumps(result) and "data:image" not in json.dumps(result)
    assert result["payload_receipt"][0]["sha256"] == result["preparations"][0]["artifact"]["sha256"]


async def test_submission_without_workflow_grant_cleans_own_preparation(
    vision_fixture, monkeypatch
):
    source, _, views = vision_fixture
    wire = AsyncMock()
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    result = await analyze_vision(request_for(source, dry_run=False), "vision_chat")
    assert result["category"] == "PERMISSION_DENIED" and not result["retryable"]
    assert not wire.called and not list(views.iterdir())


async def test_compare_keeps_both_original_digests_order_and_actual_sent_pixels(
    vision_fixture, monkeypatch
):
    source, second, _ = vision_fixture
    captured = []

    async def wire(url, **kw):
        assert kw["headers"]["Authorization"] == "Bearer fixture-key-731"
        captured.append(json.loads(kw["content"]))
        return wire_reply()

    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    request = VisionRequest(
        sources=[source_request(source), source_request(second)],
        instruction="Compare",
        backend="local",
        dry_run=False,
        authorize_submission=True,
    )
    result = await analyze_vision(request, "vision_chat")
    assert result["status"] == "complete"
    assert [p["source"]["sha256"] for p in result["preparations"]] == [
        source_request(p)["expected_source_sha256"] for p in [source, second]
    ]
    parts = captured[0]["messages"][0]["content"]
    urls = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
    assert [hashlib.sha256(base64.b64decode(u.split(",", 1)[1])).hexdigest() for u in urls] == [
        p["sha256"] for p in result["payload_receipt"]
    ]
    assert result["provenance"]["model_output"] == "model_inference"
    assert result["execution"]["input_token_limit_verified"] is False


async def test_grounding_maps_prepared_crop_resize_to_original_verified_pixel(
    vision_fixture, monkeypatch
):
    source, _, _ = vision_fixture
    box = {"source_index": 0, "label": "red pixel", "bbox": [100, 150, 200, 300]}
    wire = AsyncMock(return_value=wire_reply(regions=[box]))
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    request = VisionRequest(
        sources=[
            source_request(
                source, crop={"coordinates": [20, 10, 20, 20]}, resize={"width": 40, "height": 40}
            )
        ],
        instruction="Find red",
        backend="local",
        dry_run=False,
        authorize_submission=True,
        export_crops=True,
    )
    result = await analyze_vision(request, "grounding")
    assert result["status"] == "complete"
    region = result["regions"][0]
    assert region["original_crop_xywh"] == [22, 13, 2, 3]
    with Image.open(region["crop"]["artifact"]["path"]) as crop:
        assert crop.size == (2, 3) and crop.getpixel((1, 1))[:3] == (250, 0, 0)
    assert region["crop_parent"]["pixel_extraction_verified"]
    assert (
        not region["object_correctness_verified"]
        and region["source_sha256"] == source_request(source)["expected_source_sha256"]
    )


@pytest.mark.parametrize(
    "bbox",
    [[-1, 0, 4, 4], [0, 0, 1001, 2], [4, 0, 3, 1], [0, 0, 0, 1], [True, 0, 2, 2], [0, 0, "2", 2]],
)
async def test_invalid_model_boxes_reject_before_crop_and_clean_views(
    vision_fixture, monkeypatch, bbox
):
    source, _, views = vision_fixture
    box = {"source_index": 0, "label": "invalid", "bbox": bbox}
    monkeypatch.setattr(
        "video_research_mcp.vision_http.exchange", AsyncMock(return_value=wire_reply(regions=[box]))
    )
    result = await analyze_vision(
        request_for(source, dry_run=False, authorize_submission=True, export_crops=True),
        "grounding",
    )
    assert "error" in result and not list(views.iterdir())
    assert result["execution"]["provider_calls"] == 1


async def test_wrong_source_index_and_valid_empty_abstention(vision_fixture, monkeypatch):
    source, _, views = vision_fixture
    wire = AsyncMock(
        return_value=wire_reply(
            regions=[{"source_index": 1, "label": "unknown", "bbox": [0, 0, 10, 10]}]
        )
    )
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    request = request_for(source, dry_run=False, authorize_submission=True, export_crops=True)
    bad = await analyze_vision(request, "grounding")
    assert "error" in bad and not list(views.iterdir())
    wire.return_value = wire_reply(answer="No requested object is supported")
    good = await analyze_vision(request, "grounding")
    assert good["status"] == "complete" and good["regions"] == []


async def test_backend_and_model_changes_bind_fresh_uncached_results(vision_fixture, monkeypatch):
    source, _, _ = vision_fixture
    wire = AsyncMock(return_value=wire_reply())
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    request = request_for(source, dry_run=False, authorize_submission=True)
    first = await analyze_vision(request, "vision_chat")
    update_config(
        vision_backends={
            "local": {
                "base_url": "http://127.0.0.1:9123/v1",
                "model": "other-model",
                "local": True,
                "capabilities": ["images", "structured_json"],
            }
        }
    )
    second = await analyze_vision(request, "vision_chat")
    assert first["request_sha256"] != second["request_sha256"] and wire.await_count == 2
    assert not first["execution"]["cache_used"] and not second["execution"]["cache_used"]
    assert "Authorization" not in wire.call_args.kwargs["headers"]


async def test_source_change_after_submission_is_retained_failure_no_repeat(
    vision_fixture, monkeypatch
):
    source, _, views = vision_fixture
    original = source.read_bytes()

    async def wire(*args, **kwargs):
        source.write_bytes(b"controlled source mutation")
        return wire_reply()

    mock = AsyncMock(side_effect=wire)
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", mock)
    result = await analyze_vision(
        request_for(source, dry_run=False, authorize_submission=True), "vision_chat"
    )
    source.write_bytes(original)
    assert "error" in result and mock.await_count == 1 and not list(views.iterdir())
    assert result["execution"]["provider_calls"] == 1


async def test_provider_error_with_secrets_and_base64_is_withheld_no_repeat(
    vision_fixture, monkeypatch
):
    source, _, views = vision_fixture
    mock = AsyncMock(
        side_effect=RuntimeError("fixture-key-731 data:image/png;base64,private-content")
    )
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", mock)
    result = await analyze_vision(
        request_for(source, dry_run=False, authorize_submission=True), "ocr"
    )
    encoded = json.dumps(result)
    assert "fixture-key-731" not in encoded and "private-content" not in encoded
    assert mock.await_count == 1 and not list(views.iterdir())


async def test_model_ocr_is_labeled_inference_without_local_engine_fallback(
    vision_fixture, monkeypatch
):
    source, _, _ = vision_fixture
    monkeypatch.setattr(
        "video_research_mcp.vision_http.exchange",
        AsyncMock(return_value=wire_reply(answer="INFERRED 731")),
    )
    result = await analyze_vision(
        request_for(source, dry_run=False, authorize_submission=True), "ocr"
    )
    assert result["provenance"]["ocr_text"] == "model_inference"
    assert result["model_output"]["answer"] == "INFERRED 731"


async def test_public_cancellation_joins_wire_and_cleans_only_current_exports(
    vision_fixture, monkeypatch
):
    import asyncio
    from video_research_mcp.image_edit import edit_image
    from video_research_mcp.models.image_edit import ImageEditRequest

    source, _, views = vision_fixture
    prior = await edit_image(ImageEditRequest(file_path=str(source)))
    entered, finished = asyncio.Event(), asyncio.Event()

    async def wire(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finished.set()

    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    async with Client(vision_server) as client:
        task = asyncio.create_task(
            client.call_tool(
                "vision_chat",
                {
                    "request": request_for(
                        source, dry_run=False, authorize_submission=True
                    ).model_dump(mode="json")
                },
            )
        )
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(finished.wait(), 2)
    assert list(views.iterdir()) == [Path(prior["artifact"]["path"]).parent]
    assert (
        hashlib.sha256(Path(prior["artifact"]["path"]).read_bytes()).hexdigest()
        == prior["artifact"]["sha256"]
    )


@pytest.mark.parametrize(
    "finish,refusal", [("length", None), ("content_filter", None), ("stop", "unsupported")]
)
async def test_compatible_truncation_and_refusal_remain_failed_single_attempts(
    vision_fixture, monkeypatch, finish, refusal
):
    source, _, views = vision_fixture
    status, data = wire_reply(finish=finish)
    body = json.loads(data)
    body["choices"][0]["message"]["refusal"] = refusal
    wire = AsyncMock(return_value=(status, json.dumps(body).encode()))
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    result = await analyze_vision(
        request_for(source, dry_run=False, authorize_submission=True), "vision_chat"
    )
    assert "error" in result and not result["retryable"]
    wire.assert_awaited_once()
    assert result["execution"]["provider_calls"] == 1 and not list(views.iterdir())
