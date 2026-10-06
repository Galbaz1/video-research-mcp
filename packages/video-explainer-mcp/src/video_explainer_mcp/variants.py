"""Approved contiguous shorts with atomic bounded per-variant outcome receipts."""

import asyncio
from contextlib import contextmanager
from pathlib import Path
import tempfile

from .evidence import atomic_write
from .jobs import get_job
from .materials import discard_published, publish, snapshot
from .media_process import run_media_process
from .models.materials import PinnedFile
from .plan_artifacts import require_binding
from .planning import plan_transaction, require_approved
from .planning_sources import canonical, digest, project_directory
from .render_storyboard_sources import confined_path, file_pin, project_object
from .render_validation import codec_executables, qualification_valid
from .storyboard_timing import require_current_timing
from .variants_captions import caption_layout, check_srt, font_metrics, source_cues, srt_text
from .variants_render import DIMENSIONS, backend, qualify, recipe

MANIFEST = "variants-manifest.json"


def current(project: Path, state: dict, request) -> dict:
    """Require current original sources, real accepted timing, and a bound render job."""
    if state is None:
        raise ValueError("Variants require a managed approved plan")
    require_approved(project, state)
    script = require_binding(project, state, "script")
    narration = require_binding(project, state, "narration")
    timing = require_current_timing(project, state)
    if timing is None:
        raise ValueError("Missing current timing/captions")
    job = get_job(request.source_job_id)
    if not job or job["status"] != "completed" or not job["attestation"]["verified"]:
        raise ValueError("Source render job is unavailable or unverified")
    artifact = job["result"]["output"]
    if job["request"]["project_dir"] != str(project) or not qualification_valid(artifact):
        raise ValueError("Source render lacks current project/full-decode qualification")
    if job["request"].get("renderer", {}).get("route") != "authored_storyboard" or artifact["qualification"].get("authored_storyboard", {}).get("frames") != timing["video_frames"]:
        raise ValueError("Source render lacks bound authored scene clock qualification")
    video = confined_path(project, request.source_video.path)
    if str(video) != artifact["path"] or file_pin(video, 64 * 1024 * 1024)["sha256"] != request.source_video.sha256 or artifact["sha256"] != request.source_video.sha256:
        raise ValueError("Source video differs from the completed render")
    frozen = job["request"]["source"]["files"]
    for binding in state["bindings"].values():
        if binding["path"] not in frozen or frozen[binding["path"]]["sha256"] != binding["sha256"]:
            raise ValueError("Source render belongs to stale approved artifacts")
    if frozen.get(".timing/manifest.json", {}).get("sha256") != file_pin(confined_path(project, ".timing/manifest.json"), 1024 * 1024)["sha256"]:
        raise ValueError("Source render belongs to stale timing")
    names = [s["scene_id"] for s in timing["scenes"]]
    first = names.index(request.scene_ids[0])
    scenes = timing["scenes"][first:first + len(request.scene_ids)]
    if [s["scene_id"] for s in scenes] != request.scene_ids:
        raise ValueError("Short scenes must be complete, contiguous and in original order")
    end_frame = scenes[-1]["from_video_frame"] + scenes[-1]["video_frames"]
    duration = (end_frame - scenes[0]["from_video_frame"]) / 30
    cues = source_cues(narration, timing, scenes)
    if duration > 180 or any(c["end_sample"] / c["sample_rate"] > duration for c in cues):
        raise ValueError("Short exceeds180seconds or would cut a source caption interval")
    selected = script["video_research_plan"]["scenes"][first:first + len(scenes)]
    return {"start_frame": scenes[0]["from_video_frame"], "end_frame": end_frame,
            "start_sample": scenes[0]["start_sample"], "end_sample": scenes[-1]["end_sample"], "duration": duration,
            "source_clock_offset_seconds": scenes[0]["from_video_frame"] / 30 - scenes[0]["start_sample"] / timing["sample_rate"],
            "audio": narration["artifact"], "cues": cues, "claims": selected,
            "plan_sha256": state["plan_sha256"], "source_commitment_sha256": state["source_commitment_sha256"],
            "job_request_sha256": job["request_sha256"], "job_result_sha256": job["result_sha256"],
            "timestamp_method": timing["timestamp_method"], "scene_ids": request.scene_ids}


def load(project: Path) -> dict:
    """Never discard a retained failure or interrupted denominator on restart."""
    if not confined_path(project, MANIFEST).exists():
        return {"version": 1, "batches": {}}
    value, _ = project_object(project, MANIFEST)
    if set(value) != {"version", "batches"} or value["version"] != 1 or not isinstance(value["batches"], dict) or len(value["batches"]) > 16:
        raise ValueError("Invalid or oversized variants manifest")
    return value


def save(project: Path, manifest: dict) -> None:
    """Publish one complete bounded outcome checkpoint atomically."""
    encoded = canonical(manifest)
    if len(encoded.encode()) > 1024 * 1024 or len(manifest["batches"]) > 16:
        raise ValueError("Variants manifest exceeds1MiB/16batches")
    atomic_write(confined_path(project, MANIFEST), encoded)


async def one(work: Path, aspect: str, layout: dict, context: dict, executables: dict, row: dict) -> None:
    """Render privately, qualify completely, and publish exact new output bytes."""
    command = recipe(context, aspect, layout, executables["ffmpeg"]["path"])
    stdout, stderr = await run_media_process(command, 15, cwd=work)
    if stdout or stderr:
        raise ValueError("Variant renderer reported errors")
    path = work / command[-1]
    proof = await qualify(path, aspect, context, executables)
    row.update(output_sha256=proof["sha256"], qualification=proof, command=command)


def verify_current(project: Path, state: dict, request, context: dict, metrics: dict, executables: dict) -> None:
    """Recheck every source/backend/font/SRT binding after an awaited operation."""
    if current(project, state, request) != context or codec_executables() != executables or font_metrics(project, request.font) != metrics:
        raise ValueError("Variant input/backend changed; later outcomes remain unrun")
    if request.srt:
        check_srt(project, request.srt, srt_text(context["cues"]))


def validate_cached(batch: dict, config: dict, key: str, request) -> None:
    """Refuse changed identities, fixed caption metadata and inconsistent completion."""
    if batch["configuration"] != config or batch["batch_sha256"] != key:
        raise ValueError("Cached variant configuration/identity changed")
    if batch["factual_success"] is not False or batch["visual_semantics"] != "not_verified" or batch["captions_srt"] != srt_text(config["source"]["cues"]):
        raise ValueError("Cached variant fixed metadata changed")
    if [r["aspect"] for r in batch["outcomes"]] != request.aspects:
        raise ValueError("Cached variant denominator/order changed")
    statuses = [r["status"] for r in batch["outcomes"]]
    if any(s not in ("success", "error", "pending", "unrun") for s in statuses):
        raise ValueError("Cached variant outcome status changed")
    if any(s in ("pending", "unrun") for s in statuses):
        expected = "pending"
    elif all(s == "success" for s in statuses):
        expected = "complete"
    else:
        expected = "partial"
    if batch["status"] != expected:
        raise ValueError("Cached variant batch status differs from its outcome population")


def save_after_failure(project: Path, manifest: dict, primary: BaseException) -> None:
    """Preserve the primary cause when an error/final checkpoint cannot be confirmed."""
    try:
        save(project, manifest)
    except BaseException as persistence:  # noqa: BLE001 - secondary failure must preserve the primary
        primary.add_note(f"Variant checkpoint persistence liability:{type(persistence).__name__}; write durability unconfirmed")
        raise primary from persistence


@contextmanager
def working_directory():
    """Clean temporary snapshots without replacing cancellation or another primary cause."""
    directory = tempfile.TemporaryDirectory(prefix="vrm-variants-")
    try:
        yield Path(directory.name)
    except BaseException as primary:  # noqa: BLE001 - retain cancellation and other primary causes
        try:
            directory.cleanup()
        except BaseException as cleanup:  # noqa: BLE001 - cleanup is a secondary liability
            primary.add_note(f"Variant temporary cleanup liability:{type(cleanup).__name__}")
        raise
    else:
        directory.cleanup()


async def execute(project: Path, state: dict, request, context: dict, metrics: dict, executables: dict, manifest: dict, batch: dict) -> dict:
    """Retain every outcome and refuse uncertain automatic retries after interruption."""
    first_failure = None
    with working_directory() as work:
        snapshot(project, request.source_video, work / "source.mp4")
        snapshot(project, request.font, work / "font.ttf")
        snapshot(project, PinnedFile(path=context["audio"]["path"], sha256=context["audio"]["sha256"]), work / "audio.wav")
        for i, cue in enumerate(context["cues"]):
            (work / f"cue-{i}.txt").write_text(cue["text"], encoding="utf-8")
        await backend(executables, work)
        for row in batch["outcomes"]:
            verify_current(project, state, request, context, metrics, executables)
            aspect = row["aspect"]
            row["status"] = "pending"
            save(project, manifest)
            published = None
            try:
                layout = caption_layout(context["cues"], metrics, *DIMENSIONS[aspect])
                await one(work, aspect, layout, context, executables, row)
                verify_current(project, state, request, context, metrics, executables)
                if any(r.get("output_sha256") == row["output_sha256"] and r is not row for r in batch["outcomes"]):
                    raise ValueError("Distinct variants returned identical output hashes")
                name = f"variant-{row['configuration_sha256']}.mp4"
                published = publish(project, work / recipe(context, aspect, layout, executables["ffmpeg"]["path"])[-1], name, row["output_sha256"])
                row.update(status="success", path=name, caption_bounds=layout)
                save(project, manifest)
            except Exception as error:
                if first_failure is None:
                    first_failure = error
                if published is not None:
                    discard_published(project, published.name, row["output_sha256"], error)
                row.update(status="error", error=str(error), cleanup_liability=getattr(error, "__notes__", []))
                row.pop("path", None)
                save_after_failure(project, manifest, error)
        batch["status"] = "complete" if all(r["status"] == "success" for r in batch["outcomes"]) else "partial"
        if first_failure is None:
            save(project, manifest)
        else:
            save_after_failure(project, manifest, first_failure)
        return batch


async def _variants(project: Path, request) -> dict:
    """Hold canonical plan admission across current checks, rendering and checkpoints."""
    with plan_transaction(project) as (_, state):
        context = current(project, state, request)
        metrics = font_metrics(project, request.font)
        if request.srt:
            check_srt(project, request.srt, srt_text(context["cues"]))
        executables = codec_executables()
        config = {"request": request.model_dump(mode="json"), "source": context, "executables": executables, "fit": "contain_no_crop"}
        key, manifest = digest(config), load(project)
        if key in manifest["batches"]:
            batch = manifest["batches"][key]
            validate_cached(batch, config, key, request)
            for row in batch["outcomes"]:
                if row["configuration_sha256"] != digest({"batch": key, "aspect": row["aspect"]}):
                    raise ValueError("Cached variant identity changed")
                if row["status"] == "success":
                    if row["path"] != f"variant-{row['configuration_sha256']}.mp4":
                        raise ValueError("Cached variant output path changed")
                    proof = await qualify(confined_path(project, row["path"]), row["aspect"], context, executables)
                    if proof != row["qualification"] or proof["sha256"] != row["output_sha256"]:
                        raise ValueError("Cached variant bytes or qualification changed")
            verify_current(project, state, request, context, metrics, executables)
            return {**batch, "cached": True, "retry_policy": "retained_pending_error_unrun_not_retried"}
        batch = {"status": "pending", "batch_sha256": key, "configuration": config, "captions_srt": srt_text(context["cues"]),
                 "factual_success": False, "visual_semantics": "not_verified", "outcomes": [
                     {"aspect": a, "status": "unrun", "configuration_sha256": digest({"batch": key, "aspect": a})} for a in request.aspects]}
        manifest["batches"][key] = batch
        save(project, manifest)
        return await execute(project, state, request, context, metrics, executables, manifest, batch)


async def create_variants(project_id: str, request) -> dict:
    """Invoke a finite local batch; cancellation leaves retained pending/unrun records."""
    return await asyncio.wait_for(_variants(project_directory(project_id), request), 180)
