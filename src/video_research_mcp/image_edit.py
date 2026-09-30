"""Exact-source local image/frame editing with private artifacts and manifests."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

from .config import get_config
from .image_manifest import json_digest, write_manifest
from .image_preprocessing import (
    IDENTITY, MAX_ARTIFACT_BYTES, MAX_OUTPUT_PIXELS, MAX_STILL_BYTES, check_worker,
    crop_bounds, crop_resize, image_worker, inverse, load_oriented, multiply,
    orientation_matrix, save_artifact,
)
from .media_frames import frame_at
from .media_image_read import IMAGE_EXTENSIONS
from .media_local_io import _open_regular
from .media_probe import probe_snapshot
from .media_snapshot import checked_path, copy_hash, snapshot
from .models.image_edit import ImageArtifact, ImageEditRequest, ImageEditResult, ImageTransforms


async def _frame_input(owned, request):
    """Crop original video coordinates before native scale and retain actual PTS."""
    source = await probe_snapshot(owned)
    width, height = source["display_width"], source["display_height"]
    if not width or not height:
        raise ValueError("Video edit requires a supported square-pixel visual stream")
    crop = crop_bounds(width, height, request.crop)
    result = await frame_at(str(owned.path), time_seconds=request.time_seconds,
                            max_pixels=request.max_pixels, crop_box=crop,
                            expected_source_sha256=owned.sha256)
    frame = result["frames"][0]
    decoded = Path(frame["path"])
    target = owned.directory / "decoded.png"
    try:
        if await copy_hash(decoded, target) != (frame["sha256"], frame["bytes"]):
            raise ValueError("Prepared native frame identity changed")
    finally:
        shutil.rmtree(decoded.parent)
    rotation = int(source["rotation_degrees"]) % 360
    matrix = orientation_matrix({0: 1, 90: 8, 180: 3, 270: 6}[rotation],
                                source["stored_width"], source["stored_height"])
    x, y, w, h = crop
    scale = [[frame["width"] / w, 0, -x * frame["width"] / w],
             [0, frame["height"] / h, -y * frame["height"] / h], [0, 0, 1]]
    source.update(path=str(owned.original), oriented_width=width, oriented_height=height,
                  exif_orientation=None, selection="precise_source_point", native_crop_xywh=crop,
                  prepared_width=frame["width"], prepared_height=frame["height"])
    clock = {k: frame[k] for k in ("requested_seconds", "actual_seconds", "original_pts",
                                  "time_base", "selection_method", "approximate", "delta_seconds")}
    clock["decoded_frame_sha256"] = frame["sha256"]
    clock.update(decoded_width=frame["width"], decoded_height=frame["height"])
    return target, source, matrix, scale, clock


def _publish(image, mask, closeups, matrix, request, directory, cancelled, deadline):
    """Preflight all output pixels, then encode each closeup sequentially."""
    artifacts, total = [], 0
    pixels = image.width * image.height + (mask.width * mask.height if mask is not None else 0)
    pixels += sum((box[2] - box[0]) * (box[3] - box[1]) for _, box in closeups)
    if pixels > MAX_OUTPUT_PIXELS:
        raise ValueError("Image artifacts exceed the 16 megapixel aggregate limit")
    jobs = [("image", None, None)] + ([("alpha_mask", None, None)] if mask is not None else [])
    jobs.extend(("closeup", index, box) for index, box in closeups)
    for index, (role, annotation, box) in enumerate(jobs):
        visual = image.crop(tuple(box)) if box else mask if role == "alpha_mask" else image
        try:
            fmt = "png" if role == "alpha_mask" else request.output_format
            extension = "jpg" if fmt == "jpeg" else fmt
            path = directory / f"{role}-{index:02d}.{extension}"
            artifact = save_artifact(visual, path, fmt, request.jpeg_background,
                                     request.quality, MAX_ARTIFACT_BYTES - total, cancelled, deadline)
            total += artifact["bytes"]
            offset = [[1, 0, box[0]], [0, 1, box[1]], [0, 0, 1]] if box else IDENTITY
            artifact.update(role=role, annotation_index=annotation, output_box=box,
                            output_to_source=multiply(inverse(matrix), offset))
            artifacts.append(ImageArtifact.model_validate(artifact).model_dump(mode="json"))
        finally:
            if role == "closeup":
                visual.close()
    return artifacts


def _render(path, request, original, directory, frame_info, cancelled, deadline):
    """Run one bounded source-grid edit chain in the owned joined worker."""
    image, metadata, stored_matrix = load_oriented(path, request.include_exif, cancelled, deadline)
    source = {"path": str(original.original), "sha256": original.sha256, "bytes": original.size,
              "source_revision": "sha256:" + original.sha256, **metadata}
    initial, frame = IDENTITY, None
    if frame_info:
        source, stored_matrix, initial, frame = frame_info
        source.update(profile_handling="stripped_not_color_managed",
                      metadata_handling="stripped_after_native_rotation", animation_traversed=False)
    visual_request = request.model_copy(update={"crop": None}) if frame_info else request
    edited, resizing, crop = crop_resize(image, visual_request)
    image.close()
    matrix = multiply(resizing, initial)
    warnings, closeups, cutout, mask = [], [], None, None
    try:
        if request.cutout:
            from .image_cutout import cutout_image
            previous = edited
            edited, mask, shift, cutout, notes = cutout_image(
                edited, request.cutout, source, matrix, cancelled, deadline)
            previous.close()
            matrix = multiply(shift, matrix)
            warnings.extend(notes)
        if request.annotations:
            from .image_annotations import annotate_image
            closeups, notes = annotate_image(edited, request.annotations, source, matrix)
            warnings.extend(notes)
        if request.output_format in {"jpeg", "bmp"} and edited.getchannel("A").getextrema() != (255, 255):
            warnings.append(f"{request.output_format.upper()} transparency flattened onto the explicit jpeg_background")
        if request.output_format == "gif":
            warnings.append("GIF quantizes color to a 255-color palette and alpha to one bit at threshold 128")
        if source.get("icc_profile_present"):
            warnings.append("Embedded ICC profile stripped; color appearance is not profile-verified")
        if request.include_exif and source.get("exif_gps_present"):
            warnings.append("Included EXIF may contain GPS/private location metadata; nested GPS IFD is not traversed")
        artifacts = _publish(edited, mask, closeups, multiply(matrix, stored_matrix),
                             request, directory, cancelled, deadline)
        if cutout:
            cutout.update(mask_sha256=artifacts[1]["sha256"], mask_path=artifacts[1]["path"])
    finally:
        edited.close()
        if mask:
            mask.close()
    transforms = {"stored_to_oriented": stored_matrix, "oriented_to_output": matrix,
                  "source_to_output": multiply(matrix, stored_matrix),
                  "output_to_source": inverse(multiply(matrix, stored_matrix))}
    transforms = ImageTransforms.model_validate(transforms).model_dump(mode="json")
    check_worker(cancelled, deadline)
    return source, frame, artifacts, transforms, warnings, cutout, crop


def _result(request, rendered):
    """Commit actual source/clock/transform/artifact bytes without inferred content."""
    import PIL

    source, frame, artifacts, transforms, warnings, cutout, crop = rendered
    request_json = request.model_dump(mode="json")
    binding = {"request_sha256": json_digest(request_json), "source_sha256": source["sha256"],
               "frame": frame, "transforms": transforms,
               "artifact_sha256": [a["sha256"] for a in artifacts], "engine": "pillow_local_v1"}
    return {"status": "complete", "source": source, "frame": frame,
            "artifact": artifacts[0], "artifacts": artifacts, "transforms": transforms,
            "request": request_json, "request_sha256": binding["request_sha256"],
            "operation_sha256": json_digest(binding), "warnings": warnings, "cutout": cutout,
            "provenance": {"engine": "pillow_local_v1", "pillow_version": PIL.__version__,
                           "source_kind": "video_frame" if frame else "still_first_page",
                           "output_class": "source_annotated_image" if request.annotations else "source_cutout" if cutout else "extracted_source_frame" if frame else "prepared_source_image",
                           "origin": "source_derived", "newly_generated_media": False,
                           "original_source_synthetic_status": "unverified",
                           "annotation_font": "Pillow_builtin_Aileron_limited_subset",
                           "annotation_glyph_check": "known_missing_glyph_mask_comparison",
                           "crop_xywh": source.get("native_crop_xywh", crop),
                           "normalized_crop_rounding": "floor_left_top_ceil_right_bottom",
                           "coordinate_convention": "homogeneous_top_left_pixel_corners",
                           "order": "exif_or_native_rotation,crop,resize,cutout,annotations,encode",
                           "color_management_verified": False, "inference_used": False},
            "limits": {"max_still_source_bytes": MAX_STILL_BYTES, "max_decoded_pixels": 8000000,
                       "max_output_pixels": request.max_pixels, "max_aggregate_pixels": MAX_OUTPUT_PIXELS,
                       "max_artifact_bytes": MAX_ARTIFACT_BYTES, "max_annotations": 32,
                       "max_text_utf8_bytes": 1024, "process_rss_bound": None,
                       "animation_traversed": False, "multipage_traversed": False}}


async def edit_image(request: ImageEditRequest) -> dict:
    """Publish bounded edited bytes only after original-source identity readback."""
    request = ImageEditRequest.model_validate(request)
    original = checked_path(request.file_path)
    still = original.suffix.lower() in IMAGE_EXTENSIONS
    if still and request.time_seconds is not None:
        raise ValueError("Still image edits do not accept video timestamps")
    if not still and request.time_seconds is None:
        raise ValueError("Video image edits require a precise time_seconds")
    if still:
        with _open_regular(original) as reader:
            if os.fstat(reader.fileno()).st_size > MAX_STILL_BYTES:
                raise ValueError("Still image exceeds the 16 MiB source byte limit")
    timeout = get_config().media_acquire_timeout_seconds
    async with asyncio.timeout(timeout):
        deadline = time.monotonic() + timeout
        async with snapshot(str(original), request.expected_source_sha256) as owned:
            path, frame_info = owned.path, None
            if not still:
                path, source, matrix, scale, frame = await _frame_input(owned, request)
                frame_info = source, matrix, scale, frame
            rendered = await image_worker(_render, path, request, owned, owned.directory,
                                           frame_info, deadline=deadline)
            result = _result(request, rendered)
            if path != owned.path:
                path.unlink()
            result["manifest"] = await write_manifest(result, owned.directory)
            result = ImageEditResult.model_validate(result).model_dump(mode="json")
        return result
