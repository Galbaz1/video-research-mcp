"""Selected segmentation wire contract through HTTPX/HTTPCore/H11 mock streams."""

import asyncio
import base64
import json
import logging
import socket

from httpcore._backends.auto import AutoBackend
from pydantic import ValidationError
import pytest

from tests.test_segmentation_images import fixture_pngs, response_fixture
from tests.test_vision_http import NetworkStream
from video_research_mcp.config import get_config
from video_research_mcp.models.segmentation import SegmentationRequest, SegmentationService
from video_research_mcp import segmentation_service as service


def response_wire(payload, status=200):
    """Frame a first-party response without opening a socket or bypassing H11."""
    body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    return f"HTTP/1.1 {status} Mock\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body


@pytest.fixture
async def network(monkeypatch):
    """Substitute only DNS/connect boundaries; retain installed transport execution."""
    state = {"dns": [], "connections": [], "stream": NetworkStream(response_wire(response_fixture()), ("127.0.0.1", 8787))}
    async def resolve(host, port, **kwargs):
        state["dns"].append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]
    async def connect(self, host, port, **kwargs):
        state["connections"].append((host, port))
        return state["stream"]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    return state


@pytest.fixture
def selected(monkeypatch, clean_config):
    """Configure only this mock operator profile and a fake environment key."""
    profile = SegmentationService(base_url="http://127.0.0.1:8787", local=True, origin="mock-fixture", api_key_env="SEGMENTATION_FIXTURE_KEY")
    get_config().segmentation_services = {"fixture": profile}
    monkeypatch.setenv("SEGMENTATION_FIXTURE_KEY", "fixture-private-key")
    request = SegmentationRequest(file_path="/unread.png", expected_source_sha256="0" * 64,
                                  prompt="rectangle", service_id="fixture", dry_run=False, submission_authorized=True)
    return request, service.selected_service(request)


async def test_actual_single_post_keeps_exact_sam_wire_and_private_transport(network, selected, caplog):
    request, profile = selected
    caplog.set_level(logging.DEBUG, logger="httpcore.http11")
    caplog.set_level(logging.INFO, logger="httpx")
    response, raw = await service.submit(request, profile, fixture_pngs()["source"])
    wire = b"".join(network["stream"].writes)
    headers, body = wire.split(b"\r\n\r\n", 1)
    assert headers.startswith(b"POST /segment HTTP/1.1")
    assert b"Authorization: Bearer fixture-private-key" in headers
    payload = json.loads(body)
    assert set(payload) == {"image_b64", "prompt", "return_img"}
    assert base64.b64decode(payload["image_b64"], validate=True) == fixture_pngs()["source"]
    assert payload["prompt"] == "rectangle" and payload["return_img"] is True
    assert response == response_fixture() and json.loads(raw) == response_fixture()
    assert network["connections"] == [("127.0.0.1", 8787)] and not network["dns"]
    assert network["stream"].closed and not network["stream"].tls
    assert "fixture-private-key" not in caplog.text


async def test_remote_declared_profile_reuses_public_dns_peer_proof(network, selected, monkeypatch):
    request, _ = selected
    profile = SegmentationService(base_url="https://segment.example/v1", origin="model-service", declared_model="operator-assertion", checkpoint_sha256="1" * 64)
    get_config().segmentation_services = {"fixture": profile}
    network["stream"].peer = ("8.8.8.8", 443)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    await service.submit(request, service.selected_service(request), fixture_pngs()["source"])
    assert network["dns"] == [("segment.example", 443)]
    assert network["connections"] == [("8.8.8.8", 443)]
    assert b"".join(network["stream"].writes).startswith(b"POST /v1/segment HTTP/1.1")
    assert network["stream"].tls[0][0] == "segment.example"


@pytest.mark.parametrize("damage", ["missing", "key", "grant", "changed"])
async def test_missing_configuration_key_or_grant_refuses_before_exchange(selected, network, monkeypatch, damage):
    request, profile = selected
    if damage == "missing":
        get_config().segmentation_services = {}
    elif damage == "key":
        monkeypatch.delenv("SEGMENTATION_FIXTURE_KEY")
    elif damage == "grant":
        request = request.model_copy(update={"submission_authorized": False})
    else:
        monkeypatch.setenv("SEGMENTATION_FIXTURE_KEY", "different-fixture-key")
    with pytest.raises(service.SegmentationError):
        await service.submit(request, profile, fixture_pngs()["source"])
    assert not network["connections"] and not network["stream"].writes


@pytest.mark.parametrize("damage,reason", [("status", "service_http_error"), ("redirect", "service_http_error"),
                                           ("json", "response_json_invalid"), ("oversize", "service_transport_failed"),
                                           ("peer", "service_transport_failed"), ("timeout", "service_timeout")])
async def test_transport_refusal_is_fixed_private_joined_and_never_retried(network, selected, monkeypatch, damage, reason):
    request, profile = selected
    if damage in {"status", "redirect"}:
        network["stream"].response = response_wire(b"fixture-private-key https://signed.invalid/?token=secret", 500 if damage == "status" else 302)
    elif damage == "json":
        network["stream"].response = response_wire(b"{fixture-private-key")
    elif damage == "oversize":
        network["stream"].response = response_wire(b"x" * (262144 + 1))
    elif damage == "peer":
        network["stream"].peer = ("127.0.0.2", 8787)
    else:
        network["stream"].block_read = True
        monkeypatch.setattr("video_research_mcp.vision_http.EXCHANGE_TIMEOUT_SECONDS", 0.03)
    with pytest.raises(service.SegmentationError) as caught:
        await service.submit(request, profile, fixture_pngs()["source"])
    assert str(caught.value) == reason and len(network["connections"]) == 1
    assert network["stream"].closed
    if damage == "peer":
        assert not network["stream"].writes


@pytest.mark.parametrize("changes", [{"base_url": "http://remote.example"}, {"base_url": "https://user:secret@remote.example"},
    {"base_url": "https://remote.example?secret=x"}, {"base_url": "https://remote.example#x"},
    {"base_url": "https://127.0.0.1"}, {"base_url": "http://localhost", "local": True},
    {"base_url": "http://127.0.0.2", "local": True}, {"base_url": "https://remote.example", "local": "false"}])
def test_profile_rejects_uncontrolled_or_nonliteral_origins(changes):
    with pytest.raises(ValidationError):
        SegmentationService.model_validate({"base_url": "https://segment.example", "origin": "mock-fixture", **changes})
