"""Synthetic local controller controls; PDF/native/provider boundaries are mocked."""

import asyncio
import json
import os
import struct
import threading
import time
import zlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_research_mcp.config import get_config
from video_research_mcp.models.video_note import VideoNoteRequest
from video_research_mcp.video_note import create_note
from video_research_mcp.video_note import frames, pipeline
from video_research_mcp.video_note.io import canonical, digest, png_shape, write_bytes


def png(width=16, height=10, color=(255, 0, 0)):
    """Author a tiny synthetic RGB PNG independently with stdlib, no media decoder."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    pixels = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


@pytest.fixture
def note_request(tmp_path, clean_config):
    get_config()  # Shared configured runtime is initialized before dry-run snapshots.
    workspace = tmp_path / "authoring"
    workspace.mkdir()
    source = workspace / "source.mp4"
    source.write_bytes(b"synthetic mocked local video; no native decoding")
    return VideoNoteRequest(file_path=str(source), expected_source_sha256=digest(source.read_bytes()),
        title="Red phase tutorial", output_path=str(workspace / "tutorial.pdf"),
        steps=[{"title": "Inspect red", "instruction": "Inspect the retained red phase.",
                "start_seconds": 0.4, "end_seconds": 0.6}])


@pytest.fixture
def native_edges(note_request, tmp_path, monkeypatch):
    """Only extraction and PDF dependency/render boundaries are simulated."""
    fixture = tmp_path / "native-fixture.png"
    fixture.write_bytes(png())
    calls = []
    async def extract(path, **kwargs):
        calls.append((path, kwargs))
        return {"source": {"sha256": note_request.expected_source_sha256, "duration_seconds": 3},
                "frames": [{"path": str(fixture), "sha256": digest(fixture.read_bytes()),
                            "bytes": len(fixture.read_bytes()), "width": 16, "height": 10,
                            "actual_seconds": 0.5, "original_pts": 5120, "time_base": "1/10240"}]}
    def pdf_edge(document, records, buffers, directory, cancelled, deadline):
        from video_research_mcp.image_preprocessing import check_worker
        check_worker(cancelled, deadline)
        pdf = write_bytes(directory / "document.pdf", b"%PDF-synthetic-controlled-native-edge")
        page = write_bytes(directory / "page-01.png", png(20, 20))
        layout = write_bytes(directory / "layout.json", canonical({"schema_version": 1, "images": []}))
        return pdf, [{**page, "width": 20, "height": 20}], layout
    monkeypatch.setattr(frames, "frame_at", extract)
    monkeypatch.setattr(pipeline, "dependencies_ready", lambda: {"fpdf2": "mocked", "pypdfium2": "mocked"})
    monkeypatch.setattr(pipeline, "render_verified", pdf_edge)
    return fixture, calls, pdf_edge


async def test_dry_run_no_writes_native_provider_or_env_mutation(note_request, monkeypatch):
    before_env = dict(os.environ)
    before_files = {path: path.read_bytes() for path in Path(note_request.file_path).parent.iterdir()}
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run side effect")
    monkeypatch.setattr(os, "mkdir", forbidden)
    monkeypatch.setattr(os, "replace", forbidden)
    monkeypatch.setattr(pipeline, "dependencies_ready", forbidden)
    monkeypatch.setattr(frames, "frame_at", forbidden)
    real_open = os.open
    def readonly(path, flags, *args, **kwargs):
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", readonly)
    result = await create_note(note_request)
    assert result["status"] == "dry_run", result
    assert result["source"]["sha256"] == note_request.expected_source_sha256
    assert result["supplied_steps"][0]["instruction"] == note_request.steps[0].instruction
    assert result["verification"]["source_extent"] == "unverified"
    assert result["verification"]["all_pages_rasterized"] == "unperformed"
    assert result["artifact_directory"] is None
    assert dict(os.environ) == before_env
    assert {path: path.read_bytes() for path in Path(note_request.file_path).parent.iterdir()} == before_files


async def test_dry_run_defers_explicit_perception(note_request, monkeypatch):
    import video_research_mcp.media_perception as perception
    def forbidden(*args, **kwargs):
        raise AssertionError("perception invoked by dry run")
    monkeypatch.setattr(perception, "perceive_media", forbidden)
    value = note_request.model_dump()
    value["perception"] = {"file_path": note_request.file_path, "expected_source_sha256": note_request.expected_source_sha256,
                           "instruction": "Inspect source", "dry_run": False, "authorize_submission": True}
    result = await create_note(value)
    assert result["status"] == "dry_run" and result["perception"]["status"] == "deferred"


@pytest.mark.parametrize("change", ["reverse", "nan", "infinite", "bool", "overlap", "17steps", "glyph", "unknown"])
def test_typed_plan_refusals(note_request, change):
    value = note_request.model_dump()
    if change == "reverse":
        value["steps"][0]["end_seconds"] = 0.2
    elif change == "nan":
        value["steps"][0]["start_seconds"] = float("nan")
    elif change == "infinite":
        value["steps"][0]["end_seconds"] = float("inf")
    elif change == "bool":
        value["steps"][0]["start_seconds"] = True
    elif change == "overlap":
        value["steps"].append(dict(value["steps"][0]))
    elif change == "17steps":
        value["steps"] = [{**value["steps"][0], "start_seconds": i, "end_seconds": i + .5} for i in range(17)]
    elif change == "glyph":
        value["title"] = "Unsupported 漢字"
    else:
        value["model_name"] = "unrequested"
    with pytest.raises(ValidationError):
        VideoNoteRequest.model_validate(value)


@pytest.mark.parametrize("kind", ["url", "symlink-source", "symlink-output", "same", "hardlink", "parent", "extension", "existing", "outside-fence", "fifo"])
async def test_path_refusal_before_any_mutation(note_request, tmp_path, monkeypatch, kind):
    value = note_request.model_dump()
    output = Path(note_request.output_path)
    if kind == "url":
        value["file_path"] = "https://example.invalid/source.mp4"
    elif kind == "symlink-source":
        alias = tmp_path / "alias.mp4"
        alias.symlink_to(note_request.file_path)
        value["file_path"] = str(alias)
    elif kind == "symlink-output":
        output.symlink_to(note_request.file_path)
    elif kind == "same":
        value["output_path"] = note_request.file_path
    elif kind == "hardlink":
        os.link(note_request.file_path, output)
        value["overwrite"] = True
    elif kind == "parent":
        value["output_path"] = str(tmp_path / "missing" / "out.pdf")
    elif kind == "extension":
        value["output_path"] = str(tmp_path / "out.txt")
    elif kind == "existing":
        output.write_bytes(b"old PDF")
    elif kind == "outside-fence":
        get_config().local_file_access_root = str(tmp_path / "allowed")
    else:
        fifo = tmp_path / "fifo.mp4"
        os.mkfifo(fifo)
        value["file_path"] = str(fifo)
    before = set(tmp_path.iterdir())
    monkeypatch.setattr(pipeline, "dependencies_ready", lambda: pytest.fail("native readiness reached"))
    result = await create_note(value)
    assert "error" in result and set(tmp_path.iterdir()) == before


async def test_missing_dependencies_actionable_and_no_artifacts(note_request, tmp_path, monkeypatch):
    value = note_request.model_dump()
    value["dry_run"] = False
    def missing():
        raise ImportError("untrusted native detail SECRET-do-not-return")
    monkeypatch.setattr(pipeline, "dependencies_ready", missing)
    result = await create_note(value)
    assert result["category"] == "DEPENDENCY_MISSING"
    assert "[tutorial]" in result["error"] and "SECRET" not in str(result)
    assert set(Path(note_request.file_path).parent.iterdir()) == {Path(note_request.file_path)}


async def test_atomic_success_retains_exact_lineage_and_original(note_request, native_edges):
    fixture, calls, _ = native_edges
    source_before = Path(note_request.file_path).read_bytes()
    result = await create_note({**note_request.model_dump(), "dry_run": False})
    assert result["status"] == "complete", result
    assert calls[0] == (note_request.file_path, {"time_seconds": .5, "max_pixels": 250000,
                       "selection": "precise", "expected_source_sha256": note_request.expected_source_sha256})
    directory = Path(result["artifact_directory"])
    assert directory.is_dir() and directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "frame-01.png").read_bytes() == fixture.read_bytes()
    assert digest(Path(result["output_path"]).read_bytes()) == result["pdf"]["sha256"]
    manifest = json.loads(Path(result["manifest"]["path"]).read_text())
    assert manifest["coverage"] == {"sampled_points": [.5], "watched_intervals": []}
    assert manifest["frames"][0]["original_pts"] == 5120
    assert manifest["supplied_steps"][0]["instruction"] == note_request.steps[0].instruction
    receipt = json.loads(Path(result["receipt"]["path"]).read_text())
    for record in [receipt["manifest"], receipt["layout"], *receipt["pages"], *receipt["frames"]]:
        assert digest(Path(record["path"]).read_bytes()) == record["sha256"]
    assert Path(note_request.file_path).read_bytes() == source_before
    assert result["provenance"]["human_review"] == "pending"
    assert result["provenance"]["final_model_review"] == "unperformed"
    assert result["provenance"]["factual_correctness_verified"] is False


@pytest.mark.parametrize("failure", ["missing", "outside-point", "tampered-identity"])
async def test_image_misses_preserve_readable_text(note_request, native_edges, monkeypatch, failure):
    fixture, _, _ = native_edges
    real = frames.frame_at
    async def missing(*args, **kwargs):
        if failure == "missing":
            raise RuntimeError("raw native password=do-not-leak")
        value = await real(*args, **kwargs)
        if failure == "outside-point":
            value["frames"][0]["actual_seconds"] = .8
        else:
            value["frames"][0]["sha256"] = "0" * 64
        return value
    monkeypatch.setattr(frames, "frame_at", missing)
    result = await create_note({**note_request.model_dump(), "dry_run": False})
    assert result["status"] == "complete", result
    assert result["steps"][0]["instruction"] == note_request.steps[0].instruction
    assert result["frames"] == [] and any("illustration unavailable" in warning for warning in result["warnings"])
    assert "do-not-leak" not in str(result)
    assert fixture.exists()


async def test_observed_extent_refuses_bad_interval(note_request, native_edges, tmp_path):
    value = note_request.model_dump()
    value.update(dry_run=False, steps=[{**value["steps"][0], "start_seconds": 2.5, "end_seconds": 3.5}])
    result = await create_note(value)
    assert "error" in result and "extent" in result["error"]
    assert not Path(note_request.output_path).exists()
    assert not list(Path(note_request.output_path).parent.glob("tutorial-note-*"))


@pytest.mark.parametrize("change", ["source-before", "source-late", "frame-late", "buffer-late", "pdf-late", "output-race", "render-failure"])
async def test_failures_preserve_existing_pdf_and_remove_owned_staging(note_request, native_edges, tmp_path, monkeypatch, change):
    _, _, original = native_edges
    output = Path(note_request.output_path)
    output.write_bytes(b"protected old PDF")
    def controlled(document, records, buffers, directory, cancelled, deadline):
        if change == "render-failure":
            raise RuntimeError("native token=not-to-disclose")
        result = original(document, records, buffers, directory, cancelled, deadline)
        if change == "source-late":
            Path(note_request.file_path).write_bytes(b"changed during render")
        elif change == "frame-late":
            Path(records[0]["path"]).write_bytes(png(color=(0, 255, 0)))
        elif change == "buffer-late":
            buffers[0] = png(color=(0, 255, 0))
        elif change == "pdf-late":
            Path(result[0]["path"]).write_bytes(b"changed PDF")
        elif change == "output-race":
            output.write_bytes(b"concurrent destination writer")
        return result
    monkeypatch.setattr(pipeline, "render_verified", controlled)
    if change == "source-before":
        Path(note_request.file_path).write_bytes(b"changed before operation")
    result = await create_note({**note_request.model_dump(), "dry_run": False, "overwrite": True})
    assert "error" in result and "not-to-disclose" not in str(result)
    assert output.read_bytes() == (b"concurrent destination writer" if change == "output-race" else b"protected old PDF")
    assert not list(Path(note_request.output_path).parent.glob("tutorial-note-*"))


async def test_new_output_race_is_not_overwritten(note_request, native_edges, monkeypatch):
    _, _, original = native_edges
    def controlled(*args):
        result = original(*args)
        Path(note_request.output_path).write_bytes(b"new concurrent output")
        return result
    monkeypatch.setattr(pipeline, "render_verified", controlled)
    result = await create_note({**note_request.model_dump(), "dry_run": False})
    assert "error" in result and Path(note_request.output_path).read_bytes() == b"new concurrent output"


async def test_cancel_joins_renderer_before_removing_staging(note_request, native_edges, tmp_path, monkeypatch):
    started, joined, stage_exists = threading.Event(), threading.Event(), []
    def cooperative(document, records, buffers, directory, cancelled, deadline):
        started.set()
        while not cancelled.wait(.01):
            if time.monotonic() > deadline:
                break
        stage_exists.append(directory.exists())
        joined.set()
        raise TimeoutError("controlled cancellation")
    monkeypatch.setattr(pipeline, "render_verified", cooperative)
    task = asyncio.create_task(create_note({**note_request.model_dump(), "dry_run": False}))
    assert await asyncio.to_thread(started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert joined.is_set() and stage_exists == [True]
    assert not Path(note_request.output_path).exists() and not list(Path(note_request.output_path).parent.glob("tutorial-note-*"))


async def test_one_deadline_stops_before_pdf_publication(note_request, native_edges, monkeypatch):
    get_config().media_acquire_timeout_seconds = .02
    async def slow(*args, **kwargs):
        await asyncio.sleep(.08)
        raise AssertionError("late extraction")
    monkeypatch.setattr(frames, "frame_at", slow)
    result = await create_note({**note_request.model_dump(), "dry_run": False})
    assert "error" in result and result["retryable"] is False
    assert not Path(note_request.output_path).exists()


def perception_request(note_request):
    return {"file_path": note_request.file_path, "expected_source_sha256": note_request.expected_source_sha256,
            "instruction": "Describe phases", "dry_run": False, "authorize_submission": True}


async def test_model_failure_retains_complete_population_and_supplied_text(note_request, native_edges, monkeypatch):
    import video_research_mcp.media_perception as perception
    async def failing(_):
        return {"error": "raw password=not-to-return", "source": {"sha256": note_request.expected_source_sha256},
            "windows": [{"index": 0, "start_seconds": 0, "end_seconds": 1, "status": "complete"},
                        {"index": 1, "start_seconds": 1, "end_seconds": 2, "status": "failed"},
                        {"index": 2, "start_seconds": 2, "end_seconds": 3, "status": "planned"}],
            "timeline": [], "abstentions": [{"window_index": 0, "reason": "raw secret"}],
            "execution": {"prepared_windows": 3, "completed_windows": 1, "attempts": [{}, {}]}}
    monkeypatch.setattr(perception, "perceive_media", failing)
    result = await create_note({**note_request.model_dump(), "dry_run": False, "perception": perception_request(note_request)})
    assert result["status"] == "complete", result
    assert result["steps"][0]["origin"] == "caller_proposal"
    report = result["perception"]
    assert len(report["windows"]) == 3 and len(report["abstentions"]) == 1
    assert report["counts"]["failed_windows"] == 1 and report["counts"]["unobserved_windows"] == 2
    assert report["counts"]["attempts"] == 2
    assert "not-to-return" not in str(result) and "raw secret" not in str(result)


@pytest.mark.parametrize("kind", ["valid", "wrong-source", "overlap", "unsupported-glyph", "17events"])
async def test_only_admitted_timeline_can_become_inferred_steps(note_request, native_edges, monkeypatch, kind):
    import video_research_mcp.media_perception as perception
    event = {"modality": "visible", "start_seconds": .4, "end_seconds": .6,
             "description": "Observe the red phase.", "frame_indices": [0], "window_index": 0}
    events = [event]
    if kind == "overlap":
        events.append(dict(event))
    elif kind == "unsupported-glyph":
        event["description"] = "Unsupported 漢字"
    elif kind == "17events":
        events = [{**event, "start_seconds": i / 20, "end_seconds": (i + .5) / 20} for i in range(17)]
    async def inferred(_):
        return {"status": "complete", "source": {"sha256": "0" * 64 if kind == "wrong-source" else note_request.expected_source_sha256,
                    "duration_seconds": 3}, "windows": [], "timeline": events, "abstentions": [], "execution": {}}
    monkeypatch.setattr(perception, "perceive_media", inferred)
    result = await create_note({**note_request.model_dump(), "dry_run": False, "perception": perception_request(note_request)})
    assert result["status"] == "complete", result
    assert result["steps"][0]["origin"] == ("model_inference" if kind == "valid" else "caller_proposal")
    assert len(result["perception"]["timeline"]) == len(events)
    assert result["supplied_steps"][0]["instruction"] == note_request.steps[0].instruction


@pytest.mark.parametrize("change", ["file", "hash", "grant", "nested-dry"])
async def test_perception_selection_refused_before_mutation(note_request, native_edges, tmp_path, change):
    selected = perception_request(note_request)
    if change == "file":
        other = tmp_path / "other.mp4"
        other.write_bytes(b"different source")
        selected["file_path"] = str(other)
    elif change == "hash":
        selected["expected_source_sha256"] = "0" * 64
    elif change == "grant":
        selected["authorize_submission"] = False
    else:
        selected["dry_run"] = True
    result = await create_note({**note_request.model_dump(), "dry_run": False, "perception": selected})
    assert "error" in result and not Path(note_request.output_path).exists()
    assert not list(Path(note_request.output_path).parent.glob("tutorial-note-*"))


@pytest.mark.parametrize("corruption", ["magic", "crc", "truncated", "pixels", "scanlines"])
def test_actual_png_structure_bounds(corruption):
    data = png()
    if corruption == "magic":
        data = b"invalid" + data[7:]
    elif corruption == "crc":
        data = data[:-5] + b"x" + data[-4:]
    elif corruption == "truncated":
        data = data[:-2]
    elif corruption == "pixels":
        data = png(16, 100)
    else:
        data = data.replace(b"IDAT", b"BADX")
    with pytest.raises(ValueError):
        png_shape(data, 200)


async def test_public_tool_returns_same_typed_controller_contract(note_request):
    from video_research_mcp.tools.video_note import video_note_create
    result = await video_note_create(note_request)
    assert result["operation"] == "video_note_create" and result["status"] == "dry_run"


async def test_final_destination_check_cannot_publish_after_deadline(note_request, native_edges, monkeypatch):
    from types import SimpleNamespace
    output = Path(note_request.output_path)
    output.write_bytes(b"preserved before expired final verification")
    clock = [time.monotonic()]
    monkeypatch.setattr(pipeline, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original, calls = pipeline.verify_destination, []
    def final_check(*args):
        original(*args)
        calls.append(True)
        if len(calls) == 2:
            clock[0] += get_config().media_acquire_timeout_seconds + 1
    monkeypatch.setattr(pipeline, "verify_destination", final_check)
    result = await create_note({**note_request.model_dump(), "dry_run": False, "overwrite": True})
    assert "error" in result
    assert output.read_bytes() == b"preserved before expired final verification"
    assert not list(output.parent.glob("tutorial-note-*"))


async def test_absent_destination_publication_never_clobbers_final_racer(note_request, native_edges, monkeypatch):
    output = Path(note_request.output_path)
    original, calls = pipeline.verify_destination, []
    def final_check(*args):
        original(*args)
        calls.append(True)
        if len(calls) == 2:
            output.write_bytes(b"writer arrived after final destination check")
    monkeypatch.setattr(pipeline, "verify_destination", final_check)
    result = await create_note({**note_request.model_dump(), "dry_run": False})
    assert "error" in result
    assert output.read_bytes() == b"writer arrived after final destination check"
    assert not list(output.parent.glob("tutorial-note-*"))


@pytest.mark.parametrize("condition", ["success", "bad-digest", "late-render-failure", "cancel"])
async def test_native_view_is_disposed_after_copy_or_fallback(note_request, native_edges, tmp_path, monkeypatch, condition):
    cache = tmp_path / "cache"
    monkeypatch.setattr(get_config(), "cache_dir", str(cache))
    view = cache / "media" / "views" / ("a" * 32)
    view.mkdir(parents=True)
    native = view / "frame001.png"
    native.write_bytes(png())
    async def extract(*args, **kwargs):
        return {"source": {"sha256": note_request.expected_source_sha256, "duration_seconds": 3},
                "frames": [{"path": str(native), "sha256": "0" * 64 if condition == "bad-digest" else digest(native.read_bytes()),
                            "bytes": native.stat().st_size, "width": 16, "height": 10,
                            "actual_seconds": .5, "original_pts": 5120, "time_base": "1/10240"}]}
    monkeypatch.setattr(frames, "frame_at", extract)
    if condition in {"late-render-failure", "cancel"}:
        def fail(*args, **kwargs):
            if condition == "cancel":
                raise asyncio.CancelledError
            raise RuntimeError("owned late render failure")
        monkeypatch.setattr(pipeline, "render_verified", fail)
    if condition == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await create_note({**note_request.model_dump(), "dry_run": False})
        assert not view.exists()
        assert not list(Path(note_request.output_path).parent.glob("tutorial-note-*"))
        return
    result = await create_note({**note_request.model_dump(), "dry_run": False})
    assert not view.exists()
    if condition == "late-render-failure":
        assert "error" in result
    else:
        assert result["status"] == "complete"
        assert len(result["frames"]) == (0 if condition == "bad-digest" else 1)
