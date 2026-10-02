"""Real source/artifact admission, private failures and joined segmentation cleanup."""

import asyncio
import base64
import builtins
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading

from PIL import Image
from pydantic import ValidationError
import pytest

from tests.test_segmentation_images import fixture_pngs, response_fixture
from tests.test_segmentation_service import network as network, selected as selected, response_wire
from video_research_mcp.config import get_config
from video_research_mcp.image_manifest import read_manifest
from video_research_mcp.image_tool_results import image_blocks
from video_research_mcp.models.segmentation import SegmentationRequest, SegmentationResponse
from video_research_mcp.segmentation import segment_image


@pytest.fixture(autouse=True)
def fence(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


@pytest.fixture
def admitted(tmp_path, selected):
    request, profile = selected
    source = tmp_path / "source.png"
    body = fixture_pngs()["source"]
    source.write_bytes(body)
    request = request.model_copy(update={"file_path": str(source), "expected_source_sha256": hashlib.sha256(body).hexdigest()})
    return request, source, profile


async def test_complete_artifacts_native_delivery_and_restart_readback(admitted, network):
    request, source, _ = admitted
    before = source.read_bytes()
    value = await segment_image(request)
    assert value["status"] == "complete" and value["outcome"] == "mask_proposals" and value["num_masks"] == 1
    mask = value["masks"][0]
    assert mask["score"] == 0.875 and mask["box_xyxy"] == [8, 6, 24, 18]
    assert mask["foreground_pixels"] == 192 and mask["coverage"] == 0.25 and mask["stored_mode"] == "L"
    assert [a["role"] for a in value["artifacts"]] == ["image", "alpha_mask", "image"]
    assert Path(mask["mask"]["path"]).read_bytes() == fixture_pngs()["mask"]
    assert Path(value["artifact"]["path"]).read_bytes() == fixture_pngs()["overlay"]
    with Image.open(value["artifact"]["path"]) as image:
        assert image.getpixel((10, 10)) == (225, 55, 28) and image.getpixel((0, 0)) == (40, 60, 80)
    restarted = await read_manifest(value["manifest"]["path"], value["manifest"]["sha256"])
    assert restarted["verified"] and restarted["masks"] == value["masks"]
    blocks, delivery = await image_blocks(value, True)
    text_blocks, text_delivery = await image_blocks(value, False)
    assert len(blocks) == 3 and text_blocks == []
    assert all(row["status"] == "included" for row in delivery) and all(row["status"] == "text_only" for row in text_delivery)
    assert [base64.b64decode(block.data) for block in blocks] == [Path(row["path"]).read_bytes() for row in value["artifacts"]]
    assert SegmentationResponse.model_validate({"metadata": value, "native_images": delivery}).metadata.source["sha256"] == request.expected_source_sha256
    assert value["readiness"]["model"] == "not_used_mock_fixture" and not value["readiness"]["model_loaded_verified"]
    assert not value["provenance"]["semantic_correctness_verified"] and value["provenance"]["result_origin"] == "mock_fixture"
    assert "fixture-private-key" not in json.dumps(value) and source.read_bytes() == before


async def test_dry_plan_prepares_and_verifies_zero_http_without_a_submission_grant(admitted, network):
    request, _, _ = admitted
    value = await segment_image(request.model_copy(update={"dry_run": True, "submission_authorized": False}))
    assert value["status"] == "planned" and value["outcome"] == "planned" and value["num_masks"] == 0
    assert value["response_sha256"] is None and len(value["artifacts"]) == 1
    assert value["readiness"]["transport"] == "not_contacted" and not network["connections"]
    assert (await read_manifest(value["manifest"]["path"], value["manifest"]["sha256"]))["verified"]


async def test_missing_optional_pillow_is_actionable_private_and_cleans_staging(admitted, network, tmp_path, monkeypatch):
    request, _, _ = admitted
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError("private-provider-diagnostics")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    value = await segment_image(request.model_copy(update={"dry_run": True}))
    assert value["category"] == "DEPENDENCY_MISSING" and value["reason"] == "images_dependency_missing"
    assert "video-research-mcp[images]" in value["hint"] and "private-provider-diagnostics" not in json.dumps(value)
    assert not network["connections"] and not list((tmp_path / "cache/media/views").glob("*"))


async def test_zero_results_are_abstention_with_actual_prepared_image(admitted, network):
    request, _, _ = admitted
    network["stream"].response = response_wire({"prompt": "rectangle", "num_masks": 0, "results": []})
    value = await segment_image(request)
    assert value["status"] == "complete" and value["outcome"] == "abstention" and value["masks"] == []
    assert len(value["artifacts"]) == 1 and value["artifact"]["origin"] == "source_derived"
    assert not value["provenance"]["object_absence_verified"]
    assert Path(value["artifact"]["path"]).read_bytes() == fixture_pngs()["source"]


@pytest.mark.parametrize("damage", ["mask", "overlay", "count", "score", "missing"])
async def test_invalid_response_has_no_promoted_or_partial_outputs(admitted, network, tmp_path, damage):
    request, source, _ = admitted
    response = deepcopy(response_fixture())
    if damage == "mask":
        response["results"][0]["mask_b64"] = "private-provider-body"
    elif damage == "overlay":
        response["image_b64"] = response["results"][0]["mask_b64"]
    elif damage == "count":
        response["num_masks"] = 2
    elif damage == "score":
        response["results"][0]["score"] = True
    else:
        response = {}
    network["stream"].response = response_wire(response)
    value = await segment_image(request)
    assert value["reason"] == "response_invalid" and value["retryable"] is False
    assert "private-provider-body" not in json.dumps(value) and "artifact" not in value
    assert not list((tmp_path / "cache/media/views").glob("*")) and source.read_bytes() == fixture_pngs()["source"]


@pytest.mark.parametrize("damage", ["wrong_sha", "symlink", "fifo", "fence", "bytes", "orientation"])
async def test_source_refusal_precedes_http_and_preserves_unrelated_outputs(admitted, network, tmp_path, monkeypatch, damage):
    request, source, _ = admitted
    other = tmp_path / "cache/media/views/other-owner"
    other.mkdir(parents=True)
    protected = other / "keep"
    protected.write_bytes(b"unrelated")
    if damage == "wrong_sha":
        request = request.model_copy(update={"expected_source_sha256": "0" * 64})
    elif damage in {"symlink", "fifo"}:
        hostile = tmp_path / "hostile.png"
        hostile.symlink_to(source) if damage == "symlink" else os.mkfifo(hostile)
        request = request.model_copy(update={"file_path": str(hostile)})
    elif damage == "fence":
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        get_config().local_file_access_root = str(allowed)
    elif damage == "bytes":
        source.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    else:
        with Image.new("RGB", (32, 24), "white") as image:
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)
        request = request.model_copy(update={"expected_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    value = await segment_image(request)
    assert "error" in value and not network["connections"]
    assert protected.read_bytes() == b"unrelated" and list((tmp_path / "cache/media/views").iterdir()) == [other]


async def test_source_mutation_after_http_refuses_and_preserves_new_original(admitted, network, tmp_path):
    request, source, _ = admitted
    original_read = network["stream"].read
    async def mutate(*args, **kwargs):
        source.write_bytes(b"new source-owner revision")
        return await original_read(*args, **kwargs)
    network["stream"].read = mutate
    value = await segment_image(request)
    assert value["reason"] == "source_changed" and source.read_bytes() == b"new source-owner revision"
    assert not list((tmp_path / "cache/media/views").glob("*"))


@pytest.mark.parametrize("damage", ["mask", "overlay", "manifest", "source"])
async def test_restart_readback_rejects_changed_source_or_artifact(admitted, network, damage):
    request, source, _ = admitted
    value = await segment_image(request)
    changed = Path(value["masks"][0]["mask"]["path"]) if damage == "mask" else Path(value["artifact"]["path"]) if damage == "overlay" else Path(value["manifest"]["path"]) if damage == "manifest" else source
    changed.write_bytes(b"changed bytes")
    with pytest.raises(ValueError):
        await read_manifest(value["manifest"]["path"], value["manifest"]["sha256"])


async def test_cancelled_http_closes_stream_and_removes_only_owned_staging(admitted, network, tmp_path):
    request, source, _ = admitted
    network["stream"].block_read = True
    task = asyncio.create_task(segment_image(request))
    await asyncio.wait_for(network["stream"].read_started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert network["stream"].closed and source.read_bytes() == fixture_pngs()["source"]
    assert not list((tmp_path / "cache/media/views").glob("*"))


async def test_cancelled_pillow_worker_is_joined_before_staging_cleanup(admitted, tmp_path, monkeypatch):
    from video_research_mcp import segmentation_images
    request, _, _ = admitted
    entered, release = threading.Event(), threading.Event()
    original = segmentation_images.load_oriented
    def blocked(*args):
        entered.set()
        release.wait(2)
        return original(*args)
    monkeypatch.setattr(segmentation_images, "load_oriented", blocked)
    task = asyncio.create_task(segment_image(request.model_copy(update={"dry_run": True})))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and list((tmp_path / "cache/media/views").glob("*/source.png"))
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list((tmp_path / "cache/media/views").glob("*"))


@pytest.mark.parametrize("changes", [{"expected_source_sha256": "bad"}, {"prompt": " "}, {"prompt": "x" * 513},
                                    {"service_id": "../service"}, {"dry_run": "true"}, {"submission_authorized": 1},
                                    {"base_url": "https://caller.invalid"}, {"headers": {"Authorization": "private"}}])
def test_request_cannot_override_endpoint_headers_or_coerce_authority(changes):
    with pytest.raises(ValidationError):
        SegmentationRequest.model_validate({"file_path": "/fixture.png", "expected_source_sha256": "0" * 64,
                                           "prompt": "rectangle", "service_id": "fixture", **changes})
