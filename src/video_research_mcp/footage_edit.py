"""Two-stage exact-source footage preparation and hash-approved technical delivery."""

import asyncio
import shutil
import time
from contextlib import AsyncExitStack, asynccontextmanager

from pydantic import TypeAdapter

from .config import get_config
from .footage_edit_native import (
    NativeWork, assemble_command, decoded, input_command, probe, scene_command, selected_command,
)
from .footage_edit_qa import frame_hashes, full_review, signal
from .footage_edit_timeline import beat_report, contacts, samples, scene_frames
from .image_manifest import json_digest, read_manifest, write_manifest
from .media_clip_export import _audio_result, _bounds, _window
from .media_clip_timing import source_audio, source_frames, verify_output
from .media_image_read import decode_command
from .media_snapshot import checked_path, copy_hash, snapshot, view_directory
from .models.footage_edit import FootageEditRequest, FootageEditResult, PrepareRequest
from .models.media_export import ClipExportRequest

_SERIAL = asyncio.Lock()
_LIMITS = {"max_sources": 2, "max_scenes": 8, "max_frames": 256, "max_fps": 30,
           "max_frame_pixels": 1000000, "max_artifacts": 64, "max_artifact_bytes": 8388608,
           "max_manifest_bytes": 131072, "native_process_output_bytes": 1048576,
           "standards_conformance_verified": False, "process_rss_bound": None}
_PROVENANCE = {"workflow": "owned_local_linear_hard_cut_ffmpeg",
               "foreign_code_executed": False, "generated_media": False, "fonts_used": [],
               "visual_semantic_human_acceptance_verified": False, "rights_verified": False,
               "approval_assertions": "externally_supplied_not_authenticated_human_review",
               "binary_identity": "complete_installed_file_observation_not_source_build_or_os_isolation"}
_WARNINGS = ["Technical gates and revision commitments do not establish visual, semantic or human acceptance.",
             "Declared beat grids are caller assertions; no music beat detection is performed.",
             "HyperFrames, GSAP, external fonts, SFX and model/provider execution are unqualified in this route."]


@asynccontextmanager
async def _stage():
    """Remove only this invocation's exclusive UUID directory on failure or cancellation."""
    directory = view_directory()
    try:
        yield directory
    except BaseException:
        shutil.rmtree(directory)
        raise


def _clip(scene):
    """Use the accepted clip geometry and half-open source selection contract."""
    return ClipExportRequest(file_path=scene.file_path, expected_source_sha256=scene.expected_source_sha256,
                             start_seconds=scene.start_seconds, end_seconds=scene.end_seconds,
                             crop_box=scene.crop_box, max_pixels=1000000, include_audio=scene.audio.mode == "preserve")


async def _artifact(path, dimensions):
    """Commit the complete regular encoded file rather than a shortened checksum."""
    digest, size = await copy_hash(path)
    if not 0 < size <= 8388608:
        raise ValueError("Footage artifact is empty or exceeds the 8 MiB ceiling")
    path.chmod(0o600)
    return {"path": str(path), "sha256": digest, "bytes": size, "mime": "video/mp4",
            "width": dimensions[0], "height": dimensions[1]}


async def _scene(scene, owned, source, work, directory, fps):
    """Encode every selected original frame and measure the declared treatment."""
    request = _clip(scene)
    offset, width, height, transform, audio, scale = _bounds(source, request)
    if request.include_audio and audio is None:
        raise ValueError("Required source audio is missing; choose an explicit mute plan")
    raw, stderr = await work.run(selected_command(owned, source, request, offset))
    original = source_frames(stderr, source, request.start_seconds, request.end_seconds)
    lineage = scene_frames(scene, original, frame_hashes(raw, len(original)), fps)
    options, expression = _window(request, offset)
    before = await signal(work, decode_command(owned, source, before_input=options), len(original),
                          f"select='{expression}',{transform}")
    path = directory / (scene.scene_id + ".mp4")
    _, stderr = await work.run(scene_command(owned, source, request, offset, transform, audio, path, scene))
    artifact = await _artifact(path, (width, height))
    if source_frames(stderr, source, request.start_seconds, request.end_seconds) != original:
        raise ValueError("Scene encoding did not visit the complete selected source population")
    measured = await decoded(path, work)
    verify_output(measured, original, request.start_seconds, width, height)
    audio_clock = source_audio(stderr, offset, request.start_seconds, request.end_seconds) if audio else None
    audio_result = _audio_result(measured, audio_clock, original, request.start_seconds, request.include_audio)
    after = await signal(work, input_command(path) + ["-map", "0:v:0"], len(original))
    stdout, _ = await work.run(input_command(path) + ["-map", "0:v:0", "-an", "-vf", "format=rgb24",
                                                     "-fps_mode", "passthrough", "-f", "framehash", "-hash", "sha256", "-"])
    if await copy_hash(path) != (artifact["sha256"], artifact["bytes"]):
        raise ValueError("Encoded scene artifact changed during measurement")
    await owned.verify()
    return {"scene_id": scene.scene_id, "source_sha256": source["sha256"], "frames": lineage,
            "artifact": artifact, "output": measured["output"], "audio": audio_result,
            "audio_policy": scene.audio.model_dump(),
            "audio_format": {"sample_rate": int(audio["sample_rate"]), "channels": audio["channels"]} if audio else None,
            "grade": {"requested": scene.grade.model_dump(), "before": before, "after": after,
                      "comparison_includes_encoding_and_pixel_conversion": True},
            "geometry": {"crop_box": scene.crop_box, "scale": scale},
            "decoded_frames": frame_hashes(stdout, len(original)),
            "duration_seconds": scene.end_seconds - scene.start_seconds,
            "timeline_start_seconds": scene.timeline_start_seconds,
            "timeline_end_seconds": scene.timeline_start_seconds + scene.end_seconds - scene.start_seconds}


def _timeline(plan, scenes, beats):
    """Commit the complete measured original-to-output population and exact hard cuts."""
    dimensions = [scenes[0]["output"]["width"], scenes[0]["output"]["height"]]
    if any([s["output"]["width"], s["output"]["height"]] != dimensions for s in scenes):
        raise ValueError("Scene output grids are incompatible; revise explicit crop geometry")
    if any(s["audio_format"] != scenes[0]["audio_format"] for s in scenes):
        raise ValueError("Scene audio formats are incompatible; this route does not silently remix them")
    frames = [{"scene_id": scene["scene_id"], "scene_frame_index": frame["scene_frame_index"],
               "timeline_seconds": frame["timeline_seconds"]} for scene in scenes for frame in scene["frames"]]
    if len(frames) > 256:
        raise ValueError("Actual decoded source population exceeds 256 frames")
    return {"fps": plan.fps, "dimensions": dimensions, "duration_seconds": scenes[-1]["timeline_end_seconds"],
            "frame_count": len(frames), "frames": frames, "beats": beats,
            "transitions": "hard_cuts_only", "music_added": False, "audio_mode": plan.scenes[0].audio.mode}


def _metadata(status, plan, sources, scenes, timeline, artifacts, work, technical, approval):
    """Keep supplied intent, actual evidence and acceptance limitations distinct."""
    return {"status": status, "operation": "local_footage_edit", "source": sources[0], "sources": sources,
            "plan": plan.model_dump(), "plan_sha256": json_digest(plan.model_dump()), "scenes": scenes,
            "timeline": timeline, "artifact": artifacts[0], "artifacts": artifacts, "technical": technical,
            "native_identities": work.identities, "approval_status": approval, "provenance": _PROVENANCE,
            "warnings": _WARNINGS, "limits": {**_LIMITS, "operation_timeout_seconds": get_config().media_acquire_timeout_seconds}}


async def _prepare(plan, work):
    """Prepare scene MP4s and contact evidence without producing a delivered final."""
    beats = beat_report(plan)
    keys = {(str(checked_path(s.file_path)), s.expected_source_sha256) for s in plan.scenes}
    if len(keys) > 2 or len({p for p, _ in keys}) != len(keys):
        raise ValueError("Source paths must bind at most two distinct exact revisions")
    async with _stage() as directory, AsyncExitStack() as stack:
        owned = {}
        for key in sorted(keys):
            owned[key] = await stack.enter_async_context(snapshot(*key))
            owned[key].deadline = work.deadline
        await work.admit()
        sources = {key: await probe(value, work) for key, value in owned.items()}
        scenes, artifacts, previews = [], [], []
        for scene in plan.scenes:
            key = str(checked_path(scene.file_path)), scene.expected_source_sha256
            result = await _scene(scene, owned[key], sources[key], work, directory, plan.fps)
            scenes.append(result)
            artifacts.append(result["artifact"])
            previews.extend(await samples(result, directory, work))
        timeline = _timeline(plan, scenes, beats)
        artifacts += previews + await contacts(previews, scenes, directory, work)
        metadata = _metadata("prepared", plan, list(sources.values()), scenes, timeline, artifacts, work,
                             {"status": "scene_evidence_prepared_final_review_pending"},
                             {"status": "pending_exact_scene_approvals", "human_review_verified": False})
        for value in owned.values():
            await value.verify()
        await work.verify()
        metadata["manifest"] = await write_manifest(metadata, directory)
        return FootageEditResult.model_validate(metadata).model_dump()

def _approved(prepared, request):
    """Bind complete external lock assertions to the exact prepared revision and scenes."""
    if prepared.get("status") != "prepared" or prepared.get("operation") != "local_footage_edit":
        raise ValueError("Assembly requires a prepared footage-edit manifest")
    plan = PrepareRequest.model_validate(prepared["plan"])
    if json_digest(plan.model_dump()) != prepared["plan_sha256"]:
        raise ValueError("Prepared plan commitment changed")
    approvals = {a.scene_id: a for a in request.approvals}
    scenes = prepared["scenes"]
    if len(approvals) != len(request.approvals) or set(approvals) != {s.scene_id for s in plan.scenes}:
        raise ValueError("Assembly requires exactly one approval for every prepared scene ID")
    if [s["scene_id"] for s in scenes] != [s.scene_id for s in plan.scenes]:
        raise ValueError("Prepared scene identities differ from the plan")
    for scene in scenes:
        approval = approvals[scene["scene_id"]]
        if (not approval.locked or approval.scene_sha256 != scene["artifact"]["sha256"]
                or approval.prepared_manifest_sha256 != request.expected_manifest_sha256):
            raise ValueError("Scene approval is unlocked or bound to stale scene bytes")
        if scene["artifact"] not in prepared["artifacts"]:
            raise ValueError("Prepared scene artifact is absent from manifest commitments")
    if _timeline(plan, scenes, beat_report(plan)) != prepared["timeline"]:
        raise ValueError("Prepared timeline changed from its measured scene ledger")
    return plan


async def _assemble(request, work):
    """Preserve prepared evidence while creating a separately gated approved final."""
    prepared = await read_manifest(request.manifest_path, request.expected_manifest_sha256)
    plan = _approved(prepared, request)
    await work.admit()
    async with _stage() as directory:
        inputs = []
        for i, scene in enumerate(prepared["scenes"]):
            path = checked_path(scene["artifact"]["path"])
            target = directory / f"input-{i}.mp4"
            if await copy_hash(path, target) != (scene["artifact"]["sha256"], scene["artifact"]["bytes"]):
                raise ValueError("Prepared scene changed before final assembly")
            inputs.append(target)
        output = directory / "final.mp4"
        await work.run(assemble_command(prepared["scenes"], directory, output))
        artifact = await _artifact(output, prepared["timeline"]["dimensions"])
        measured = await decoded(output, work)
        technical = await full_review(output, work, measured, prepared["timeline"], plan.scenes[0].audio.mode == "preserve")
        if await copy_hash(output) != (artifact["sha256"], artifact["bytes"]):
            raise ValueError("Encoded final artifact changed during measurement")
        artifacts = [artifact]
        scenes = [{**scene, "artifact": {**scene["artifact"], "path": str(inputs[i]), "role": "approved_scene_copy"}}
                  for i, scene in enumerate(prepared["scenes"])]
        artifacts += [scene["artifact"] for scene in scenes]
        previews = []
        offset = 0
        for scene in scenes:
            count = len(scene["frames"])
            selection = {**scene, "artifact": artifacts[0], "output_frame_offset": offset,
                         "output": {**measured["output"], "frame_count": count,
                                    "decoded_frame_seconds": measured["output"]["decoded_frame_seconds"][offset:offset + count]},
                         "decoded_frames": technical["decoded_frames"][offset:offset + count]}
            previews.extend(await samples(selection, directory, work))
            offset += count
        artifacts += previews + await contacts(previews, scenes, directory, work)
        rejoined = await read_manifest(request.manifest_path, request.expected_manifest_sha256)
        if rejoined != prepared:
            raise ValueError("Prepared revision changed during final assembly")
        for i, path in enumerate(inputs):
            scene = scenes[i]["artifact"]
            if await copy_hash(path) != (scene["sha256"], scene["bytes"]):
                raise ValueError("Owned assembly input changed")
        await work.verify()
        approval = {"status": "complete_exact_scene_assertions", "prepared_manifest": prepared["manifest"],
                    "approvals": [a.model_dump() for a in request.approvals], "human_review_verified": False}
        metadata = _metadata("delivered", plan, prepared["sources"], scenes, prepared["timeline"], artifacts, work, technical, approval)
        metadata["manifest"] = await write_manifest(metadata, directory)
        return FootageEditResult.model_validate(metadata).model_dump()


async def execute(request: FootageEditRequest) -> dict:
    """Prepare or assemble a typed local edit under serialized, joined bounded work."""
    request = TypeAdapter(FootageEditRequest).validate_python(request)
    timeout = get_config().media_acquire_timeout_seconds
    deadline = time.monotonic() + timeout
    async with asyncio.timeout(timeout):
        async with _SERIAL:
            work = NativeWork(deadline)
            return await _prepare(request, work) if request.action == "prepare" else await _assemble(request, work)
