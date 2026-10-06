"""SOURCE_ONLY variants over canonical dummy plans/jobs; all native calls mocked."""

import hashlib
import json
from pathlib import Path
import struct
import re
import asyncio

import pytest

from tests.test_storyboard_timing import project as project  # noqa: F401
from video_explainer_mcp import variants as implementation
from video_explainer_mcp import variants_render as renderer
from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.models.timing import TimingRequest
from video_explainer_mcp.models.variants import VariantRequest
from video_explainer_mcp.planning import plan_transaction
from video_explainer_mcp.planning_sources import digest
from video_explainer_mcp.render_storyboard_sources import file_pin
from video_explainer_mcp.storyboard_timing import manage_timing
from video_explainer_mcp.tools.variants import explainer_variants
from video_explainer_mcp.variants_captions import caption_layout, font_metrics, source_cues, srt_text


def pin(path, project):
    return {"path": str(path.relative_to(project)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def dummy_font():
    """Tiny authored table fixture, not a usable or qualified native font asset."""
    head, hhea, maxp = bytearray(54), bytearray(36), bytearray(6)
    struct.pack_into(">H", head, 18, 1000)
    struct.pack_into(">hhhh", head, 36, -20, -200, 1000, 800)
    struct.pack_into(">H", hhea, 10, 600)
    struct.pack_into(">H", hhea, 34, 1)
    struct.pack_into(">H", maxp, 4, 128)
    table = struct.pack(">7H", 4, 32, 0, 4, 4, 1, 0) + struct.pack(">9H", 126, 65535, 0, 32, 65535, 0, 1, 0, 0)
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + table
    tables = {b"head": head, b"hhea": hhea, b"maxp": maxp, b"cmap": cmap, b"glyf": b"dummy", b"hmtx": struct.pack(">HH", 600, 0) + b"\x00" * 254}
    offset = 12 + 16 * len(tables)
    directory, body = bytearray(), bytearray()
    for name, data in tables.items():
        directory.extend(struct.pack(">4sIII", name, 0, offset, len(data)))
        body.extend(data)
        offset += len(data)
    return struct.pack(">IHHHH", 65536, len(tables), 0, 0, 0) + directory + body


@pytest.fixture
def prepared(project):
    """GIVEN actual approved source bindings and a byte-attested dummy completed job."""
    manage_timing(project.name, TimingRequest(action="repair", expected_revision=0))
    source = project / "source.mp4"
    source.write_bytes(b"unit-dummy-not-real-media")
    font = project / "font.ttf"
    font.write_bytes(dummy_font())
    with plan_transaction(project) as (_, state):
        files = {b["path"]: file_pin(project / b["path"], 1024 * 1024) for b in state["bindings"].values()}
        files[".timing/manifest.json"] = file_pin(project / ".timing/manifest.json", 1024 * 1024)
    source_revision = digest(files)
    qualification = {"policy": "mp4-full-decode-v1", "full_decode": True, "artifact_sha256": pin(source, project)["sha256"],
                     "size_bytes": source.stat().st_size, "authored_storyboard": {"frames": 31}}
    artifact = {"path": str(source), **file_pin(source, 1024), "qualification": qualification}
    store = JobStore()
    row = store.create("render", {"project_dir": str(project), "source": {"files": files, "sha256": source_revision},
                                 "renderer": {"route": "authored_storyboard"}}, source_revision)
    store.claim(row["job_id"], "unit-owner")
    store.checkpoint(row["job_id"], "unit-owner", status="completed", result={"output": artifact},
                     artifact_hashes={str(source): artifact["sha256"]}, release=True)
    return {"source_job_id": row["job_id"], "source_video": pin(source, project), "scene_ids": ["0", "1", "2"], "font": pin(font, project)}


@pytest.fixture
def codec(monkeypatch, tmp_path):
    """Mock only the external codec boundary; run real snapshot/manifest/publication code."""
    calls = []
    monkeypatch.setattr(implementation.tempfile, "tempdir", str(tmp_path))
    binaries = {"ffmpeg": {"path": "/mock/ffmpeg", "sha256": "a" * 64}, "ffprobe": {"path": "/mock/ffprobe", "sha256": "b" * 64}}
    monkeypatch.setattr(implementation, "codec_executables", lambda: binaries)

    async def process(command, timeout, cwd=None):
        calls.append(command)
        assert timeout <= 20
        if command[-1].startswith("variant-"):
            graph = command[command.index("-filter_complex") + 1]
            start, end = map(int, re.search(r"trim=start_frame=(\d+):end_frame=(\d+)", graph).groups())
            value = {"aspect": command[-1].removeprefix("variant-").removesuffix(".mp4").replace("-", ":"),
                     "frames": end - start, "duration": float(command[command.index("-t") + 1])}
            Path(cwd, command[-1]).write_bytes(json.dumps(value).encode())
        elif command[0].endswith("ffprobe"):
            saved = json.loads(Path(command[-1]).read_bytes())
            aspect = saved["aspect"]
            width, height = renderer.DIMENSIONS[aspect]
            value = {"format": {"duration": saved["duration"]}, "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": width, "height": height, "nb_read_frames": str(saved["frames"]), "r_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2, "duration": saved["duration"]}]}
            return json.dumps(value).encode(), b""
        return b"", b""

    monkeypatch.setattr(implementation, "run_media_process", process)
    monkeypatch.setattr(renderer, "run_media_process", process)
    return calls, process


async def test_public_batch_dimensions_bounds_claims_hashes_restart(project, prepared, codec):
    """WHEN three aspects render, THEN exact selected facts/order and distinct hashes survive."""
    result = await explainer_variants(project.name, prepared)
    assert result["status"] == "complete" and len(result["outcomes"]) == 3
    assert len({o["configuration_sha256"] for o in result["outcomes"]}) == 3
    assert len({o["output_sha256"] for o in result["outcomes"]}) == 3
    source = result["configuration"]["source"]
    assert source["scene_ids"] == ["0", "1", "2"]
    assert [c["claim_ids"] for c in source["claims"]] == [["0"], ["1"], ["2"]]
    assert all(c["claims"][0]["support"][0]["revision"] == "r1" for c in source["claims"])
    for outcome in result["outcomes"]:
        proof, bounds = outcome["qualification"], outcome["caption_bounds"]
        assert (proof["width"], proof["height"]) == renderer.DIMENSIONS[outcome["aspect"]]
        assert bounds["max_width"] <= proof["width"] - 2 * bounds["margin"]
        assert bounds["max_height"] <= proof["height"] / 4
        assert proof["full_decode"] and not proof["caption_pixels_verified"]
        graph = outcome["command"][outcome["command"].index("-filter_complex") + 1]
        assert "force_original_aspect_ratio=decrease" in graph and "crop=" not in graph
        assert "trim=start_frame=0:end_frame=31" in graph and "expansion=none" in graph
        assert pin(project / outcome["path"], project)["sha256"] == outcome["output_sha256"]
    renders = sum(c[-1].startswith("variant-") for c in codec[0])
    again = await explainer_variants(project.name, prepared)
    assert again["cached"] and sum(c[-1].startswith("variant-") for c in codec[0]) == renders


async def test_srt_exact_current_source_and_stale_refusal(project, prepared, codec):
    request = VariantRequest.model_validate(prepared)
    with plan_transaction(project) as (_, state):
        context = implementation.current(project, state, request)
    source = project / "captions.srt"
    source.write_text(srt_text(context["cues"]))
    prepared.update(captions="srt", srt=pin(source, project))
    assert (await explainer_variants(project.name, prepared))["status"] == "complete"
    source.write_text(source.read_text().replace("One.", "Unsupported."))
    prepared["srt"] = pin(source, project)
    before = len(codec[0])
    assert "error" in await explainer_variants(project.name, prepared)
    assert len(codec[0]) == before


@pytest.mark.parametrize("ids", [["1", "0"], ["0", "2"], ["0", "0"]])
async def test_reorder_omission_duplicates_refused_before_native(project, prepared, codec, ids):
    prepared["scene_ids"] = ids
    assert "error" in await explainer_variants(project.name, prepared)
    assert not codec[0]


async def test_missing_stale_audio_font_and_source_refuse(project, prepared, codec):
    (project / "fixture/narration.wav").write_bytes(b"changed")
    assert "error" in await explainer_variants(project.name, prepared)
    assert not codec[0]


async def test_missing_font_backend_retains_planned_denominator(project, prepared, codec, monkeypatch):
    async def absent(*args, **kwargs):
        raise RuntimeError("drawtext unavailable")
    monkeypatch.setattr(renderer, "run_media_process", absent)
    result = await explainer_variants(project.name, prepared)
    assert "error" in result and not codec[0]
    batches = json.loads((project / implementation.MANIFEST).read_text())["batches"]
    assert [o["status"] for o in next(iter(batches.values()))["outcomes"]] == ["unrun"] * 3


async def test_one_variant_failure_is_retained_without_automatic_retry(project, prepared, codec, monkeypatch):
    async def fail(command, timeout, cwd=None):
        if command[-1] == "variant-9-16.mp4":
            raise RuntimeError("controlled portrait failure")
        return await codec[1](command, timeout, cwd)
    monkeypatch.setattr(implementation, "run_media_process", fail)
    result = await explainer_variants(project.name, prepared)
    assert result["status"] == "partial"
    assert [o["status"] for o in result["outcomes"]] == ["success", "error", "success"]
    assert "controlled portrait failure" in result["outcomes"][1]["error"]
    again = await explainer_variants(project.name, prepared)
    assert again["cached"] and again["outcomes"][1]["status"] == "error"


def test_font_glyph_and_readable_bounds_refusal(project, prepared):
    from video_explainer_mcp.models.materials import PinnedFile
    metrics = font_metrics(project, PinnedFile.model_validate(prepared["font"]))
    assert caption_layout([{"text": "One."}], metrics, 720, 720)["font_size"] >= 12
    metrics["advance"] = 1500
    with pytest.raises(ValueError):
        caption_layout([{"text": "A" * 64}], metrics, 720, 720)
    metrics["glyphs"] = 10
    with pytest.raises(ValueError):
        caption_layout([{"text": "One."}], metrics, 720, 720)


def test_missing_alignment_and_nonmonotonic_srt_never_fabricate():
    with pytest.raises(ValueError, match="Missing"):
        source_cues({"words": None}, {"sample_rate": 24000, "total_samples": 24000}, [{"start_sample": 0, "end_sample": 24000}])
    with pytest.raises(ValueError, match="monotonic"):
        srt_text([{"text": "a", "start_sample": 0, "end_sample": 100, "sample_rate": 1000},
                  {"text": "b", "start_sample": 50, "end_sample": 150, "sample_rate": 1000}])


async def test_short_keeps_one_complete_scene_and_its_source_clock(project, prepared, codec):
    prepared.update(scene_ids=["1"], aspects=["9:16"])
    result = await explainer_variants(project.name, prepared)
    assert result["status"] == "complete"
    context = result["configuration"]["source"]
    assert (context["start_frame"], context["end_frame"]) == (11, 18)
    assert (context["start_sample"], context["end_sample"]) == (8400, 14400)
    assert abs(context["source_clock_offset_seconds"]) <= 1 / 30
    assert context["claims"][0]["claim_ids"] == ["1"] and context["cues"][0]["text"] == "Two."


@pytest.mark.parametrize("changed", ["font", "video", "timing", "font_symlink"])
async def test_source_font_and_timing_refusals_precede_work(project, prepared, codec, changed):
    if changed == "font":
        (project / "font.ttf").write_bytes(b"unsupported-font")
        prepared["font"] = pin(project / "font.ttf", project)
    elif changed == "video":
        (project / "source.mp4").write_bytes(b"changed")
    elif changed == "timing":
        (project / ".timing/manifest.json").unlink()
    else:
        (project / "font.ttf").rename(project / "original.ttf")
        (project / "font.ttf").symlink_to(project / "original.ttf")
    assert "error" in await explainer_variants(project.name, prepared)
    assert not codec[0]


async def test_input_change_stops_later_work_preserving_first_error(project, prepared, codec, monkeypatch):
    async def change(command, timeout, cwd=None):
        result = await codec[1](command, timeout, cwd)
        if command[-1].startswith("variant-"):
            (project / "source.mp4").write_bytes(b"changed source")
        return result
    monkeypatch.setattr(implementation, "run_media_process", change)
    assert "error" in await explainer_variants(project.name, prepared)
    batch = next(iter(json.loads((project / implementation.MANIFEST).read_text())["batches"].values()))
    assert [o["status"] for o in batch["outcomes"]] == ["error", "unrun", "unrun"]
    assert sum(c[-1].startswith("variant-") for c in codec[0]) == 1
    assert not list(project.glob("variant-*.mp4"))


async def test_atomic_success_receipt_failure_removes_only_new_outputs(project, prepared, codec, monkeypatch):
    original = implementation.atomic_write
    def fail(path, data):
        if '"status":"success"' in data:
            raise OSError("controlled atomic receipt failure")
        original(path, data)
    monkeypatch.setattr(implementation, "atomic_write", fail)
    result = await explainer_variants(project.name, prepared)
    assert result["status"] == "partial"
    assert all(o["status"] == "error" and "controlled atomic receipt failure" in o["error"] for o in result["outcomes"])
    assert not list(project.glob("variant-*.mp4"))


@pytest.mark.parametrize("fault", ["width", "audio_duration"])
async def test_qualification_mismatch_cannot_publish(project, prepared, codec, monkeypatch, fault):
    async def wrong(command, timeout, cwd=None):
        stdout, stderr = await codec[1](command, timeout, cwd)
        if command[0].endswith("ffprobe"):
            value = json.loads(stdout)
            if fault == "width":
                value["streams"][0]["width"] += 1
            else:
                value["streams"][1]["duration"] += 0.1
            return json.dumps(value).encode(), stderr
        return stdout, stderr
    monkeypatch.setattr(renderer, "run_media_process", wrong)
    result = await explainer_variants(project.name, prepared)
    assert result["status"] == "partial" and all(o["status"] == "error" for o in result["outcomes"])
    assert not list(project.glob("variant-*.mp4"))


async def test_cancellation_retains_pending_denominator_no_resend(project, prepared, codec, monkeypatch):
    async def cancel(command, timeout, cwd=None):
        if command[-1].startswith("variant-"):
            raise asyncio.CancelledError
        return await codec[1](command, timeout, cwd)
    monkeypatch.setattr(implementation, "run_media_process", cancel)
    with pytest.raises(asyncio.CancelledError):
        await explainer_variants(project.name, prepared)
    result = await explainer_variants(project.name, prepared)
    assert result["cached"] and [o["status"] for o in result["outcomes"]] == ["pending", "unrun", "unrun"]


async def test_cached_denominator_tampering_fails_closed(project, prepared, codec):
    await explainer_variants(project.name, prepared)
    path = project / implementation.MANIFEST
    manifest = json.loads(path.read_text())
    next(iter(manifest["batches"].values()))["outcomes"].pop()
    path.write_text(json.dumps(manifest))
    before = len(codec[0])
    assert "error" in await explainer_variants(project.name, prepared)
    assert len(codec[0]) == before


@pytest.mark.parametrize("batch_status,row_status", [
    ("complete", "pending"), ("complete", "error"), ("complete", "unrun"),
    ("complete", "invented"), ("partial", "success"), ("pending", "success"),
    ("invented", "success"),
])
async def test_cached_batch_status_matches_exact_population(project, prepared, codec, batch_status, row_status):
    """GIVEN tampered terminal metadata, THEN cache refuses before any decoder call."""
    await explainer_variants(project.name, prepared)
    path = project / implementation.MANIFEST
    manifest = json.loads(path.read_text())
    batch = next(iter(manifest["batches"].values()))
    batch["status"] = batch_status
    batch["outcomes"][0]["status"] = row_status
    path.write_text(json.dumps(manifest))
    before = len(codec[0])
    result = await explainer_variants(project.name, prepared)
    assert "error" in result
    assert len(codec[0]) == before
    assert json.loads(path.read_text()) == manifest


@pytest.mark.parametrize("field,value", [
    ("factual_success", True), ("factual_success", 0),
    ("visual_semantics", "verified"), ("captions_srt", "invented caption"),
    ("batch_sha256", "0" * 64),
])
async def test_cached_fixed_metadata_is_source_bound(project, prepared, codec, field, value):
    await explainer_variants(project.name, prepared)
    path = project / implementation.MANIFEST
    manifest = json.loads(path.read_text())
    next(iter(manifest["batches"].values()))[field] = value
    path.write_text(json.dumps(manifest))
    before = len(codec[0])
    assert "error" in await explainer_variants(project.name, prepared)
    assert len(codec[0]) == before
    assert json.loads(path.read_text()) == manifest


@pytest.mark.parametrize("stage", ["failure", "final"])
async def test_failed_checkpoint_keeps_primary_and_actual_durable_rows(project, prepared, codec, monkeypatch, stage):
    """GIVEN primary codec failure plus failed save, THEN neither the cause nor disk state is invented."""
    primary = RuntimeError("controlled primary variant failure")
    original = implementation.atomic_write

    async def fail(command, timeout, cwd=None):
        if command[-1].startswith("variant-"):
            raise primary
        return await codec[1](command, timeout, cwd)

    def persist(path, data):
        marker = '"status":"error"' if stage == "failure" else '"status":"partial"'
        if marker in data:
            raise OSError("controlled secondary checkpoint failure")
        original(path, data)

    monkeypatch.setattr(implementation, "run_media_process", fail)
    monkeypatch.setattr(implementation, "atomic_write", persist)
    with pytest.raises(RuntimeError, match="controlled primary") as caught:
        await implementation.create_variants(project.name, VariantRequest.model_validate(prepared))
    assert caught.value is primary
    assert any("persistence" in note and "OSError" in note for note in primary.__notes__)
    batch = next(iter(json.loads((project / implementation.MANIFEST).read_text())["batches"].values()))
    assert batch["status"] == "pending"
    expected = ["pending", "unrun", "unrun"] if stage == "failure" else ["error"] * 3
    assert [row["status"] for row in batch["outcomes"]] == expected
    assert not list(project.glob("variant-*.mp4"))


async def test_temporary_cleanup_cannot_replace_cancellation(project, prepared, codec, monkeypatch):
    """GIVEN cancellation and failing cleanup, THEN exact cancellation and a cleanup note survive."""
    primary = asyncio.CancelledError("controlled cancellation")
    original = implementation.tempfile.TemporaryDirectory

    class FailingTemporaryDirectory(original):
        def cleanup(self):
            super().cleanup()
            raise OSError("controlled temporary cleanup failure")

    async def cancel(command, timeout, cwd=None):
        if command[-1].startswith("variant-"):
            raise primary
        return await codec[1](command, timeout, cwd)

    monkeypatch.setattr(implementation.tempfile, "TemporaryDirectory", FailingTemporaryDirectory)
    monkeypatch.setattr(implementation, "run_media_process", cancel)
    with pytest.raises(asyncio.CancelledError) as caught:
        await implementation.create_variants(project.name, VariantRequest.model_validate(prepared))
    assert caught.value is primary
    assert any("cleanup" in note and "OSError" in note for note in primary.__notes__)
    batch = next(iter(json.loads((project / implementation.MANIFEST).read_text())["batches"].values()))
    assert [row["status"] for row in batch["outcomes"]] == ["pending", "unrun", "unrun"]


@pytest.mark.parametrize("changed", ["video", "audio", "timing", "script", "font", "srt", "codec"])
async def test_cached_qualification_final_rechecks_all_bound_inputs(project, prepared, codec, monkeypatch, changed):
    """GIVEN mutation during awaited cached decode, THEN no stale cached success escapes."""
    if changed == "srt":
        request = VariantRequest.model_validate(prepared)
        with plan_transaction(project) as (_, state):
            context = implementation.current(project, state, request)
        path = project / "captions.srt"
        path.write_text(srt_text(context["cues"]))
        prepared.update(captions="srt", srt=pin(path, project))
    await explainer_variants(project.name, prepared)
    before = (project / implementation.MANIFEST).read_bytes()
    mutated = False

    async def change(command, timeout, cwd=None):
        nonlocal mutated
        result = await codec[1](command, timeout, cwd)
        if not mutated and command[0].endswith("ffprobe"):
            mutated = True
            paths = {"video": "source.mp4", "audio": "fixture/narration.wav",
                     "timing": ".timing/manifest.json", "script": "script/script.json",
                     "font": "font.ttf", "srt": "captions.srt"}
            if changed == "codec":
                monkeypatch.setattr(implementation, "codec_executables", lambda: {
                    "ffmpeg": {"path": "/mock/changed", "sha256": "c" * 64}})
            else:
                (project / paths[changed]).write_bytes(b"changed during cached decode")
        return result

    monkeypatch.setattr(renderer, "run_media_process", change)
    result = await explainer_variants(project.name, prepared)
    assert mutated and "error" in result
    assert (project / implementation.MANIFEST).read_bytes() == before
