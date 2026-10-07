"""Source/mock Wan frame admission and wire tests; no native decoder qualification."""

import importlib
import json
import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from tests import test_generation_adapters as fixtures
from video_explainer_mcp import config, generation as service
from video_explainer_mcp import generation_assets as assets
from video_explainer_mcp import generation_references as references
from video_explainer_mcp import generation_request as admission
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.planning_sources import digest
from video_explainer_mcp.tools.generation import explainer_generation_submit

wire = fixtures.wire


class MockImage:
    """A closed decoder surrogate whose inputs are explicitly mock JSON bytes."""

    def __init__(self, body):
        self.value = json.loads(body)
        self.format = self.value.get("format", "PNG")
        self.size = self.value.get("width", 320), self.value.get("height", 240)
        self.n_frames = self.value.get("n_frames", 1)
        self.info = {"transparency": 0} if self.value.get("transparency") else {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getbands(self):
        return tuple(self.value.get("bands", "RGB"))

    def getexif(self):
        return {274: self.value.get("orientation", 1)}

    def verify(self):
        if self.value.get("verify_failure"):
            raise OSError("mock decoder verification failure")

    def load(self):
        if self.value.get("decode_failure"):
            raise OSError("mock decoder load failure")


@pytest.fixture(autouse=True)
def closed_image_decoder(monkeypatch):
    """Exercise decoder calls with no Pillow/native execution or package install."""
    module = ModuleType("PIL")
    module.Image = SimpleNamespace(
        open=lambda stream: MockImage(stream.getvalue()), DecompressionBombError=OSError)
    monkeypatch.setitem(sys.modules, "PIL", module)


def frame(wire, role="first_frame", **properties):
    """Pin explicitly synthetic mock decoder input without a native image fixture."""
    name = role + ".mock-image"
    body = json.dumps({"format": "PNG", "width": 320, "height": 240, **properties}).encode()
    (wire[0] / name).write_bytes(body)
    return {"role": role, "source": {"path": name, "sha256": fixtures.sha(body)}}


def i2v_request(wire, **changes):
    value = dict(model="wan2.7-i2v", ratio="4:3", expected_dimensions=(1120, 832),
                 references=changes["references"] if "references" in changes else [frame(wire)])
    value.update(changes)
    return fixtures.request(wire, **value)


def job_id():
    return "wan-" + digest({"project_id": "fixture", "logical_job_id": "one-logical-job"})[:32]


@pytest.mark.parametrize("roles", [("first_frame",), ("first_frame", "last_frame"),
                                    ("last_frame", "first_frame")])
async def test_exact_frame_wire_and_frozen_controls_survive_reload(wire, roles):
    refs = [frame(wire, role) for role in roles]
    req = i2v_request(wire, references=refs, prompt_extend=True, watermark=False)
    originals = [(wire[0] / ref["source"]["path"]).read_bytes() for ref in refs]
    wire[2].append(fixtures.task())
    result = await explainer_generation_submit("fixture", req)
    assert result["status"] == "running" and len(wire[1]) == 1
    payload = json.loads(wire[1][0].content)
    assert payload["model"] == references.I2V_WIRE_MODEL
    assert "ratio" not in payload["parameters"] and "img_url" not in payload["input"]
    assert payload["parameters"] == dict(duration=2, resolution="720P", seed=42,
                                          prompt_extend=True, watermark=False)
    import base64

    for item, role, original in zip(payload["input"]["media"], roles, originals, strict=True):
        assert item["type"] == role and item["url"].startswith("data:image/png;base64,")
        assert base64.b64decode(item["url"].split(",", 1)[1], validate=True) == original
    row = JobStore().get(result["job_id"])
    assert row["request"]["generation"] == req.model_dump(mode="json")
    assert row["request"]["expected_pixels"] == [1120, 832]
    assert row["request"]["dimension_basis"] == "caller_declared_i2v_output_not_provider_guarantee"
    assert row["request"]["mode"] == ("first_frame" if len(roles) == 1 else "first_last_frame")
    assert "generation_references.py" in row["request"]["adapter_revision"]
    assert row["request"]["quote"]["model"] == "wan2.7-i2v"
    assert row["request"]["quote"]["total_cost"] == "0.02"
    importlib.reload(service)
    replay = await explainer_generation_submit("fixture", req)
    assert replay["state"]["request"] == req.model_dump(mode="json") and len(wire[1]) == 1


@pytest.mark.parametrize("properties", [
    {"format": "GIF"}, {"format": "TIFF"}, {"width": 239}, {"height": 8001},
    {"width": 240, "height": 1921}, {"bands": "RGBA"}, {"transparency": True},
    {"orientation": 6}, {"n_frames": 2}, {"verify_failure": True}, {"decode_failure": True},
])
async def test_decoded_frame_limits_refuse_before_reservation(wire, properties):
    req = i2v_request(wire, references=[frame(wire, **properties)])
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and not wire[1] and JobStore().get(job_id()) is None


@pytest.mark.parametrize("format,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"),
                                       ("BMP", "image/bmp"), ("WEBP", "image/webp")])
def test_selected_actual_format_drives_mime_not_filename(wire, format, mime):
    ref = frame(wire, format=format)
    req = i2v_request(wire, references=[ref])
    frozen, _ = admission.freeze_request("fixture", req)
    payload = admission.provider_payload(frozen)
    assert payload["input"]["media"][0]["url"].startswith(f"data:{mime};base64,")
    assert frozen["reference_metadata"][0]["format"] == format


@pytest.mark.parametrize("roles", [(), ("last_frame",), ("identity",), ("style",),
                                    ("driving_audio",), ("first_clip",),
                                    ("first_frame", "first_frame"),
                                    ("first_frame", "last_frame", "style")])
async def test_role_combinations_are_preserved_and_refused(wire, roles):
    req = i2v_request(wire, references=[frame(wire, role) for role in roles])
    assert [ref.role for ref in req.references] == list(roles)
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and not wire[1] and JobStore().get(job_id()) is None


@pytest.mark.parametrize("changes", [{"expected_dimensions": None},
                                    {"expected_dimensions": (1119, 832)},
                                    {"expected_dimensions": (960, 960)},
                                    {"ratio": "16:9"}, {"expected_audio": "absent"},
                                    {"transparent_background": True}])
async def test_i2v_declared_metadata_refuses_before_reservation(wire, changes):
    result = await explainer_generation_submit("fixture", i2v_request(wire, **changes))
    assert "error" in result and not wire[1] and JobStore().get(job_id()) is None


async def test_continuation_is_not_silently_translated(wire):
    ref = frame(wire, "first_clip")["source"]
    req = i2v_request(wire, continuation=ref)
    result = await explainer_generation_submit("fixture", req)
    assert req.continuation.model_dump() == ref
    assert "error" in result and not wire[1] and JobStore().get(job_id()) is None


@pytest.mark.parametrize("change", ["missing", "changed", "oversize", "symlink"])
async def test_invalid_reference_bytes_never_reserve_or_post(wire, change):
    req = i2v_request(wire)
    path = wire[0] / req.references[0].source.path
    if change == "missing":
        path.unlink()
    elif change == "changed":
        path.write_bytes(b"changed")
    elif change == "oversize":
        with path.open("wb") as stream:
            stream.truncate(references.MAX_IMAGE_BYTES + 1)
    else:
        path.unlink()
        path.symlink_to(wire[0] / "script.json")
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and not wire[1] and JobStore().get(job_id()) is None


async def test_missing_image_decoder_is_pre_reservation_refusal(wire, monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    result = await explainer_generation_submit("fixture", i2v_request(wire))
    assert "Pillow image decoder" in result["error"]
    assert not wire[1] and JobStore().get(job_id()) is None


@pytest.mark.parametrize("mutation", ["reference", "origin"])
async def test_final_snapshot_or_origin_change_prevents_post_and_retry(wire, monkeypatch, mutation):
    req = i2v_request(wire)
    original = service.read_operator_quote

    def change_after_quote(*args):
        quote = original(*args)
        if mutation == "reference":
            (wire[0] / req.references[0].source.path).write_bytes(b"changed after quote")
        else:
            config._config.dashscope_base_url = fixtures.BASE.replace("fixture.", "changed.")
        return quote

    monkeypatch.setattr(service, "read_operator_quote", change_after_quote)
    result = await explainer_generation_submit("fixture", req)
    assert result["status"] == "unknown" and not wire[1]
    assert result["provider_operation_id"] is None
    await explainer_generation_submit("fixture", req)
    assert not wire[1]


def test_source_guard_runs_after_encoding(wire, monkeypatch):
    req = i2v_request(wire)
    frozen, _ = admission.freeze_request("fixture", req)
    original = references.inspect_image

    def change_origin(body):
        metadata = original(body)
        config._config.dashscope_base_url = fixtures.BASE.replace("fixture.", "changed.")
        return metadata

    monkeypatch.setattr(references, "inspect_image", change_origin)
    with pytest.raises(ValueError, match="origin differs"):
        admission.provider_payload(frozen)
    assert not wire[1]


@pytest.mark.parametrize("field", ["contract", "adapter_revision", "wire_model"])
def test_new_effect_contract_and_source_guards(wire, field):
    frozen, _ = admission.freeze_request("fixture", i2v_request(wire))
    frozen[field] = "changed" if field == "wire_model" else {}
    with pytest.raises(ValueError):
        admission.provider_payload(frozen)
    assert not wire[1]


def test_i2v_output_dimensions_are_declared_and_measured(wire):
    frozen, _ = admission.freeze_request("fixture", i2v_request(wire))
    measured = assets.measured_media(fixtures.metadata(width=1120, height=832), frozen)
    assert measured["width"] == 1120 and measured["height"] == 832 and measured["audio_present"]
    with pytest.raises(ValueError, match="dimensions"):
        assets.measured_media(fixtures.metadata(width=1104, height=832), frozen)
    frozen["expected_pixels"] = [1104, 832]
    with pytest.raises(ValueError, match="model-specific metadata"):
        assets.measured_media(fixtures.metadata(width=1104, height=832), frozen)


async def test_i2v_timeout_stays_unknown_across_reload(wire):
    req = i2v_request(wire)
    wire[2].append(httpx.ReadTimeout("mock timeout"))
    result = await explainer_generation_submit("fixture", req)
    assert result["status"] == "unknown" and result["state"]["submit_count"] == 1
    importlib.reload(service)
    replay = await explainer_generation_submit("fixture", req)
    assert replay["job_id"] == result["job_id"] and len(wire[1]) == 1


async def test_i2v_pending_cancel_keeps_exact_request_and_counters(wire):
    req = i2v_request(wire)
    wire[2].append(fixtures.task())
    first = await explainer_generation_submit("fixture", req)
    wire[2].extend([fixtures.task(), httpx.Response(200, json="cancel-request"), fixtures.task("CANCELED")])
    result = await service.cancel_generation(first["job_id"], fixtures.operation("cancel-i2v"))
    assert result["status"] == "cancelled" and result["state"]["cancel_count"] == 1
    assert result["state"]["poll_count"] == 2 and result["state"]["request"] == req.model_dump(mode="json")
    assert len(wire[1]) == 4


def test_legacy_t2v_default_schema_bytes_and_wire_are_preserved(wire):
    req = fixtures.request(wire)
    body = req.model_dump(mode="json")
    assert not {"expected_dimensions", "prompt_extend", "watermark"} & body.keys()
    frozen, _ = admission.freeze_request("fixture", req)
    payload = admission.provider_payload(frozen)
    assert payload["model"] == "wan2.7-t2v" and "media" not in payload["input"]
    assert payload["parameters"] == dict(duration=2, resolution="720P", ratio="16:9", seed=42,
                                          prompt_extend=False, watermark=True)
