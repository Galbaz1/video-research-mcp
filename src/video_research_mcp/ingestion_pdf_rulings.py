"""Source-bound measured ruling grids, separate from positioned-text content bounds."""

import math


def validate_rulings(records, source_sha, pages):
    """Require finite unrotated page geometry and unique top-level path occurrences."""
    if not isinstance(records, list) or len(records) > 4096:
        raise ValueError("Invalid measured ruling population")
    fields = {"page", "object_ordinal", "points", "source_pdf_sha256", "method", "clip_path_count"}
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError("Unknown ruling fields")
        number, ordinal = record["page"], record["object_ordinal"]
        if (type(number) is not int or type(ordinal) is not int or ordinal < 0
                or record["source_pdf_sha256"] != source_sha
                or type(record["clip_path_count"]) is not int or record["clip_path_count"] not in (-1, 0)
                or record["method"] != "pdfium-identity-stroked-line-v1"):
            raise ValueError("Invalid ruling identity/method")
        page, points = pages.get(number), record["points"]
        if (page is None or page["rotation_degrees"] != 0 or (number, ordinal) in seen
                or not isinstance(points, list) or len(points) != 4
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in points)):
            raise ValueError("Invalid ruling page/occurrence/coordinates")
        if not all(0 <= points[i] <= page[key] for i, key in (
                (0, "page_width"), (1, "page_height"), (2, "page_width"), (3, "page_height"))):
            raise ValueError("Ruling outside measured page")
        seen.add((number, ordinal))
    return seen


def attach_rulings(tables, records, source_sha, pages):
    """Add a measured region only for a complete uniquely bound grid; keep content cells."""
    validate_rulings(records, source_sha, pages)
    for table in tables:
        table["content_bbox"], table["bbox_role"] = table["bbox"], "text_content_bounds"
        page = pages.get(table["page"])
        selected = [r for r in records if r["page"] == table["page"]]
        if (page is None or page["rotation_degrees"] != 0
                or any(table[k] != page[k] for k in ("page_width", "page_height"))
                or table["source_pdf_sha256"] != source_sha
                or sum(t["page"] == table["page"] for t in tables) != 1):
            table["ruling_limitation"] = "Measured region abstained: page geometry/source or table ambiguity"
            continue
        region = grid_region(table, selected)
        if region is None:
            table["ruling_limitation"] = "Measured region abstained: incomplete or ambiguous native grid"
        else:
            table.update(bbox=region, bbox_role="measured_ruling_centerline_region",
                         ruling_method="pdfium-complete-axis-aligned-grid-v1",
                         ruling_clip_path_counts=[r["clip_path_count"] for r in selected],
                         ruling_limitations="Centerlines measured, not painted border extent; stroke color/dash visibility unknown; native clip count -1 semantics require Root qualification",
                         ruling_object_ordinals=[r["object_ordinal"] for r in selected])
    return tables


def grid_region(table, records):
    """Require all borders/separators and one indexed content cell in every grid band."""
    rows, columns = table["rows"], table["columns"]
    if type(rows) is not int or type(columns) is not int or not (3 <= rows <= 4096 and 2 <= columns <= 8):
        return None
    cells, lines = table["cells"], [r["points"] for r in records]
    if len(lines) != rows + columns + 2 or len(cells) != rows * columns:
        return None
    horizontal = [sorted((x0, x1)) + [y0] for x0, y0, x1, y1 in lines if y0 == y1 and x0 != x1]
    vertical = [sorted((y0, y1)) + [x0] for x0, y0, x1, y1 in lines if x0 == x1 and y0 != y1]
    if len(horizontal) != rows + 1 or len(vertical) != columns + 1:
        return None
    xs = sorted({v[2] for v in vertical})
    ys = sorted({h[2] for h in horizontal}, reverse=True)
    if len(xs) != columns + 1 or len(ys) != rows + 1:
        return None
    if any(h[:2] != [xs[0], xs[-1]] for h in horizontal) or any(v[:2] != [ys[-1], ys[0]] for v in vertical):
        return None
    width, height = table["page_width"], table["page_height"]
    if (any(type(v) not in (float, int) or not math.isfinite(v) for v in (width, height))
            or not (0 <= xs[0] < xs[-1] <= width and 0 <= ys[-1] < ys[0] <= height)):
        return None
    seen = set()
    for cell in cells:
        r, c = cell["row"], cell["column"]
        box = cell["bbox"]
        if (type(r) is not int or type(c) is not int or not (0 <= r < rows and 0 <= c < columns)
                or (r, c) in seen or len(box) != 4
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in box)):
            return None
        x0, y0, x1, y1 = box
        if not (xs[c] <= x0 < x1 <= xs[c+1] and height-ys[r] <= y0 < y1 <= height-ys[r+1]):
            return None
        seen.add((r, c))
    return [xs[0], height-ys[0], xs[-1], height-ys[-1]]
