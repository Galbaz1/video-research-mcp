"""Exact input snapshots and an ordered, fitted silent H264 material recipe."""

import asyncio
from pathlib import Path
import tempfile

from .materials import (
    MAX_ASSET_BYTES, discard_published, load_manifest, publish, save_manifest, snapshot, source_receipt,
)
from .media_process import run_media_process
from .models.materials import MaterialsRequest
from .planning import plan_transaction
from .planning_sources import digest, project_directory
from .render_storyboard_sources import confined_path, file_pin
from .render_validation import RESOLUTIONS, codec_executables, qualify_render


def render_recipe(request: MaterialsRequest, sources: list[Path], target: Path, binary: str) -> list[str]:
    """Build a deterministic concat graph in caller order with explicit temporal fitting."""
    width, height = RESOLUTIONS[request.resolution]
    command = [binary, "-v", "error", "-nostdin", "-xerror", "-n"]
    filters = []
    for index, (clip, source) in enumerate(zip(request.clips, sources, strict=True)):
        command += ["-protocol_whitelist", "file,pipe"]
        if clip.kind == "image":
            command += ["-loop", "1", "-framerate", str(request.fps), "-f", "image2", "-pattern_type", "none"]
        else:
            command += ["-f", "mov"]
        command += ["-i", str(source)]
        mode = "increase" if clip.fit == "cover" else "decrease"
        fit = f"scale={width}:{height}:force_original_aspect_ratio={mode}"
        fit += f",crop={width}:{height}" if clip.fit == "cover" else f",pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        if clip.motion == "zoom":
            if clip.kind != "image":
                raise ValueError("Zoom motion requires a still image")
            fit += f",zoompan=z='min(zoom+0.001,1.1)':d=1:s={width}x{height}:fps={request.fps}"
        filters.append(f"[{index}:v]trim=start={clip.start_seconds}:duration={clip.duration_seconds},"
                       f"setpts=PTS-STARTPTS,{fit},fps={request.fps},setsar=1,format=yuv420p[v{index}]")
    inputs = "".join(f"[v{i}]" for i in range(len(sources)))
    filters.append(f"{inputs}concat=n={len(sources)}:v=1:a=0[out]")
    return command + ["-filter_complex", ";".join(filters), "-map", "[out]", "-an", "-c:v", "libx264",
                      "-threads", "2", "-pix_fmt", "yuv420p", "-r", str(request.fps), "-t",
                      str(sum(c.duration_seconds for c in request.clips)), "-fs", str(MAX_ASSET_BYTES), str(target)]


async def _qualify(path: Path, request: MaterialsRequest) -> dict:
    """Require full decode, exact dimensions and frame-tolerant declared total duration."""
    artifact = {"path": str(path), **file_pin(path, MAX_ASSET_BYTES)}
    artifact["qualification"] = await qualify_render(artifact, request.resolution)
    expected = sum(c.duration_seconds for c in request.clips)
    if abs(artifact["qualification"]["media"]["duration_seconds"] - expected) > 1 / request.fps:
        raise ValueError("Material output duration differs from the ordered recipe")
    return artifact


async def _assemble(project: Path, request: MaterialsRequest) -> dict:
    """Hold existing project admission across snapshots, codec work and atomic publication."""
    with plan_transaction(project, create=True):
        receipts = [source_receipt(project, clip, request.principal) for clip in request.clips]
        if sum(r["size_bytes"] for r in receipts) > 128 * 1024 * 1024:
            raise ValueError("Material assembly inputs exceed128MiB")
        executables = codec_executables()
        recipe = {"version": 1, "request": request.model_dump(mode="json"),
                  "sources": receipts, "executables": executables, "audio": "silent"}
        key = digest(recipe)
        manifest = load_manifest(project)
        if key in manifest["outputs"]:
            row = manifest["outputs"][key]
            if row["path"] != f"materials-output-{key}.mp4" or row["recipe"] != recipe:
                raise ValueError("Cached material path or recipe changed")
            artifact = await _qualify(confined_path(project, row["path"]), request)
            if (artifact["sha256"] != row["sha256"] or artifact["size_bytes"] != row["size_bytes"]
                    or row["recipe"] != recipe):
                raise ValueError("Cached material output or recipe changed")
            _recheck(project, request, receipts, executables)
            return {"success": True, "cached": True, "cache_key": key, **row,
                    "qualification": artifact["qualification"]}
        return await _render_new(project, request, receipts, executables, recipe, key, manifest)


async def _render_new(project: Path, request: MaterialsRequest, receipts: list, executables: dict,
                      recipe: dict, key: str, manifest: dict) -> dict:
    """Keep intermediate media private and publish only after every final recheck."""
    with tempfile.TemporaryDirectory(prefix="vrm-materials-") as directory:
        work = Path(directory)
        sources = []
        for index, clip in enumerate(request.clips):
            suffix = Path(clip.source.path).suffix.lower() if clip.kind == "image" else ".mp4"
            if suffix not in {".mp4", ".png", ".jpg", ".jpeg"}:
                raise ValueError("Material images requirePNG/JPEG; video inputs requireMP4")
            source = work / f"input-{index}{suffix}"
            snapshot(project, clip.source, source)
            sources.append(source)
        target = work / "output.mp4"
        command = render_recipe(request, sources, target, executables["ffmpeg"]["path"])
        stdout, stderr = await run_media_process(command, 15.0)
        if stdout or stderr:
            raise ValueError("Material renderer reported media errors")
        artifact = await _qualify(target, request)
        _recheck(project, request, receipts, executables)
        name = f"materials-output-{key}.mp4"
        publish(project, target, name, artifact["sha256"])
        row = {"path": name, "sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"],
               "recipe": recipe, "command": command, "qualification": artifact["qualification"],
               "factual_success": False, "semantic_support": "not_verified"}
        manifest["outputs"][key] = row
        try:
            save_manifest(project, manifest)
        except BaseException as error:
            discard_published(project, name, artifact["sha256"], error)
            raise
        return {"success": True, "cached": False, "cache_key": key, **row}


def _recheck(project: Path, request: MaterialsRequest, receipts: list, executables: dict) -> None:
    """Refuse source, rights or codec changes before success, including cache hits."""
    if [source_receipt(project, c, request.principal) for c in request.clips] != receipts:
        raise ValueError("Material provenance changed during assembly")
    if codec_executables() != executables:
        raise ValueError("Material codec executable changed during assembly")


async def assemble_materials(project_id: str, request: MaterialsRequest) -> dict:
    """Assemble explicitly ordered project materials under a90second outer deadline."""
    return await asyncio.wait_for(_assemble(project_directory(project_id), request), timeout=90)
