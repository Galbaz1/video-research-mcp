"""Five bounded source-grid annotations and verified padded closeup geometry."""

import math

from .image_preprocessing import map_point


def source_point(point, space, source, matrix, size):
    """Map a valid original oriented corner into the current edited pixel grid."""
    x, y = point
    width, height = source["oriented_width"], source["oriented_height"]
    if space == "normalized1000":
        x, y = x * width / 1000, y * height / 1000
    if not 0 <= x <= width or not 0 <= y <= height:
        raise ValueError("Annotation/cutout coordinate exceeds the oriented source grid")
    x, y = map_point(matrix, x, y)
    if not -1e-9 <= x <= size[0] + 1e-9 or not -1e-9 <= y <= size[1] + 1e-9:
        raise ValueError("Annotation/cutout coordinate is outside the cropped output")
    return max(0, min(x, size[0])), max(0, min(y, size[1]))


def _text(draw, point, text, font, color, size):
    """Reject clipped literal text using the installed font's actual glyph bounds."""
    bounds = draw.textbbox(point, text, font=font)
    if min(bounds[:2]) < 0 or bounds[2] > size[0] or bounds[3] > size[1]:
        raise ValueError("Annotation text exceeds the output pixel grid")
    draw.text(point, text, fill=color, font=font)


def _arrow(draw, points, color, width, size):
    """Draw a bounded line and two finite head segments in output pixels."""
    start, end = points
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = min(max(6, width * 4), math.dist(start, end) / 2)
    heads = [(end[0] - length * math.cos(angle + offset),
              end[1] - length * math.sin(angle + offset)) for offset in (-0.5, 0.5)]
    if any(not 0 <= x <= size[0] or not 0 <= y <= size[1] for x, y in heads):
        raise ValueError("Annotation arrowhead exceeds the output pixel grid")
    draw.line([start, end], fill=color, width=width)
    for head in heads:
        draw.line([end, head], fill=color, width=width)


def _number(draw, point, annotation, font, size):
    """Size one numeric badge from measured builtin glyph geometry."""
    bounds = draw.textbbox((0, 0), annotation.text, font=font)
    radius = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) / 2 + 4
    x, y = point
    if x - radius < 0 or y - radius < 0 or x + radius > size[0] or y + radius > size[1]:
        raise ValueError("Annotation number badge exceeds the output pixel grid")
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=annotation.color)
    draw.text(point, annotation.text, font=font, fill="white", anchor="mm")


def _closeup(points, padding, size):
    """Reserve a padded output box only for marks covering at most forty percent."""
    (x1, y1), (x2, y2) = points
    if (x2 - x1) * (y2 - y1) > size[0] * size[1] * 0.4:
        return None
    padding = 0.1 if padding is None else padding
    px, py = (x2 - x1) * padding, (y2 - y1) * padding
    return [max(0, math.floor(x1 - px)), max(0, math.floor(y1 - py)),
            min(size[0], math.ceil(x2 + px)), min(size[1], math.ceil(y2 + py))]


def _glyph_warning(text, font):
    """Detect replacement glyphs by the builtin font's known missing-glyph mask."""
    missing = font.getmask("\uffff")
    unsupported = []
    for character in text:
        if character.isspace():
            continue
        mask = font.getmask(character)
        if mask.size == missing.size and bytes(mask) == bytes(missing):
            unsupported.append(f"U+{ord(character):04X}")
    if unsupported:
        return "Builtin Aileron font has unsupported glyphs " + ",".join(sorted(set(unsupported))) + "; replacement glyphs are not literal text verification"
    return None


def annotate_image(image, annotations, source, matrix):
    """Draw all requested annotations using Pillow's installed builtin font."""
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(image)
    closeups, warnings = [], []
    for index, annotation in enumerate(annotations):
        coordinates = annotation.coordinates
        points = [source_point(coordinates[i:i + 2], annotation.space, source, matrix, image.size)
                  for i in range(0, len(coordinates), 2)]
        font = ImageFont.load_default(size=annotation.font_size)
        if annotation.kind in {"box", "circle"}:
            bounds = (*points[0], min(points[1][0], image.width - 1), min(points[1][1], image.height - 1))
            renderer = draw.rectangle if annotation.kind == "box" else draw.ellipse
            renderer(bounds, outline=annotation.color, width=annotation.width)
            if annotation.text:
                _text(draw, (points[0][0] + 2, points[0][1] + 2), annotation.text,
                      font, annotation.color, image.size)
            box = _closeup(points, annotation.closeup_padding, image.size)
            if box:
                closeups.append((index, box))
        elif annotation.kind == "arrow":
            _arrow(draw, points, annotation.color, annotation.width, image.size)
        elif annotation.kind == "number":
            _number(draw, points[0], annotation, font, image.size)
        else:
            _text(draw, points[0], annotation.text, font, annotation.color, image.size)
        if note := _glyph_warning(annotation.text, font):
            warnings.append(note)
    return closeups, sorted(set(warnings))
