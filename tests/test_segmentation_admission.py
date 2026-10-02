"""Actual public segmentation admission, native delivery and manifest restart."""

import base64
import hashlib
import io
import json
from pathlib import Path

from fastmcp import Client
from jsonschema import validate
from PIL import Image
import pytest

from tests.test_vision_http import NetworkStream, network as transport_fixture
from video_research_mcp.config import ServerConfig
from video_research_mcp.tools.segmentation import segmentation_server

network = transport_fixture


@pytest.fixture(autouse=True)
def private_config(tmp_path, monkeypatch, clean_config):
    """Confine configuration and all generated artifacts to the invocation."""
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("WEAVIATE_URL", "")
    monkeypatch.delenv("SEGMENTATION_SERVICES_JSON", raising=False)


def test_default_optional_config_and_explicit_environment_selection(monkeypatch):
    assert ServerConfig.from_env().segmentation_services == {}
    profile = {"base_url": "http://127.0.0.1:9000", "local": True, "origin": "mock-fixture"}
    monkeypatch.setenv("SEGMENTATION_SERVICES_JSON", json.dumps({"fixture": profile}))
    assert ServerConfig.from_env().segmentation_services["fixture"].model_dump() == {
        **profile, "api_key_env": None, "declared_model": None, "checkpoint_sha256": None,
    }


@pytest.mark.parametrize("profiles", [
    {"bad id": {"base_url": "https://service.example", "origin": "mock-fixture"}},
    {f"s{i}": {"base_url": "https://service.example", "origin": "mock-fixture"} for i in range(9)},
    {"fixture": {"base_url": "http://127.0.0.1:9000", "origin": "mock-fixture"}},
    {"fixture": {"base_url": "https://service.example", "origin": "mock-fixture", "api_key": "forbidden"}},
])
def test_invalid_operator_config_fails_before_tool_execution(monkeypatch, profiles):
    monkeypatch.setenv("SEGMENTATION_SERVICES_JSON", json.dumps(profiles))
    with pytest.raises(ValueError):
        ServerConfig.from_env()


async def test_public_missing_service_preserves_fixed_reason_and_typed_schema(network):
    """GIVEN no service WHEN called THEN the error needs no source open or network."""
    async with Client(segmentation_server) as client:
        tool = (await client.list_tools())[0]
        assert tool.name == "image_segment" and tool.annotations.open_world_hint is True
        reply = await client.call_tool("image_segment", {"request": {
            "file_path": "/unused.png", "expected_source_sha256": "0" * 64,
            "prompt": "object", "service_id": "fixture",
        }}, raise_on_error=False)
        assert reply.is_error and reply.structured_content["reason"] == "service_missing"
        assert reply.structured_content["retryable"] is False and len(reply.content) == 1
        validate(reply.structured_content, tool.output_schema)
        assert not network["connections"] and not network["stream"].writes


@pytest.fixture
def image_response(tmp_path):
    """Create an owned original image and an exact mock raster response."""
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 24), (40, 60, 80)).save(source)
    original = source.read_bytes()
    encoded = []
    for image in (Image.new("L", (32, 24), 255), Image.new("RGB", (32, 24), (225, 55, 28))):
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        encoded.append(buffer.getvalue())
    response = {"prompt": "object", "num_masks": 1, "results": [{
        "score": .875, "box": [0, 0, 32, 24], "mask_b64": base64.b64encode(encoded[0]).decode(),
    }], "image_b64": base64.b64encode(encoded[1]).decode()}
    return source, original, response


async def test_actual_wire_native_metadata_and_restart_readback(monkeypatch, network, image_response):
    """GIVEN an owned service fixture WHEN submitted THEN original-grid PNG bytes survive."""
    source, original, response = image_response
    raw = json.dumps(response).encode()
    network["stream"] = NetworkStream(
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw,
        peer=("127.0.0.1", 9000),
    )
    monkeypatch.setenv("SEGMENTATION_SERVICES_JSON", json.dumps({"fixture": {
        "base_url": "http://127.0.0.1:9000", "local": True, "origin": "mock-fixture",
    }}))
    async with Client(segmentation_server) as client:
        reply = await client.call_tool("image_segment", {"request": {
            "file_path": str(source), "expected_source_sha256": hashlib.sha256(original).hexdigest(),
            "prompt": "object", "service_id": "fixture", "dry_run": False, "submission_authorized": True,
        }})
        metadata = reply.structured_content["metadata"]
        tool = (await client.list_tools())[0]
        validate(reply.structured_content, tool.output_schema)
        assert json.loads(reply.content[0].text) == reply.structured_content
        assert metadata["masks"][0]["coverage"] == 1
        assert metadata["masks"][0]["semantic_correctness_verified"] is False
        artifacts = metadata["artifacts"]
        assert len(reply.content) == len(artifacts) + 1
        for block, artifact in zip(reply.content[1:], artifacts, strict=True):
            assert base64.b64decode(block.data) == Path(artifact["path"]).read_bytes()
    wire = b"".join(network["stream"].writes)
    assert wire.startswith(b"POST /segment HTTP/1.1\r\n")
    sent = json.loads(wire.split(b"\r\n\r\n", 1)[1])
    assert sent["prompt"] == "object" and sent["return_img"] is True
    assert network["connections"] == [("127.0.0.1", 9000)] and network["stream"].closed
    from video_research_mcp.tools.image import image_server

    async with Client(image_server) as restarted:
        manifest = metadata["manifest"]
        readback = await restarted.call_tool("image_manifest_read", {
            "manifest_path": manifest["path"], "expected_sha256": manifest["sha256"],
        })
        assert readback.structured_content["verified"] is True
    assert source.read_bytes() == original


async def test_inflight_operator_profile_change_cannot_rebind_response_provenance(
    tmp_path, monkeypatch, network, image_response
):
    """GIVEN changed operator state WHEN the original response arrives THEN refuse."""
    source, original, response = image_response
    prior = tmp_path / "cache/media/views/retained"
    prior.mkdir(parents=True)
    (prior / "prior.png").write_bytes(original)
    raw = json.dumps(response).encode()
    stream = NetworkStream(
        b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw,
        peer=("127.0.0.1", 9000),
    )
    network["stream"] = stream
    monkeypatch.setenv("SEGMENTATION_SERVICES_JSON", json.dumps({"fixture": {
        "base_url": "http://127.0.0.1:9000", "local": True, "origin": "mock-fixture",
    }}))
    from video_research_mcp.config import get_config

    profile = get_config().segmentation_services["fixture"]
    original_read = stream.read

    async def changed_profile(*args, **kwargs):
        returned = await original_read(*args, **kwargs)
        profile.base_url = "http://127.0.0.1:9000/changed"
        profile.origin = "model-service"
        return returned

    monkeypatch.setattr(stream, "read", changed_profile)
    async with Client(segmentation_server) as client:
        reply = await client.call_tool("image_segment", {"request": {
            "file_path": str(source), "expected_source_sha256": hashlib.sha256(original).hexdigest(),
            "prompt": "object", "service_id": "fixture", "dry_run": False, "submission_authorized": True,
        }}, raise_on_error=False)
        assert reply.is_error
        assert reply.structured_content["reason"] == "service_configuration_changed"
    wire = b"".join(stream.writes)
    assert wire.startswith(b"POST /segment HTTP/1.1\r\n") and stream.closed
    assert set((tmp_path / "cache/media/views").iterdir()) == {prior}
    assert (prior / "prior.png").read_bytes() == original
    assert source.read_bytes() == original
