"""Actual file/manifest/approval/lifecycle checks with the synthetic native boundary."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from tests.test_footage_edit_native import sha, video_info
from video_research_mcp import footage_edit as engine
from video_research_mcp.image_manifest import read_manifest
from video_research_mcp.models.footage_edit import AssembleRequest


pytest_plugins = ("tests.test_footage_edit_native",)


def approve(prepared):
    """Assert complete locks against exactly the prepared revision and scene bytes."""
    return AssembleRequest.model_validate({"action": "assemble", "manifest_path": prepared["manifest"]["path"],
        "expected_manifest_sha256": prepared["manifest"]["sha256"],
        "approvals": [{"scene_id": s["scene_id"], "scene_sha256": s["artifact"]["sha256"],
                       "prepared_manifest_sha256": prepared["manifest"]["sha256"], "locked": True}
                      for s in prepared["scenes"]]})


@pytest.mark.parametrize("patch", [
    {"fps": 31}, {"fps": float("nan")}, {"fps": True}, {"brief": " "}, {"look": "cinematic"},
    {"scenes": []}, {"scenes": [{"bad": "shape"}]},
])
async def test_typed_plan_refuses_before_native(boundary, patch):
    """Malformed caller intent cannot start native work or publish an artifact."""
    transport, plan, _, _ = boundary
    data = plan.model_dump()
    data.update(patch)
    with pytest.raises(ValidationError):
        await engine.execute(data)
    assert transport.calls == []


@pytest.mark.parametrize("field,value", [("end_seconds", .1), ("end_seconds", 100),
    ("start_seconds", -1), ("start_seconds", float("inf")), ("timeline_start_seconds", .01),
    ("crop_box", [-1, 0, 2, 2]), ("crop_box", [0, 0, True, 2]),
    ("grade", {"contrast": 1.2}), ("audio", {"gain_db": 1}), ("scene_id", "../escape")])
async def test_scene_bounds_refuse_before_native(boundary, field, value):
    """Explicit source, treatment and timing limits are enforced at the typed boundary."""
    transport, plan, _, _ = boundary
    data = plan.model_dump()
    data["scenes"][0][field] = value
    with pytest.raises(ValidationError):
        await engine.execute(data)
    assert transport.calls == []


async def test_prepare_commits_all_frames_signals_and_real_contact_artifacts(boundary):
    """Preparation persists exact source/scene commitments without creating a delivered final."""
    transport, plan, _, _ = boundary
    result = await engine.execute(plan)
    assert result["status"] == "prepared" and result["timeline"]["frame_count"] == 4
    frames = {s["scene_id"]: s["frames"] for s in result["scenes"]}
    resolved = [frames[f["scene_id"]][f["scene_frame_index"]] for f in result["timeline"]["frames"]]
    assert [f["original_pts"] for f in resolved] == [200, 300, 200, 300]
    assert [f["timeline_seconds"] for f in resolved] == [f["timeline_seconds"] for f in result["timeline"]["frames"]]
    assert [f["timeline_seconds"] for f in result["timeline"]["frames"]] == pytest.approx([0, .1, .2, .3])
    assert not (Path(result["manifest"]["path"]).parent / "final.mp4").exists()
    assert all(s["grade"]["before"]["frame_count"] == 2 for s in result["scenes"])
    assert all(s["grade"]["requested"] == {"contrast": 1., "gamma": 1., "saturation": 1.} for s in result["scenes"])
    assert all(sha(a["path"]) == a["sha256"] for a in result["artifacts"])
    assert (await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"]))["verified"]
    assert not any("eq=contrast" in " ".join(c) for c, _ in transport.calls)
    assert len([a for a in result["artifacts"] if a.get("role") == "scene_sample"]) == 4


@pytest.mark.parametrize("failure", ["missing", "duplicate", "wrong_id", "unlocked", "stale_scene", "stale_revision"])
async def test_assembly_requires_every_exact_revision_lock_before_native(boundary, failure):
    """Complete byte/revision-bound assertions replace arbitrary LOCKED prose."""
    transport, plan, _, _ = boundary
    prepared = await engine.execute(plan)
    request = approve(prepared).model_dump()
    if failure == "missing":
        request["approvals"].pop()
    elif failure == "duplicate":
        request["approvals"][1] = request["approvals"][0]
    elif failure == "wrong_id":
        request["approvals"][0]["scene_id"] = "other"
    elif failure == "unlocked":
        request["approvals"][0]["locked"] = False
    elif failure == "stale_scene":
        request["approvals"][0]["scene_sha256"] = "a" * 64
    else:
        request["approvals"][0]["prepared_manifest_sha256"] = "b" * 64
    calls = len(transport.calls)
    with pytest.raises(ValueError):
        await engine.execute(request)
    assert len(transport.calls) == calls
    assert Path(prepared["manifest"]["path"]).exists()


async def test_assemble_final_technical_and_restart_readback_exact_b_preview(boundary):
    """Delivered final is separately staged and B samples use actual final B frame positions."""
    transport, plan, _, _ = boundary
    prepared = await engine.execute(plan)
    result = await engine.execute(approve(prepared))
    assert result["status"] == "delivered" and result["technical"]["full_decode"]
    assert result["technical"]["audio"]["loudness"]["integrated_lufs"] == -18
    assert result["technical"]["black"]["spans"] == []
    final_dir = Path(result["manifest"]["path"]).parent
    prepared_dir = Path(prepared["manifest"]["path"]).parent
    assert final_dir != prepared_dir
    assert all(Path(a["path"]).parent == final_dir for a in result["artifacts"])
    assert all(Path(s["artifact"]["path"]).parent == final_dir for s in result["scenes"])
    b = [a for a in result["artifacts"] if a.get("role") == "scene_sample" and a["scene_id"] == "S1"]
    assert [a["decoded_video_frame_index"] for a in b] == [2, 3]
    with Image.open(b[0]["path"]) as image:
        assert image.getpixel((0, 0)) == (120, 40, 60)
    calls = len(transport.calls)
    restored = await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])
    assert restored["verified"] and restored["timeline"] == result["timeline"]
    assert len(transport.calls) == calls
    Path(result["scenes"][0]["artifact"]["path"]).write_bytes(b"changed approved copy")
    with pytest.raises(ValueError, match="identity changed"):
        await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])
    assert prepared_dir.exists()


@pytest.mark.parametrize("target", ["source", "scene", "manifest"])
async def test_tampered_prepared_input_refuses_before_more_native(boundary, target):
    """Restart validates actual original, scene and manifest bytes before assembly dispatch."""
    transport, plan, sources, _ = boundary
    prepared = await engine.execute(plan)
    path = sources[0] if target == "source" else Path(prepared["scenes"][0]["artifact"]["path"] if target == "scene" else prepared["manifest"]["path"])
    path.write_bytes(b"tampered")
    calls = len(transport.calls)
    with pytest.raises(ValueError):
        await engine.execute(approve(prepared))
    assert len(transport.calls) == calls


@pytest.mark.parametrize("kind", ["black", "hot", "command"])
async def test_final_failure_removes_only_new_stage_preserves_prepared(boundary, kind):
    """Technical failures are terminal and do not delete a previous prepared revision."""
    transport, plan, _, _ = boundary
    prepared = await engine.execute(plan)
    base = Path(prepared["manifest"]["path"]).parent.parent
    before = {p.name for p in base.iterdir()}
    if kind == "command":
        transport.fail = lambda command: "-filter_complex" in command
    else:
        setattr(transport, kind, True)
    with pytest.raises((ValueError, RuntimeError)):
        await engine.execute(approve(prepared))
    assert {p.name for p in base.iterdir()} == before
    assert (await read_manifest(prepared["manifest"]["path"], prepared["manifest"]["sha256"]))["verified"]


async def test_missing_required_audio_and_explicit_structural_mute(boundary):
    """Missing source audio fails preservation; mute produces no invented loudness."""
    transport, plan, sources, _ = boundary
    for path in sources:
        path.write_text(json.dumps(video_info(list(range(0, 1000, 100)), 1, audio=False)))
    data = plan.model_dump()
    for scene, path in zip(data["scenes"], sources):
        scene["expected_source_sha256"] = sha(path)
    with pytest.raises(ValueError, match="Required source audio"):
        await engine.execute(data)
    for scene in data["scenes"]:
        scene["audio"]["mode"] = "mute"
    prepared = await engine.execute(data)
    final = await engine.execute(approve(prepared))
    assert final["technical"]["audio"]["loudness"] is None
    command = next(c for c, _ in transport.calls if "-filter_complex" in c)
    assert "-an" in command


async def test_explicit_grade_measures_before_after_without_changing_lineage(boundary):
    """Typed correction changes the mocked native treatment while full source PTS remain bound."""
    transport, plan, _, _ = boundary
    data = plan.model_dump()
    data["scenes"][0]["grade"] = {"contrast": 1.04, "gamma": 1.02, "saturation": .98}
    result = await engine.execute(data)
    assert result["scenes"][0]["grade"]["before"]["fields"]["YAVG"]["mean"] == 80
    assert result["scenes"][0]["grade"]["after"]["fields"]["YAVG"]["mean"] == 82
    assert result["timeline"]["frame_count"] == 4
    assert any("eq=contrast=1.04:gamma=1.02:saturation=0.98" in " ".join(c) for c, _ in transport.calls)


@pytest.mark.parametrize("kind", ["symlink", "url", "wrong_hash", "outside"])
async def test_source_path_identity_fence_before_native(boundary, tmp_path, kind):
    """Only exact regular local sources inside the operator fence can enter preparation."""
    transport, plan, sources, _ = boundary
    data = plan.model_dump()
    if kind == "symlink":
        path = tmp_path / "link.mp4"
        path.symlink_to(sources[0])
        data["scenes"][0]["file_path"] = str(path)
    elif kind == "url":
        data["scenes"][0]["file_path"] = "https://fixture.invalid/source.mp4"
    elif kind == "outside":
        data["scenes"][0]["file_path"] = str(tmp_path.parent / "outside.mp4")
    else:
        data["scenes"][0]["expected_source_sha256"] = "0" * 64
    with pytest.raises((ValueError, PermissionError)):
        await engine.execute(data)
    assert transport.calls == []


async def test_source_exit_verification_failure_cleans_already_written_stage(boundary, monkeypatch):
    """Snapshot closing verification must finish before a prepared stage can be retained."""
    _, plan, _, _ = boundary
    original = engine.snapshot

    @asynccontextmanager
    async def changed_on_exit(*args):
        async with original(*args) as owned:
            yield owned
            owned.original.write_bytes(b"changed during closing verification")

    monkeypatch.setattr(engine, "snapshot", changed_on_exit)
    with pytest.raises(ValueError, match="changed"):
        await engine.execute(plan)
    base = Path(plan.scenes[0].file_path).parent / "cache/media/views"
    assert list(base.iterdir()) == []


async def test_cancel_cleanup_and_serialization_preserve_prior_stage(boundary):
    """Canceled new native work joins before cleanup and cannot remove prepared artifacts."""
    transport, plan, _, _ = boundary
    prepared = await engine.execute(plan)
    base = Path(prepared["manifest"]["path"]).parent.parent
    names = {p.name for p in base.iterdir()}
    transport.block = asyncio.Event()
    before = len(transport.calls)
    task = asyncio.create_task(engine.execute(approve(prepared)))
    await asyncio.sleep(.02)
    second = asyncio.create_task(engine.execute(approve(prepared)))
    await asyncio.sleep(.02)
    assert len(transport.calls) == before + 1
    task.cancel()
    second.cancel()
    await asyncio.gather(task, second, return_exceptions=True)
    assert {p.name for p in base.iterdir()} == names
    assert Path(prepared["manifest"]["path"]).exists()


async def test_approval_replay_after_brief_revision_refuses_even_when_scene_sha_equal(boundary):
    """The whole manifest revision invalidates previous assertions with unchanged scene bytes."""
    from video_research_mcp.image_manifest import json_digest, write_manifest
    from video_research_mcp.media_snapshot import view_directory

    transport, plan, _, _ = boundary
    prepared = await engine.execute(plan)
    changed = copy.deepcopy(prepared)
    changed.pop("manifest")
    changed["plan"]["brief"] = "Changed scope, same scene artifact bytes"
    changed["plan_sha256"] = json_digest(changed["plan"])
    manifest = await write_manifest(changed, view_directory())
    old = approve(prepared).model_dump()
    old.update(manifest_path=manifest["path"], expected_manifest_sha256=manifest["sha256"])
    calls = len(transport.calls)
    with pytest.raises(ValueError, match="stale"):
        await engine.execute(old)
    assert len(transport.calls) == calls


async def test_complete_operation_timeout_does_not_leave_stage_or_late_work(boundary):
    """The caller deadline cancels a blocked native await and cleanup finishes before return."""
    from video_research_mcp.config import get_config

    transport, plan, _, _ = boundary
    get_config().media_acquire_timeout_seconds = 1
    transport.block = asyncio.Event()
    with pytest.raises(TimeoutError):
        await engine.execute(plan)
    calls = len(transport.calls)
    transport.block.set()
    await asyncio.sleep(.01)
    assert len(transport.calls) == calls == 1
    base = Path(plan.scenes[0].file_path).parent / "cache/media/views"
    assert list(base.iterdir()) == []


@pytest.mark.parametrize("stage", ["scene", "final"])
async def test_measurement_cannot_adopt_modified_initial_artifact(boundary, stage):
    """Mutation after the first decoded read must refuse, clean only new output, retain prior evidence."""
    transport, plan, _, _ = boundary
    prepared = await engine.execute(plan) if stage == "final" else None
    mutated = []

    def alter_after_read(command):
        if Path(command[0]).name != "ffprobe" or "-show_frames" not in command or mutated:
            return
        path = Path(command[command.index("-i") + 1])
        if path.name != ("S0.mp4" if stage == "scene" else "final.mp4"):
            return
        path.write_bytes(path.read_bytes() + b" ")
        mutated.append(str(path))

    transport.mutate = alter_after_read
    before = set((Path(plan.scenes[0].file_path).parent / "cache/media/views").glob("*"))
    with pytest.raises(ValueError, match="artifact.*changed|identity changed"):
        await engine.execute(approve(prepared) if prepared else plan)
    assert mutated
    assert set((Path(plan.scenes[0].file_path).parent / "cache/media/views").glob("*")) == before
    if prepared:
        assert Path(prepared["manifest"]["path"]).is_file()


async def test_complete_ninety_six_frame_edit_retains_lineage_within_manifest_ceiling(boundary):
    """The fixed-size edit fits the unchanged manifest limit without dropping source records."""
    _, plan, sources, _ = boundary
    data = plan.model_dump()
    for index, path in enumerate(sources):
        path.write_text(json.dumps(video_info(list(range(0, 9600, 100)), 9.6, color=80 + index * 40)))
        data["scenes"][index].update(expected_source_sha256=sha(path), start_seconds=.2,
                                     end_seconds=5., timeline_start_seconds=index * 4.8)
    prepared = await engine.execute(data)
    final = await engine.execute(approve(prepared))
    assert final["status"] == "delivered" and final["manifest"]["bytes"] <= 128 * 1024
    scene_frames = {s["scene_id"]: s["frames"] for s in final["scenes"]}
    references = final["timeline"]["frames"]
    assert len(references) == len(final["technical"]["decoded_frames"]) == 96
    resolved = [scene_frames[r["scene_id"]][r["scene_frame_index"]] for r in references]
    assert len(scene_frames["S0"]) == len(scene_frames["S1"]) == 48
    assert all(f["source_decoded_pixel_sha256"] and f["source_sha256"] and f["time_base"] for f in resolved)
    assert [f["timeline_seconds"] for f in resolved] == [r["timeline_seconds"] for r in references]
    restored = await read_manifest(final["manifest"]["path"], final["manifest"]["sha256"])
    assert restored["scenes"] == final["scenes"] and restored["timeline"] == final["timeline"]
