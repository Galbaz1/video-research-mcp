"""Causal optional admission checks through real freeze and closed HTTP submit."""

from decimal import Decimal
import importlib
import json
import subprocess
import wave

import pytest

from tests import test_generation_adapters as fixtures
from tests import test_generation_optional_modes as modes
from video_explainer_mcp import generation as service, generation_request as admission
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.models.generation import GenerationRequest
from video_explainer_mcp.tools.generation import explainer_generation_submit

wire = fixtures.wire
MODELS = modes.MODELS
WHOLE_MEDIA = ["wan2.2-s2v", "happyhorse-1.0-video-edit"]


def fractional_request(wire, model, **changes):
    """Pin an actual 3.08-second whole WAV or H264 video with declared duration 3."""
    movie = None
    if model.endswith("-video-edit"):
        path = wire[0] / "input.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
            "color=c=red:s=1280x720:r=25:d=3.08", "-t", "3.08", "-an", "-c:v",
            "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
        ], check=True, capture_output=True, timeout=20)
        movie = path.read_bytes()
        changes["expected_audio"] = "absent"
    req = modes.optional_request(wire, model, movie, **changes)
    if model == "wan2.2-s2v":
        with wave.open(str(wire[0] / "audio.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * 24640)
        refs = [ref.model_dump(mode="json") for ref in req.references]
        refs[1]["source"] = modes.pin(wire[0], "audio.wav")
        req = GenerationRequest.model_validate({**req.model_dump(mode="json"), "references": refs})
        req = modes.requote(wire, req)
    return req


@pytest.mark.parametrize("model", WHOLE_MEDIA)
async def test_whole_media_cost_ceiling_refuses_before_any_http(wire, model):
    """A fractional whole input cannot use a rounded declared-duration ceiling."""
    req = fractional_request(wire, model, max_cost="0.03")
    modes.public_responses(wire, req)
    wire[2].append(fixtures.task())
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result, result
    assert not wire[1]
    assert not JobStore().list_active(service.KIND)


@pytest.mark.parametrize("model", WHOLE_MEDIA)
@pytest.mark.parametrize("duration,max_cost", [(3, "0.04"), (3.08, "0.0308")])
async def test_funded_fractional_media_prices_whole_input_and_submits_once(
    wire, monkeypatch, model, duration, max_cost,
):
    """Both quote reads retain measured seconds and whole pinned public bytes."""
    req = fractional_request(wire, model, duration=duration, max_cost=max_cost)
    frozen, source = admission.freeze_request("fixture", req)
    assert frozen["expected_seconds"] == 3.08
    assert Decimal(frozen["quote"]["total_cost"]) == Decimal("0.0308")
    quotes = []
    original = service.read_operator_quote

    def observe_quote(*args):
        quote = original(*args)
        quotes.append(quote)
        return quote

    monkeypatch.setattr(service, "read_operator_quote", observe_quote)
    modes.public_responses(wire, req)
    wire[2].append(fixtures.task())
    result = await explainer_generation_submit("fixture", req)
    assert result["status"] == "running", result
    assert len(quotes) == 1 and quotes[0] == frozen["quote"]
    row = JobStore().get(result["job_id"])
    assert row["request"]["expected_seconds"] == 3.08
    assert row["source_revision"] == source
    assert row["request"]["generation"] == req.model_dump(mode="json")
    assert row["request_sha256"] == fixtures.digest({
        "kind": service.KIND, "request": row["request"], "source_revision": source,
        "exclusive_key": row["job_id"],
    })
    assert row["attestation"]["request_integrity"] == "verified"
    assert row["request"]["quote"] == frozen["quote"]
    for metadata in row["request"]["reference_metadata"]:
        assert metadata["source"]["sha256"] == modes.pin(wire[0], metadata["source"]["path"])["sha256"]
        if metadata["kind"] in {"audio", "video"}:
            assert metadata["duration_seconds"] == 3.08
    posts = [request for request in wire[1] if request.method == "POST"]
    assert len(posts) == 1
    body = json.loads(posts[0].content)
    assert "duration" not in body["parameters"]
    assert all(request.method == "GET" for request in wire[1][:-1])
    importlib.reload(service)
    assert (await explainer_generation_submit("fixture", req))["job_id"] == result["job_id"]
    assert len([request for request in wire[1] if request.method == "POST"]) == 1


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("defect", ["tiny", "wrong-tier", "wrong-aspect"])
async def test_optional_geometry_refuses_before_any_effect(wire, model, defect):
    """Tier and actual/declared aspect must agree before even reference HTTP."""
    if model.endswith("-video-edit"):
        req = fractional_request(wire, model)
    else:
        req = modes.optional_request(wire, model)
    pixels = ((16, 16) if defect == "tiny" else
              (1920, 1440) if req.resolution == "480P" and defect == "wrong-tier" else
              (1920, 1088) if defect == "wrong-tier" else
              (560, 560) if req.resolution == "480P" else (960, 960))
    req = modes.requote(wire, GenerationRequest.model_validate({
        **req.model_dump(mode="json"), "expected_dimensions": pixels,
    }))
    modes.public_responses(wire, req)
    wire[2].append(fixtures.task())
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result, result
    assert not wire[1]
    assert not JobStore().list_active(service.KIND)


@pytest.mark.parametrize("model,resolution,ratio,pixels,image_size", [
    ("happyhorse-1.0-t2v", "720P", "16:9", (1280, 720), None),
    ("happyhorse-1.0-t2v", "1080P", "16:9", (1920, 1080), None),
    ("happyhorse-1.0-t2v", "720P", "9:16", (720, 1280), None),
    ("happyhorse-1.0-t2v", "720P", "4:3", (1104, 832), None),
    ("happyhorse-1.0-r2v", "1080P", "1:1", (1440, 1440), None),
    ("happyhorse-1.0-i2v", "1080P", None, (1920, 1080), (800, 450)),
    ("wan2.2-s2v", "480P", None, (640, 480), (640, 480)),
    ("wan2.2-s2v", "480P", None, (480, 600), (400, 500)),
    ("wan2.2-s2v", "720P", None, (1280, 720), (800, 450)),
    ("happyhorse-1.0-video-edit", "1080P", None, (1920, 1080), None),
])
async def test_supported_tier_aspect_geometries_reach_one_submit(
    wire, model, resolution, ratio, pixels, image_size,
):
    """Accept tier/aspect-compatible declarations without an exact provider grid."""
    changes = dict(resolution=resolution, ratio=ratio, expected_dimensions=pixels)
    req = (fractional_request(wire, model, **changes) if model.endswith("-video-edit") else
           modes.optional_request(wire, model, **changes))
    if image_size:
        refs = [ref.model_dump(mode="json") for ref in req.references]
        refs[0] = modes.image_ref(wire, refs[0]["role"], size=image_size, public=model == "wan2.2-s2v")
        req = modes.requote(wire, GenerationRequest.model_validate({
            **req.model_dump(mode="json"), "references": refs,
        }))
    modes.public_responses(wire, req)
    wire[2].append(fixtures.task())
    result = await explainer_generation_submit("fixture", req)
    assert result["status"] == "running", result
    assert JobStore().get(result["job_id"])["request"]["expected_pixels"] == list(pixels)
    assert len([request for request in wire[1] if request.method == "POST"]) == 1
