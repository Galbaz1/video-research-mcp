"""Exact source-to-shot clocks, declared beat distances and font-free contact evidence."""

import hashlib
import io
import math

from .audio_dsp_native import read_png
from .footage_edit_native import input_command
from .image_preprocessing import check_worker, image_worker, save_artifact
from .media_local_io import _open_regular
from .media_snapshot import checked_path


def beat_report(plan):
    """Measure cut distances to caller-declared grids without inferring musical beats."""
    decision = plan.beats
    cuts = []
    for scene in plan.scenes[1:]:
        seconds = scene.timeline_start_seconds
        row = {"scene_id": scene.scene_id, "cut_seconds": seconds, "frame_distance": None}
        if decision.bpm is not None:
            period = 60 / decision.bpm
            index = round((seconds - decision.origin_seconds) / period)
            nearest = decision.origin_seconds + index * period
            row.update(nearest_declared_beat_seconds=nearest, frame_distance=abs(seconds - nearest) * plan.fps)
            if decision.mode == "declared" and row["frame_distance"] > decision.tolerance_frames + 1e-9:
                raise ValueError("Cut exceeds the declared beat-grid tolerance; choose explicit offbeat or revise the plan")
        cuts.append(row)
    return {"decision": decision.model_dump(), "cuts": cuts,
            "provenance": "caller_declared_grid_unverified" if decision.bpm else "explicit_no_inferred_music_grid",
            "measured_beat_detection": False, "music_added": False}


def scene_frames(scene, frames, hashes, fps):
    """Retain every actual original PTS; refuse implicit frame resampling or lost population."""
    count = round((scene.end_seconds - scene.start_seconds) * fps)
    if len(frames) != count or len(hashes) != count:
        raise ValueError("Selected source population differs from the declared timeline")
    result = []
    for index, (frame, digest) in enumerate(zip(frames, hashes)):
        local = frame["actual_seconds"] - scene.start_seconds
        if abs(local - index / fps) > 1e-5:
            raise ValueError("Source frame clock requires unsupported timeline resampling")
        result.append({**frame, "source_sha256": scene.expected_source_sha256, "scene_id": scene.scene_id,
                       "scene_frame_index": index, "timeline_seconds": scene.timeline_start_seconds + local,
                       "source_decoded_pixel_sha256": digest["pixel_sha256"], "source_decoded_pixel_format": "rgb24"})
    return result


def _sample_png(path, dimensions, expected_pixel_sha256, cancelled, deadline):
    """Rejoin the actual PNG RGB pixels to the exact decoded-frame hash receipt."""
    from PIL import Image

    artifact = read_png(path, dimensions, cancelled, deadline)
    with _open_regular(path) as reader:
        data = reader.read(8388609)
    if len(data) != artifact["bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
        raise ValueError("Sample PNG changed during pixel readback")
    with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
        image.load()
        rgb = image.convert("RGB")
        try:
            digest = hashlib.sha256(rgb.tobytes()).hexdigest()
        finally:
            rgb.close()
    if digest != expected_pixel_sha256:
        raise ValueError("Sample PNG pixels differ from the exact decoded scene frame")
    check_worker(cancelled, deadline)
    return {**artifact, "pixel_sha256": digest, "pixel_format": "rgb24"}


async def samples(scene, directory, work):
    """Extract first/middle/last decoded scene PNGs and bind them to full lineage records."""
    output, artifacts = scene["output"], []
    for index in sorted({0, output["frame_count"] // 2, output["frame_count"] - 1}):
        path = directory / f"{scene['scene_id']}-{index}.png"
        command = input_command(scene["artifact"]["path"]) + ["-map", "0:v:0", "-an", "-sn", "-dn",
                   "-vf", f"select='eq(n,{index + scene.get('output_frame_offset', 0)})',format=rgb24", "-frames:v", "1", "-fps_mode", "passthrough",
                   "-c:v", "png", "-threads", "1", "-f", "image2", "-fs", "8388608", "-n", str(path)]
        await work.run(command)
        try:
            artifact = await image_worker(_sample_png, path, (output["width"], output["height"]),
                                          scene["decoded_frames"][index]["pixel_sha256"], deadline=work.deadline)
        except ImportError as error:
            raise ImportError("Pillow is unavailable; install video-research-mcp[images] for footage contact previews") from error
        artifact.update(role="scene_sample", scene_id=scene["scene_id"], scene_frame_index=index,
                        source_frame=scene["frames"][index], sampled_video_sha256=scene["artifact"]["sha256"],
                        decoded_video_frame_index=index + scene.get("output_frame_offset", 0),
                        decoded_scene_seconds=output["decoded_frame_seconds"][index])
        artifacts.append(artifact)
    return artifacts


def _contacts(records, scene_ids, directory, duration, cancelled, deadline):
    """Compose bounded exact-readback thumbnails and bars without selecting any font."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise ImportError("Pillow is unavailable; install video-research-mcp[images] for footage contact previews") from error
    sheet = Image.new("RGB", (480, 120 * len(scene_ids)), (32, 32, 32))
    tiles = []
    try:
        for record in records:
            check_worker(cancelled, deadline)
            with _open_regular(checked_path(record["path"])) as reader:
                data = reader.read(8388609)
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Scene sample changed before contact composition")
            row = scene_ids.index(record["scene_id"])
            column = len([t for t in tiles if t["scene_id"] == record["scene_id"]])
            with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
                image.load()
                tile = image.convert("RGB")
                tile.thumbnail((160, 120), Image.Resampling.LANCZOS)
                x, y = column * 160, row * 120
                sheet.paste(tile, (x, y))
                tiles.append({"scene_id": record["scene_id"], "scene_frame_index": record["scene_frame_index"],
                              "source_frame": record["source_frame"], "sample_sha256": record["sha256"],
                              "x": x, "y": y, "width": tile.width, "height": tile.height})
                tile.close()
        artifact = save_artifact(sheet, directory / "contacts.png", "png", "#000000", 90, 8388608, cancelled, deadline)
    finally:
        sheet.close()
    bar = Image.new("RGB", (480, 48), (32, 32, 32))
    try:
        draw = ImageDraw.Draw(bar)
        for i, scene_id in enumerate(scene_ids):
            selected = [r for r in records if r["scene_id"] == scene_id]
            start = selected[0]["source_frame"]["timeline_seconds"]
            end = selected[-1]["source_frame"]["timeline_seconds"]
            draw.rectangle((math.floor(480 * start / duration), 8, min(479, math.ceil(480 * end / duration)), 39),
                           fill=((80 + i * 31) % 256, (140 + i * 23) % 256, (190 + i * 17) % 256))
        timeline = save_artifact(bar, directory / "timeline.png", "png", "#000000", 90, 8388608, cancelled, deadline)
    finally:
        bar.close()
    artifact.update(role="contact_sheet", tiles=tiles, thumbnail_resampling="Pillow_LANCZOS", fonts_used=[])
    timeline.update(role="timeline_preview", duration_seconds=duration, fonts_used=[],
                    coverage="sample_positions_only_full_timeline_is_in_the_ledger")
    return [artifact, timeline]


async def contacts(records, scenes, directory, work):
    """Join the owned Pillow worker before any directory cleanup or artifact promotion."""
    return await image_worker(_contacts, records, [s["scene_id"] for s in scenes], directory,
                              scenes[-1]["timeline_end_seconds"], deadline=work.deadline)
