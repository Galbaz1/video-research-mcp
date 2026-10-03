"""Authored raster cells and source-derived primitives with complete frame populations."""

import hashlib
import io

from .education_domain import BACKGROUND, CAPTION_BOX, DIAGRAM, FOREGROUND, caption_lines, primitives
from .education_glyphs import cells
from .education_timing import frame_schedule, legacy_timeline
from .image_preprocessing import check_worker, save_artifact

TITLES = ["RIGHT TRIANGLE", "INPUT REFLECTION SQUARE", "CLOSED SERIES CIRCUIT"]


def raster(spec, index):
    """Draw actual source geometry and captions without importing or selecting a font."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ImportError("Pillow is required; install video-research-mcp[images] for the explicit lesson workflow") from exc
    image = Image.new("RGB", (640, 360), BACKGROUND)
    draw = ImageDraw.Draw(image)
    scene, caption = spec.storyboard.scenes[index], spec.script.captions[index]
    for primitive in primitives(scene):
        draw.line([tuple(p) for p in primitive["points"]], fill=DIAGRAM, width=3)
    draw.rectangle(tuple(CAPTION_BOX), outline=DIAGRAM, width=2)
    labels = [(TITLES[index], 48, 16), (scene.equation, 48, 36)]
    labels.extend((line, 40, 294 + i * 20) for i, line in enumerate(caption_lines(caption.text)))
    if index == 0:
        labels.extend([("A", 60, 224), ("B", 330, 224), ("C", 330, 60)])
    for text, x, y in labels:
        for left, top, width, height in cells(text, x, y):
            draw.rectangle((left, top, left + width - 1, top + height - 1), fill=FOREGROUND)
    return image


def authored_frames(spec, directory, cancelled, deadline, *, timeline=None):
    """Write every scheduled PNG and its full encoded/pixel identities exclusively."""
    timeline = legacy_timeline() if timeline is None else timeline
    frames, remaining = [], 8388608
    for index in range(3):
        check_worker(cancelled, deadline)
        with raster(spec, index) as image:
            digest = hashlib.sha256(image.tobytes()).hexdigest()
            for number, scene_index in frame_schedule(timeline):
                if scene_index != index:
                    continue
                path = directory / f"frame-{number:03}.png"
                artifact = save_artifact(image, path, "png", BACKGROUND, 100, remaining, cancelled, deadline)
                remaining -= artifact["bytes"]
                frames.append({**artifact, "path": path.name, "frame_index": number,
                               "scene_id": spec.storyboard.scenes[index].id, "timeline_seconds": number / 12,
                               "pixel_sha256": digest, "pixel_format": "rgb24"})
                if spec.schema_version == 2:
                    frames[-1]["timeline_sample"] = number * 4000
    return frames


def expected_pixels(spec):
    """Recompute each source-derived scene independently of any editable artifact receipt."""
    output = []
    for index in range(3):
        with raster(spec, index) as image:
            output.append(hashlib.sha256(image.tobytes()).hexdigest())
    return output


def png_pixels(data):
    """Reopen committed PNG bytes rather than accepting recorded pixel hashes as measurements."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ImportError("Pillow is required; install video-research-mcp[images] for lesson readback") from exc
    with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
        if image.size != (640, 360) or image.mode != "RGB" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Lesson frame is not a single640x360 RGB PNG")
        return hashlib.sha256(image.tobytes()).hexdigest()
