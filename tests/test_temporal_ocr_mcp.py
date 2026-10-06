"""Authored native fixtures and real FastMCP source journey with exact lineage."""

import asyncio
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastmcp import Client
from jsonschema import validate
from PIL import Image, ImageDraw

from video_research_mcp import image_ocr, media_frames, media_probe
from video_research_mcp.models.video_evidence import TemporalOCRRequest
from video_research_mcp.tools.video_evidence import video_evidence_server
from video_research_mcp.transcript_formats import encoded, write_artifact


def sha(data):
    return hashlib.sha256(data).hexdigest()


def set_frames(env, texts, *, confidence=0.7, dimensions=(192, 96)):
    """Declare authored native boundary observations, not a real encoded video oracle."""
    env["source"].write_text(
        json.dumps(
            {
                "width": dimensions[0],
                "height": dimensions[1],
                "frames": [
                    {"pts": 7200 + i * 600, "text": text, "confidence": confidence}
                    for i, text in enumerate(texts)
                ],
            }
        )
    )


async def probe(env, command, timeout):
    env["commands"].append(command)
    data = json.loads(Path(command[-1]).read_text())
    return json.dumps(
        {
            "format": {"duration": "8", "start_time": "7"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "width": data["width"],
                    "height": data["height"],
                    "sample_aspect_ratio": "1:1",
                    "time_base": "1/1000",
                    "start_time": "7",
                    "duration": "8",
                }
            ],
        }
    ).encode(), b""


async def decode(env, command, timeout):
    env["commands"].append(command)
    data = json.loads(Path(command[command.index("-i") + 1]).read_text())
    filters = command[command.index("-vf") + 1]
    point = float(re.search(r"gte\(t,([\d.]+)\)", filters)[1])
    index = next(i for i, row in enumerate(data["frames"]) if row["pts"] / 1000 >= point)
    row = data["frames"][index]
    env["current"] = index, row
    image = Image.new("RGB", (data["width"], data["height"]), "#dddddd")
    ImageDraw.Draw(image).text((24, 16), str(row["text"]), fill="black")
    if match := re.search(r"crop=(\d+):(\d+):(\d+):(\d+)", filters):
        width, height, x, y = map(int, match.groups())
        image = image.crop((x, y, x + width, y + height))
    width, height = map(int, re.search(r"scale=(\d+):(\d+)", filters).groups())
    image.resize((width, height)).save(command[-1].replace("%03d", "001"))
    pts = env.get("bad_pts", row["pts"])
    return b"", (
        "[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 0/0\n"
        f"[Parsed_showinfo_1 @ 0xabc] n: 0 pts: {pts} pts_time:{pts / 1000}\n"
    ).encode()


async def vision(env, image, options, directory, deadline):
    index, row = env["current"]
    env["ocr_calls"].append(index)
    if env.get("delay_index") == index:
        await asyncio.sleep(1)
    if hook := env.get("ocr_hook"):
        hook(index)
    if env.get("mutate_index") == index:
        env["source"].write_bytes(b"changed original while OCR observed its snapshot")
    if error := env["failures"].get(index):
        raise error
    with Image.open(image) as prepared:
        width, height = prepared.size
    texts = row["text"] if isinstance(row["text"], list) else [row["text"]]
    observations = [
        {
            "kind": "line",
            "text": text,
            "confidence": row["confidence"],
            "raw_box": [0.25, 0.25, 0.5, 0.5],
            "raw_points": [[0.25, 0.75], [0.75, 0.75], [0.75, 0.25], [0.25, 0.25]],
        }
        for text in texts
        if text
    ]
    payload = {
        "protocol": 1,
        "width": width,
        "height": height,
        "coordinate_space": "normalized_bottom_left",
        "observations": observations,
    }
    return json.dumps(payload).encode(), payload, {"engine": "vision", "qualification": "mocked"}


@pytest.fixture
def scene_fixture(tmp_path, monkeypatch, clean_config):
    """Use real snapshots, PNG encoding, geometry, manifests and bounded OCR parsing."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    env = {"source": tmp_path / "screen.mp4", "commands": [], "ocr_calls": [], "failures": {}}
    set_frames(env, ["error A", "error B", "error C"])
    monkeypatch.setattr(media_probe.shutil, "which", lambda name: "/mocked/" + name)
    monkeypatch.setattr(media_probe, "run_media_process", lambda *a: probe(env, *a))
    monkeypatch.setattr(media_frames, "run_media_process", lambda *a: decode(env, *a))
    monkeypatch.setattr(image_ocr, "run_vision", lambda *a: vision(env, *a))
    return env


def request(env, **updates):
    values = {
        "file_path": str(env["source"]),
        "expected_source_sha256": sha(env["source"].read_bytes()),
        "times_seconds": [0.1, 0.6],
        "engine": "vision",
        "crop": {"coordinates": [20, 10, 80, 40]},
        "resize": {"width": 160, "height": 80},
    }
    values.update(updates)
    return TemporalOCRRequest(**values)


def transcript_state(source, inferred, artifacts):
    """Keep original caption/model provenance separate from native observations."""
    provenance = dict(
        evidence="model_inference_or_measured_zero_pcm"
        if inferred
        else "caption_source_assertions",
        word_status="inferred_if_supplied" if inferred else "source_assertion_if_supplied",
        speaker_status="model_inferred_label_if_supplied"
        if inferred
        else "source_assertion_if_supplied",
        speech_accuracy_verified=False,
        word_alignment_verified=False,
        speaker_identity_verified=False,
    )
    cue = dict(
        id="fixture-cue",
        start_seconds=0.15,
        end_seconds=0.5,
        text="Look",
        speaker_id="speaker_0" if inferred else None,
        words=[dict(text="Look", start_seconds=0.15, end_seconds=0.5)],
    )
    return dict(
        operation="audio_transcribe",
        status="complete",
        outcome="inferred" if inferred else "captions",
        source=source,
        request_sha256="a" * 64,
        selection={"start_seconds": 0, "end_seconds": 2},
        captions=[],
        segments=[cue],
        untimed_text=[],
        windows=[],
        attempts=[],
        exports=[],
        artifacts=artifacts,
        provenance=provenance,
        warnings=[],
        execution={},
        receipt=None,
    )


def transcript_receipt(
    env, *, inferred=False, padding=0, caption=False, partial=False, empty=False
):
    """Create an authored preexisting receipt through the real exclusive artifact writer."""
    root = env["source"].parent / "transcript"
    root.mkdir()
    source = {
        "path": str(env["source"]),
        "sha256": sha(env["source"].read_bytes()),
        "bytes": env["source"].stat().st_size,
    }
    artifacts = (
        [write_artifact(root, "reference.txt", b"x" * padding, "authored_reference")]
        if padding
        else []
    )
    if empty:
        artifacts.append(write_artifact(root, "empty.txt", b"", "empty_text_export"))
    original = None
    if caption:
        path = root.parent / "original-caption.srt"
        path.write_text("1\n00:00:00,150 --> 00:00:00,500\nLook\n")
        original = dict(path=str(path), sha256=sha(path.read_bytes()), bytes=path.stat().st_size)
    result = transcript_state(source, inferred, artifacts)
    if original:
        result["captions"] = [dict(origin="uploaded", original=original)]
    if partial:
        result.update(status="partial", outcome="partial")
    record = write_artifact(
        root, "transcript-result.json", encoded(result), "complete_result_state"
    )
    receipt = {
        "schema_version": 1,
        "operation": result["operation"],
        "status": result["status"],
        "source": source,
        "request_sha256": result["request_sha256"],
        "caption_originals": [original] if original else [],
        "artifacts": [*artifacts, record],
    }
    commitment = write_artifact(
        root, "receipt.json", encoded(receipt), "externally_bound_restart_receipt"
    )
    return {
        "action": "readback",
        "file_path": str(env["source"]),
        "expected_source_sha256": source["sha256"],
        "output_directory": str(root),
        "expected_receipt_sha256": commitment["sha256"],
    }


async def test_mcp_schema_call_preserves_frames_numbers_and_speech(scene_fixture):
    set_frames(scene_fixture, ["9", "8"], confidence=None)
    speech = transcript_receipt(scene_fixture, inferred=True)
    arguments = {
        "request": request(scene_fixture, track_numbers=True, transcript=speech).model_dump(
            mode="json"
        )
    }
    async with Client(video_evidence_server) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["video_ocr_timeline"]
        assert tools[0].annotations.open_world_hint is False
        reply = await client.call_tool("video_ocr_timeline", arguments)
        value = reply.structured_content
        validate(value, tools[0].output_schema)
        assert json.loads(reply.content[0].text) == value
        assert value["status"] == "complete" and len(value["points"]) == 2
        assert value["numeric_candidates"][0]["actual_seconds"] == pytest.approx(0.8)
        assert value["numeric_candidates"][0]["uncertain"]
        assert value["speech"]["transcript"]["outcome"] == "inferred"
        assert value["limits"]["provider_calls"] == 0


async def test_mcp_unavailable_backend_returns_typed_retained_failure(scene_fixture):
    scene_fixture["failures"][0] = ImportError("Optional local OCR unavailable")
    async with Client(video_evidence_server) as client:
        tools = await client.list_tools()
        reply = await client.call_tool(
            "video_ocr_timeline", {"request": request(scene_fixture).model_dump(mode="json")}
        )
    value = reply.structured_content
    validate(value, tools[0].output_schema)
    assert value["status"] == "failed"
    assert value["points"][0]["error"]["category"] == "DEPENDENCY_MISSING"
    assert value["points"][1]["reason"] == "backend_unavailable"
    assert scene_fixture["ocr_calls"] == [0]


@pytest.mark.parametrize(
    "update",
    [
        {"times_seconds": [True]},
        {"unknown_option": True},
        {
            "transcript": {
                "action": "transcribe",
                "file_path": "/unused",
                "expected_source_sha256": "a" * 64,
                "output_directory": "/unused-output",
                "backend": "gemini",
                "authorize_submission": True,
            }
        },
    ],
)
async def test_mcp_invalid_input_refuses_before_native_or_speech(scene_fixture, update):
    arguments = request(scene_fixture).model_dump(mode="json") | update
    async with Client(video_evidence_server) as client:
        reply = await client.call_tool(
            "video_ocr_timeline", {"request": arguments}, raise_on_error=False
        )
    assert reply.is_error and scene_fixture["commands"] == []
