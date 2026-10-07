"""Missing optional mode boundaries, using closed HTTP and deterministic local media."""

import base64
import hashlib
import importlib
import json
import subprocess
import wave

import httpx
from PIL import Image
import pytest

from tests import test_generation_adapters as fixtures
from video_explainer_mcp import generation as service
from video_explainer_mcp import generation_optional as optional, generation_request as admission
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.models.generation import GenerationRequest
from video_explainer_mcp.tools.generation import explainer_generation_submit, explainer_generation_poll

wire = fixtures.wire
MODELS = list(optional.MODES)
PUBLIC = "https://help-static-aliyun-doc.aliyuncs.com/fixture/{}?Signature=private-input-token"


def pin(project, name):
    return {"path": name, "sha256": fixtures.sha((project / name).read_bytes())}


def image_ref(wire, role="reference", name="image.png", size=(800, 450), public=False):
    Image.new("RGB", size, (120, 40, 20)).save(wire[0] / name)
    result = {"role": role, "source": pin(wire[0], name)}
    if public:
        result["public_url"] = PUBLIC.format(name)
    return result


@pytest.fixture
def movie(wire):
    """Generate a finite first-party color/tone MP4; no model inference or network."""
    path = wire[0] / "input.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
        "color=c=red:s=1280x720:r=25:d=3", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=3", "-t", "3", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
        str(path)], check=True, capture_output=True, timeout=20)
    return path.read_bytes()


def optional_request(wire, model, movie=None, **changes):
    values = dict(model=model, duration=3, expected_dimensions=(1280, 720),
                  prompt="A synthetic fixture", seed=42, references=[])
    if model.endswith("-i2v"):
        values["references"] = [image_ref(wire, "first_frame")]
    elif model.endswith("-r2v"):
        values.update(references=[image_ref(wire, "identity")], prompt="The object in [Image 1] moves")
    elif model.endswith("-video-edit"):
        assert movie is not None
        values["references"] = [{"role": "source_video", "source": pin(wire[0], "input.mp4"),
                                 "public_url": PUBLIC.format("input.mp4")}]
        values["audio_setting"] = "origin"
    elif model == "wan2.2-s2v":
        wire[0].joinpath("audio.wav").write_bytes(b"")
        with wave.open(str(wire[0] / "audio.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\0\0" * 24000)
        values.update(prompt="", seed=0, resolution="480P", expected_dimensions=(640, 480),
                      references=[image_ref(wire, "portrait", size=(640, 480), public=True),
                          {"role": "driving_audio", "source": pin(wire[0], "audio.wav"),
                           "public_url": PUBLIC.format("audio.wav")}])
        from video_explainer_mcp import config
        config._config.dashscope_base_url = fixtures.BASE.replace("ap-southeast-1", "cn-beijing")
    values.update(changes)
    req = fixtures.request(wire, **values)
    return requote(wire, req)


def requote(wire, req):
    from video_explainer_mcp import config
    origin = config._config.dashscope_base_url
    quote = json.loads((wire[0] / "quote.json").read_text())
    access = json.loads((wire[0] / "access-source.json").read_text())
    access.update(api_origin=origin, source_url=origin + "/tasks/operator-declared-evidence")
    quote.update(api_origin=origin, contract_sha256=fixtures.digest(admission.contract_for(req.model)),
                 model_access_source=fixtures.pinned_json(wire[0], "access-source.json", access))
    body = req.model_dump(mode="json")
    body.pop("quote")
    quote["request_sha256"] = fixtures.digest(body)
    return GenerationRequest.model_validate({**req.model_dump(mode="json"),
        "quote": fixtures.pinned_json(wire[0], "quote.json", quote)})


def public_responses(wire, req, changed=False):
    for ref in req.references:
        if ref.public_url:
            body = (wire[0] / ref.source.path).read_bytes()
            wire[2].append(httpx.Response(200, content=b"changed" if changed else body))


@pytest.mark.parametrize("model", MODELS)
async def test_exact_mode_wire_and_ambiguous_submit_never_reposts(wire, movie, model):
    req = optional_request(wire, model, movie)
    public_responses(wire, req)
    wire[2].append(httpx.ReadTimeout("private-api-token ambiguous POST"))
    result = await explainer_generation_submit("fixture", req)
    posts = [r for r in wire[1] if r.method == "POST"]
    assert len(posts) == 1 and result["status"] == "unknown"
    body = json.loads(posts[0].content)
    assert body["model"] == model and posts[0].url.path.endswith(optional.ENDPOINTS[model])
    assert "negative_prompt" not in body["input"] and "prompt_extend" not in body["parameters"]
    if model == "wan2.2-s2v":
        assert body["parameters"] == {"resolution": "480P"}
        assert body["input"] == {"image_url": req.references[0].public_url,
                                  "audio_url": req.references[1].public_url}
    elif model.endswith("-video-edit"):
        assert body["input"]["media"][0]["type"] == "video"
        assert "duration" not in body["parameters"] and "ratio" not in body["parameters"]
    elif req.references:
        assert len(body["input"]["media"]) == len(req.references)
        actual = base64.b64decode(body["input"]["media"][0]["url"].split(",")[1])
        assert fixtures.sha(actual) == req.references[0].source.sha256
    importlib.reload(service)
    assert (await explainer_generation_submit("fixture", req))["job_id"] == result["job_id"]
    await service.poll_generation(result["job_id"], fixtures.operation("no-task-resume"))
    assert len([r for r in wire[1] if r.method == "POST"]) == 1
    assert "private-input-token" not in json.dumps(result) and "private-api-token" not in json.dumps(result)


@pytest.mark.parametrize("model,count", [("happyhorse-1.0-r2v", 10), ("happyhorse-1.0-video-edit", 6)])
async def test_reference_overflow_rejected_without_effect(wire, movie, model, count):
    req = optional_request(wire, model, movie)
    refs = [image_ref(wire, name=f"ref-{n}.png") for n in range(count)]
    if model.endswith("-video-edit"):
        refs.insert(0, req.references[0].model_dump(mode="json"))
    req = optional_request(wire, model, movie, references=refs)
    result = await explainer_generation_submit("fixture", req)
    assert "error" in result and not wire[1]


@pytest.mark.parametrize("model,changes", [
    ("happyhorse-1.0-t2v", {"transparent_background": True}),
    ("happyhorse-1.0-t2v", {"negative_prompt": "ignored"}),
    ("happyhorse-1.0-i2v", {"prompt_extend": True}),
    ("happyhorse-1.0-i2v", {"audio_setting": "origin"}),
    ("happyhorse-1.0-r2v", {"duration": 2}),
    ("happyhorse-1.0-r2v", {"prompt": "Missing ordered image token"}),
    ("wan2.2-s2v", {"seed": 1}),
    ("wan2.2-s2v", {"resolution": "1080P"}),
    ("wan2.2-s2v", {"expected_audio": "absent"}),
])
async def test_cross_mode_control_mismatch_has_zero_effect(wire, movie, model, changes):
    req = optional_request(wire, model, movie, **changes)
    assert "error" in await explainer_generation_submit("fixture", req)
    assert not wire[1]


@pytest.mark.parametrize("defect", ["role", "media-kind", "missing", "hash", "source-script", "dimensions"])
async def test_reference_and_source_counterexamples_have_zero_effect(wire, defect):
    req = optional_request(wire, "happyhorse-1.0-i2v")
    ref = req.references[0].model_dump(mode="json")
    changes = {}
    if defect == "role":
        ref["role"] = "driving_audio"
    elif defect == "media-kind":
        (wire[0] / "image.png").write_bytes(b"not an image")
        ref["source"] = pin(wire[0], "image.png")
    elif defect == "missing":
        (wire[0] / "image.png").unlink()
    elif defect == "hash":
        ref["source"]["sha256"] = "0" * 64
    elif defect == "source-script":
        (wire[0] / "script.json").unlink()
    else:
        changes["expected_dimensions"] = None
    req = GenerationRequest.model_validate({**req.model_dump(mode="json"), "references": [ref], **changes})
    assert "error" in await explainer_generation_submit("fixture", req)
    assert not wire[1]


async def test_public_body_mismatch_does_not_post_or_retry(wire):
    req = optional_request(wire, "wan2.2-s2v")
    public_responses(wire, req, changed=True)
    result = await explainer_generation_submit("fixture", req)
    assert result["status"] == "unknown" and not [r for r in wire[1] if r.method == "POST"]
    await explainer_generation_submit("fixture", req)
    assert len(wire[1]) == 1


@pytest.mark.parametrize("model", MODELS)
async def test_pending_failure_budget_cancel_and_task_identity_survive_reload(wire, movie, model):
    req = optional_request(wire, model, movie)
    public_responses(wire, req)
    wire[2].append(fixtures.task())
    first = await explainer_generation_submit("fixture", req)
    assert first["status"] == "running" and first["provider_operation_id"] == "provider-task"
    importlib.reload(service)
    wire[2].append(fixtures.task("RUNNING"))
    pending = await explainer_generation_poll(first["job_id"], fixtures.operation("resume"))
    assert pending["status"] == "running"
    wire[2].append(fixtures.task("FAILED"))
    failed = await explainer_generation_poll(first["job_id"], fixtures.operation("failure"))
    assert failed["status"] == "failed" and failed["provider_operation_id"] == "provider-task"
    assert len([r for r in wire[1] if r.method == "POST"]) == 1


async def test_optional_cancel_confirmation_and_budget(wire):
    req = optional_request(wire, "happyhorse-1.0-t2v", max_polls=2)
    wire[2].append(fixtures.task())
    first = await explainer_generation_submit("fixture", req)
    wire[2].extend([fixtures.task(), httpx.Response(200, json="cancel-ack"), fixtures.task("CANCELED")])
    result = await service.cancel_generation(first["job_id"], fixtures.operation("cancel"))
    assert result["status"] == "cancelled" and result["provider_operation_id"] == "provider-task"
    assert result["state"]["poll_count"] == 2
    req = optional_request(wire, "happyhorse-1.0-t2v", logical_job_id="budget", max_polls=2)
    wire[2].append(fixtures.task(task_id="budget-task"))
    first = await explainer_generation_submit("fixture", req)
    for name in ("poll-1", "poll-2"):
        wire[2].append(fixtures.task(task_id="budget-task"))
        await service.poll_generation(first["job_id"], fixtures.operation(name))
    before = len(wire[1])
    with pytest.raises(ValueError, match="budget exhausted"):
        await service.poll_generation(first["job_id"], fixtures.operation("poll-3"))
    assert len(wire[1]) == before and JobStore().get(first["job_id"])["external_id"] == "budget-task"


@pytest.mark.parametrize("model", MODELS[1:])
async def test_full_decode_hash_handoff_and_continuation_survive_reload(wire, movie, model):
    req = optional_request(wire, model, movie)
    settings = {"model": model, "controls": optional.controls(req.model_dump(mode="json")),
                "references": [r.model_dump(mode="json") for r in req.references]}
    continuation = fixtures.pinned_json(wire[0], "continuation.json", settings)
    req = requote(wire, GenerationRequest.model_validate({**req.model_dump(mode="json"), "continuation": continuation}))
    public_responses(wire, req)
    wire[2].append(fixtures.task())
    first = await explainer_generation_submit("fixture", req)
    wire[2].extend([fixtures.task("SUCCEEDED", video_url=fixtures.URL), httpx.Response(200, content=movie)])
    result = await explainer_generation_poll(first["job_id"], fixtures.operation("complete"))
    assert result["status"] == "completed", result
    asset = result["state"]["asset"]
    assert asset["sha256"] == hashlib.sha256(movie).hexdigest()
    assert asset["qualification"]["full_decode"] and asset["qualification"]["media"]["audio_present"]
    assert asset["handoff"]["label"] == "synthetic illustrative"
    assert asset["handoff"]["script"] == req.script.model_dump()
    assert asset["handoff"]["continuation"] == req.continuation.model_dump()
    assert "private-input-token" not in json.dumps(result) and "private-output-token" not in json.dumps(result)
    importlib.reload(service)
    replay = await explainer_generation_submit("fixture", req)
    assert replay["status"] == "completed" and replay["state"]["asset"] == asset
    stored = JobStore().get(first["job_id"])
    evidence = stored["result"]["provider_evidence"][-1]
    assert hashlib.sha256(base64.b64decode(evidence["body_base64"])).hexdigest() == evidence["sha256"]
    stored["result"]["asset"].pop("handoff")
    assert service._view(stored)["status"] == "unknown"
    (wire[0] / "scene.json").write_bytes(b"changed source")
    assert (await explainer_generation_submit("fixture", req))["status"] == "unknown"


async def test_s2v_nested_result_full_decode(wire):
    req = optional_request(wire, "wan2.2-s2v")
    output = wire[0] / "output.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
        "color=c=blue:s=640x480:r=25:d=3", "-i", str(wire[0] / "audio.wav"), "-t", "3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output)],
        check=True, capture_output=True, timeout=20)
    body = output.read_bytes()
    public_responses(wire, req)
    wire[2].append(fixtures.task())
    first = await explainer_generation_submit("fixture", req)
    wire[2].extend([fixtures.task("SUCCEEDED", results={"video_url": fixtures.URL}), httpx.Response(200, content=body)])
    result = await explainer_generation_poll(first["job_id"], fixtures.operation("finish-s2v"))
    assert result["status"] == "completed", result
    assert result["state"]["asset"]["sha256"] == fixtures.sha(body)
    assert result["state"]["asset"]["qualification"]["media"]["width"] == 640


def test_continuation_and_video_truncation_are_rejected(wire, movie):
    req = optional_request(wire, "happyhorse-1.0-video-edit", movie)
    continuation = fixtures.pinned_json(wire[0], "continuation.json", {"model": "other"})
    req = GenerationRequest.model_validate({**req.model_dump(mode="json"), "continuation": continuation})
    with pytest.raises(ValueError, match="Continuation"):
        admission.freeze_request("fixture", req)
    probe = {"format": {"format_name": "mov,mp4", "duration": "16"}, "streams": [{"codec_type": "video", "codec_name": "h264"}]}
    original = subprocess.run
    try:
        subprocess.run = lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, json.dumps(probe).encode(), b"")
        with pytest.raises(ValueError, match="truncation refused"):
            optional.inspect_av(movie, "video")
    finally:
        subprocess.run = original
