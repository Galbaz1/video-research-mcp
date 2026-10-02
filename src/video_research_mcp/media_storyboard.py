"""Bounded storyboard pixels with burned actual source clocks and exact manifests."""

import hashlib
import io
import math
from pathlib import Path

from .image_manifest import write_manifest
from .image_preprocessing import check_worker, image_worker, save_artifact
from .media_frames import _source_clock, sample_frames
from .media_image_read import MAX_ARTIFACT_BYTES, MAX_OUTPUT_PIXELS, geometry
from .media_local_io import _open_regular
from .media_probe import probe_snapshot
from .media_snapshot import copy_hash, snapshot
from .models.scene_assets import StoryboardRequest
from .native_media_results import native_operation


def timestamp(seconds):
    """Format the measured source-relative presentation point to milliseconds."""
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _compose(frames, columns, directory, cancelled, deadline):
    """Draw bounded numeric labels using the separately cleared builtin Pillow font."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=12)
    labels = [timestamp(frame["actual_seconds"]) for frame in frames]
    bounds = [font.getbbox(label) for label in labels]
    width = max(max(f["width"] for f in frames), max(b[2] - b[0] for b in bounds) + 8)
    image_height = max(f["height"] for f in frames)
    label_height = max(b[3] - b[1] for b in bounds) + 8
    height, rows = image_height + label_height, math.ceil(len(frames) / columns)
    pixels = width * columns * height * rows + sum(f["width"] * f["height"] for f in frames)
    if pixels > MAX_OUTPUT_PIXELS:
        raise ValueError("Storyboard frames and labeled canvas exceed the aggregate pixel budget")
    image = Image.new("RGB", (width * columns, height * rows), "black")
    tiles = []
    try:
        draw = ImageDraw.Draw(image)
        for index, (frame, label, glyph) in enumerate(zip(frames, labels, bounds)):
            check_worker(cancelled, deadline)
            path = Path(frame["path"])
            with _open_regular(path) as reader:
                data = reader.read(MAX_ARTIFACT_BYTES + 1)
            if len(data) != frame["bytes"] or hashlib.sha256(data).hexdigest() != frame["sha256"]:
                raise ValueError("Storyboard frame changed before composition")
            x, y = index % columns * width, index // columns * height
            with Image.open(io.BytesIO(data)) as tile:
                tile.load()
                if tile.size != (frame["width"], frame["height"]):
                    raise ValueError("Storyboard frame dimensions changed")
                with tile.convert("RGB") as rgb:
                    image.paste(rgb, (x, y))
            position = (x + 4 - glyph[0], y + image_height + 4 - glyph[1])
            draw.text(position, label, font=font, fill="white")
            tiles.append({"frame_index": index, "x": x, "y": y, "width": width,
                          "height": height, "actual_seconds": frame["actual_seconds"],
                          "original_pts": frame["original_pts"], "time_base": frame["time_base"],
                          "source_frame_sha256": frame["sha256"], "label": label,
                          "label_rectangle": [x, y + image_height, width, label_height]})
        remaining = MAX_ARTIFACT_BYTES - sum(f["bytes"] for f in frames)
        artifact = save_artifact(image, directory / "storyboard.png", "png", "white", 90,
                                 remaining, cancelled, deadline)
        return artifact, tiles
    finally:
        image.close()


async def create_storyboard(request: StoryboardRequest) -> dict:
    """Sample measured frames and publish literal source-clock labels without inference."""
    request = StoryboardRequest.model_validate(request)
    async with native_operation() as generated, snapshot(request.file_path, request.expected_source_sha256) as owned:
        source = await probe_snapshot(owned)
        duration, _ = _source_clock(source)
        end = duration if request.end_seconds is None else request.end_seconds
        start = request.start_seconds
        if not 0 <= start < end <= duration or end - start > 120:
            raise ValueError("Storyboard interval must lie in the source and be at most 120 seconds")
        count = request.columns * request.rows
        pixels = min(request.max_pixels, (MAX_ARTIFACT_BYTES - (count + 1) * 65536 - 262144) // (8 * count))
        width, height, _ = geometry(source, pixels, None)
        reserved_pixels = count * (max(width, 128) * (height + 32) + width * height)
        if reserved_pixels > MAX_OUTPUT_PIXELS:
            raise ValueError("Storyboard frames and labeled canvas exceed the aggregate pixel budget")
        sampled = await sample_frames(str(owned.path), start_seconds=start, end_seconds=end,
                                      fps=min(30, count / (end - start)), max_frames=count, max_pixels=pixels,
                                      expected_source_sha256=owned.sha256)
        generated.append(sampled)
        if sampled["source"]["sha256"] != owned.sha256:
            raise ValueError("Storyboard sampled source commitment differs from the verified original")
        frames = sampled["frames"]
        artifact, tiles = await image_worker(_compose, frames, min(request.columns, len(frames)),
                                             owned.directory, deadline=owned.deadline)
        for frame in frames:
            if await copy_hash(Path(frame["path"])) != (frame["sha256"], frame["bytes"]):
                raise ValueError("Storyboard source frame changed during composition")
        artifacts = [{**f, "mime": "image/png", "role": "sampled_source_frame"} for f in frames]
        artifacts.append({**artifact, "role": "timestamped_storyboard"})
        metadata = {"source": source, "operation": "timestamped_storyboard", "artifact": artifacts[-1],
                    "artifacts": artifacts, "frames": frames, "tiles": tiles,
                    "coverage": sampled["coverage"], "status": sampled["status"],
                    "provenance": "extracted_source_frames_with_literal_timestamp_annotations",
                    "labels": {"basis": "actual_source_relative_presentation_seconds_not_window_relative",
                               "precision": "nearest_millisecond", "font": "installed_Pillow_builtin_Aileron",
                               "burned": True, "human_verified": False},
                    "limits": {"requested_tiles": count, "returned_tiles": len(frames),
                               "max_frame_pixels": pixels, "max_output_pixels": MAX_OUTPUT_PIXELS,
                               "max_artifact_bytes": MAX_ARTIFACT_BYTES, "provider_calls": 0}}
        await owned.verify()
        metadata["manifest"] = await write_manifest(metadata, owned.directory)
        generated.append(metadata)
        return metadata
