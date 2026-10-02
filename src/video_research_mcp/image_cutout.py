"""Bounded polygon holes and conservative connected-background alpha cutouts."""

import hashlib
import math
from array import array

from .image_annotations import source_point
from .image_preprocessing import IDENTITY, check_worker


def _neighbors(index, width, height):
    """Yield only the four connected neighbors within the prepared pixel grid."""
    x, y = index % width, index // width
    if x:
        yield index - 1
    if x + 1 < width:
        yield index + 1
    if y:
        yield index - width
    if y + 1 < height:
        yield index + width


def _flood(image, seed, tolerance, cancelled, deadline):
    """Complement the seed-connected L1 RGB background without removing components."""
    from PIL import Image

    if image.getchannel("A").getextrema() != (255, 255):
        raise ValueError("Seeded flood requires an opaque image; use explicit polygons for transparency")
    width, height = image.size
    x, y = seed
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError("Flood seed must be inside the output pixel grid")
    values = image.tobytes()
    start = math.floor(y) * width + math.floor(x)
    reference = values[start * 4:start * 4 + 3]
    visited, queue = bytearray(width * height), array("I", [start])
    visited[start] = 1
    head = 0
    while head < len(queue):
        if head % 4096 == 0:
            check_worker(cancelled, deadline)
        index = queue[head]
        head += 1
        for neighbor in _neighbors(index, width, height):
            if visited[neighbor]:
                continue
            difference = sum(abs(values[neighbor * 4 + c] - reference[c]) for c in range(3))
            visited[neighbor] = 1 if difference <= tolerance else 2
            if difference <= tolerance:
                queue.append(neighbor)
    return Image.frombytes("L", image.size, bytes(0 if v == 1 else 255 for v in visited))


def _component_stats(values, width, height, foreground, cancelled, deadline):
    """Count regions and enclosed pixels with one bounded visited/queue allocation."""
    visited = bytearray(width * height)
    count, enclosed = 0, 0
    for start in range(len(values)):
        if start % 4096 == 0:
            check_worker(cancelled, deadline)
        if visited[start] or bool(values[start]) != foreground:
            continue
        count += 1
        queue, head, border = array("I", [start]), 0, False
        visited[start] = 1
        while head < len(queue):
            if head % 4096 == 0:
                check_worker(cancelled, deadline)
            index = queue[head]
            head += 1
            x, y = index % width, index // width
            border |= x in {0, width - 1} or y in {0, height - 1}
            for neighbor in _neighbors(index, width, height):
                if not visited[neighbor] and bool(values[neighbor]) == foreground:
                    visited[neighbor] = 1
                    queue.append(neighbor)
        if not border:
            enclosed += len(queue)
    return count, enclosed


def _metrics(mask, cancelled, deadline):
    """Measure actual alpha coverage and preserve conservative ambiguity warnings."""
    width, height = mask.size
    values = mask.tobytes()
    pixels = sum(bool(v) for v in values)
    components, _ = _component_stats(values, width, height, True, cancelled, deadline)
    _, holes = _component_stats(values, width, height, False, cancelled, deadline)
    border = [values[y * width + x] for y in range(height) for x in range(width)
              if x in {0, width - 1} or y in {0, height - 1}]
    ratio = sum(bool(v) for v in border) / len(border)
    warnings = []
    coverage = pixels / len(values)
    if coverage >= 0.95 or coverage <= 0.02:
        warnings.append("Cutout coverage is extreme; foreground/background selection may be ambiguous")
    if ratio >= 0.9:
        warnings.append("Cutout foreground spans the image border; background seed may identify foreground")
    if components > 4:
        warnings.append("Cutout contains more than four foreground components; all components are retained")
    if holes > max(1, pixels * 0.01):
        warnings.append("Cutout has enclosed alpha holes; exact alpha mask is required for readback")
    return {"coverage_fraction": coverage, "border_inside_fraction": ratio,
            "foreground_components": components, "enclosed_hole_pixels": holes}, warnings


def _polygon(image, spec, source, matrix):
    """Rasterize one outer ring and explicitly subtract all supplied hole rings."""
    from PIL import Image, ImageDraw

    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    for index, ring in enumerate(spec.rings):
        points = [source_point(point, spec.space, source, matrix, image.size) for point in ring]
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
        if not area:
            mask.close()
            raise ValueError("Polygon ring has no area")
        draw.polygon(points, fill=255 if index == 0 else 0)
    return mask


def cutout_image(image, spec, source, matrix, cancelled, deadline):
    """Return exact alpha, trim mapping and honest seeded/polygon boundary metrics."""
    from PIL import ImageChops

    check_worker(cancelled, deadline)
    if image.width * image.height > 1_000_000:
        raise ValueError("Cutout exceeds its 1 megapixel work limit")
    if spec.method == "polygon":
        mask = _polygon(image, spec, source, matrix)
    else:
        seed = source_point(spec.seed, spec.space, source, matrix, image.size)
        mask = _flood(image, seed, spec.tolerance, cancelled, deadline)
    combined = ImageChops.multiply(mask, image.getchannel("A"))
    mask.close()
    mask = combined
    bbox = mask.getbbox()
    if bbox is None:
        mask.close()
        raise ValueError("Cutout has no foreground; use explicit polygons for this difficult background")
    metrics, warnings = _metrics(mask, cancelled, deadline)
    box = bbox if spec.crop_to_bbox else (0, 0, image.width, image.height)
    output = image.crop(box)
    cropped = mask.crop(box)
    mask.close()
    output.putalpha(cropped)
    shift = [[1, 0, -box[0]], [0, 1, -box[1]], [0, 0, 1]] if spec.crop_to_bbox else IDENTITY
    details = {**metrics, "method": spec.method, "bbox_before_trim": list(bbox),
               "crop_offset": list(box[:2]), "mask_stage": "cutout_alpha_before_annotations",
               "alpha_bytes_sha256": hashlib.sha256(cropped.tobytes()).hexdigest(),
               "algorithm": "outer_minus_explicit_hole_rings" if spec.method == "polygon" else "four_connected_seed_L1_RGB_complement",
               "polygon_rasterization": "Pillow_integer_inclusive_fill", "polygon_replay_verified": False,
               "morphology_or_component_removal": False, "feathering": False,
               "semantic_object_boundary_verified": False}
    if spec.method == "flood":
        warnings.append("Seeded background flood is a color-connectivity estimate; object boundaries and enclosed background are unverified")
    check_worker(cancelled, deadline)
    return output, cropped, shift, details, warnings
