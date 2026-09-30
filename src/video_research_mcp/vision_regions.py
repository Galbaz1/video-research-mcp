"""Strict model-region mapping and exact original-source crop exports."""

import math

from .image_edit import edit_image
from .image_manifest import json_digest
from .image_preprocessing import inverse, map_point
from .models.image_edit import CropRegion, ImageEditRequest
from .models.vision import VisionAnswer


def mapped_region(region, preparation):
    """Preserve inferred geometry alongside measured preparation transforms."""
    artifact = preparation["artifact"]
    x, y, a, b = region.bbox
    points = [(x * artifact["width"] / 1000, y * artifact["height"] / 1000),
              (a * artifact["width"] / 1000, y * artifact["height"] / 1000),
              (a * artifact["width"] / 1000, b * artifact["height"] / 1000),
              (x * artifact["width"] / 1000, b * artifact["height"] / 1000)]
    transforms = preparation["transforms"]
    oriented_matrix = inverse(transforms["oriented_to_output"])
    oriented = [map_point(oriented_matrix, *point) for point in points]
    stored = [map_point(transforms["output_to_source"], *point) for point in points]
    source = preparation["source"]
    left, top = math.floor(min(p[0] for p in oriented)), math.floor(min(p[1] for p in oriented))
    right = math.ceil(max(p[0] for p in oriented))
    bottom = math.ceil(max(p[1] for p in oriented))
    # Valid affine corners may differ from the integer image edge by machine epsilon.
    left, top = max(0, left), max(0, top)
    right, bottom = min(source["oriented_width"], right), min(source["oriented_height"], bottom)
    return {**region.model_dump(mode="json"), "coordinate_space": "prepared_normalized1000_xyxy",
            "prepared_corners": points, "original_oriented_corners": oriented,
            "original_stored_corners": stored, "original_crop_xywh": [left, top, right-left, bottom-top],
            "prepared_sha256": artifact["sha256"], "source_sha256": source["sha256"],
            "provenance": "model_inferred_region", "object_correctness_verified": False,
            "geometry_mapping_verified": True}


async def regions_and_crops(answer, request, prepared, generated):
    """Validate every region before producing any selected original-pixel crop."""
    validated = VisionAnswer.model_validate(answer)
    mapped = []
    for region in validated.regions:
        if region.source_index >= len(prepared) or request.sources[region.source_index].kind == "video":
            raise ValueError("Model region must identify one transmitted image or precise source frame")
        mapped.append(mapped_region(region, prepared[region.source_index]))
    for region in mapped:
        if not request.export_crops:
            continue
        source = request.sources[region["source_index"]]
        edit = ImageEditRequest(file_path=source.file_path,
                                expected_source_sha256=source.expected_source_sha256,
                                time_seconds=source.time_seconds,
                                crop=CropRegion(coordinates=tuple(region["original_crop_xywh"])))
        crop = await edit_image(edit)
        generated.append(crop)
        region["crop"] = crop
        region["crop_parent"] = {"prepared_sha256": region["prepared_sha256"],
                                 "inferred_region_sha256": json_digest({"bbox": region["bbox"]}),
                                 "source_sha256": region["source_sha256"],
                                 "pixel_extraction_verified": True,
                                 "object_correctness_verified": False}
    return mapped
