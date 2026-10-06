"""Located Docling JSON derivatives, with the complete service response retained."""

import base64
import io
import math

from .image_preprocessing import check_worker
from .models.ingestion import IngestionSegment, ParsedSource
from .models.ingestion_location import IngestionLocation

LIMITATIONS = [
    "Docling text, tables, equations, page geometry and image extraction are service reports; accuracy is unverified",
    "Element references locate the normalized Docling document, not original byte offsets",
    "Table spans and every native provenance record remain in docling-response.json",
    "Embedded image bytes are parser derivatives; source pixel equivalence and page compositing are unverified",
    "Partial or multiple text provenance does not establish a whole-text box; cells need their own single-page box",
    "Finite zero-area or out-of-page element boxes are unknown; their raw provenance remains retained",
]


def number(value):
    """Reject bools, strings and nonfinite wire geometry without coercion."""
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError("Docling geometry must contain finite numbers")
    return value


def integer(value, minimum=0, maximum=4096):
    """Require an exact bounded wire integer."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Docling index/count must be a bounded integer")
    return value


def geometry(document, source, box=None):
    """Validate one reported box against its actual page dimensions."""
    page = integer(source["page_no"], 1)
    size = document["pages"][str(page)]["size"]
    box = source["bbox"] if box is None else box
    left, top, right, bottom = [number(box[k]) for k in ("l", "t", "r", "b")]
    width, height = number(size["width"]), number(size["height"])
    origin = {"TOPLEFT": "top_left", "BOTTOMLEFT": "bottom_left"}.get(box["coord_origin"])
    if origin is None:
        raise ValueError("Docling bounding box has an unsupported coordinate origin")
    if not (0 <= left < right <= width and 0 <= min(top, bottom) < max(top, bottom) <= height):
        return IngestionLocation(page=page)
    return IngestionLocation(page=page, bbox=[left, min(top, bottom), right, max(top, bottom)],
        coordinate_origin=origin, page_width=width, page_height=height)


def location(document, item, element, cell=None, **fields):
    """Keep boxes only for whole text or an actual single-page cell/image."""
    provenance = item.get("prov", [])
    if type(provenance) is not list or len(provenance) > 64:
        raise ValueError("Docling provenance cardinality exceeds limits")
    for source in provenance:
        geometry(document, source)
        span = source["charspan"]
        if type(span) is not list or len(span) != 2:
            raise ValueError("Docling provenance requires a character span pair")
        start, end = [integer(v, maximum=32768) for v in span]
        if start > end or ("text" in item and end > len(item["text"])):
            raise ValueError("Docling provenance character span is outside its text")
    position = {"element": element, **fields}
    whole = "text" not in item or (provenance and provenance[0]["charspan"] == [0, len(item["text"])])
    if len(provenance) == 1 and whole and (cell is None or cell.get("bbox") is not None):
        measured = geometry(document, provenance[0], None if cell is None else cell["bbox"])
        position.update({k: v for k, v in measured.model_dump().items() if v is not None})
    return IngestionLocation(**position)


def text_segments(document, cancelled, deadline):
    """Retain text/formulas individually without claiming original character offsets."""
    result, skipped = [], 0
    for index, item in enumerate(document.get("texts", [])):
        check_worker(cancelled, deadline)
        element = f"#/texts/{index}"
        if item["self_ref"] != element:
            raise ValueError("Docling text reference differs from its position")
        if not item["text"].strip():
            skipped += 1
            continue
        kind = "equation" if item["label"] == "formula" else "text"
        result.append(IngestionSegment(id=f"docling-text-{index}", kind=kind, text=item["text"],
            location=location(document, item, element), method="docling-service-reported-" + kind + ":" + item["label"]))
    return result, skipped


def table_segments(document, cancelled, deadline):
    """Keep every reported cell and its row/column, including repeated cell text."""
    result = []
    for index, item in enumerate(document.get("tables", [])):
        check_worker(cancelled, deadline)
        element = f"#/tables/{index}"
        if item["self_ref"] != element:
            raise ValueError("Docling table reference differs from its position")
        data = item["data"]
        for cell_index, cell in enumerate(data["table_cells"]):
            check_worker(cancelled, deadline)
            row, column = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
            if (type(row) is not int or type(column) is not int
                    or not 0 <= row < data["num_rows"] or not 0 <= column < data["num_cols"]):
                raise ValueError("Docling table cell is outside its reported grid")
            if not cell["text"].strip():
                continue
            result.append(IngestionSegment(id=f"docling-table-{index}-cell-{cell_index}",
                kind="table_cell", text=cell["text"], method="docling-service-reported-table-cell",
                location=location(document, item, element, cell=cell, table=index, row=row, column=column)))
    return result


def embedded_picture(item, path):
    """Admit one bounded embedded PNG; external paths and URLs are never followed."""
    image = item["image"]
    prefix = "data:image/png;base64,"
    uri = image["uri"]
    if image["mimetype"] != "image/png" or not isinstance(uri, str) or not uri.startswith(prefix):
        raise ValueError("Docling pictures require embedded PNG bytes; external images are unsupported")
    encoded = uri[len(prefix):]
    if len(encoded) > 4 * ((256 * 1024 + 2) // 3):
        raise ValueError("Docling embedded image exceeds its encoded byte limit")
    declared = [number(image["size"][key]) for key in ("width", "height")]
    if any(v <= 0 or int(v) != v for v in declared) or declared[0] * declared[1] > 8_000_000:
        raise ValueError("Docling embedded image dimensions exceed limits")
    body = base64.b64decode(encoded, validate=True)
    if not body or len(body) > 256 * 1024:
        raise ValueError("Docling embedded image exceeds 256 KiB")
    from PIL import Image

    with Image.open(io.BytesIO(body), formats=["PNG"]) as opened:
        width, height = opened.size
        if width * height > 8_000_000 or [width, height] != declared or opened.n_frames != 1:
            raise ValueError("Docling embedded image dimensions exceed limits or differ from its declaration")
        opened.verify()
    with path.open("xb") as writer:
        path.chmod(0o600)
        writer.write(body)


def parse_document(response, directory, cancelled, deadline):
    """Interpret only the selected JSON contract and fail on unsupported populated modalities."""
    check_worker(cancelled, deadline)
    if response["status"] != "success" or response.get("errors"):
        raise ValueError("Docling conversion did not report complete success")
    document = response["document"]["json_content"]
    validate_population(document)
    if document["schema_name"] != "DoclingDocument" or document["version"] != "1.10.0":
        raise ValueError("Unsupported Docling document schema; expected DoclingDocument1.10.0")
    if any(document.get(key) for key in (
            "key_value_items", "form_items", "field_regions", "field_items")):
        raise ValueError("Docling returned unsupported populated form/key-value elements; response retained")
    texts, skipped = text_segments(document, cancelled, deadline)
    segments = texts + table_segments(document, cancelled, deadline)
    for index, item in enumerate(document.get("pictures", [])):
        check_worker(cancelled, deadline)
        if index >= 56:
            raise ValueError("Docling image population exceeds the artifact count ceiling")
        element = f"#/pictures/{index}"
        if item["self_ref"] != element:
            raise ValueError("Docling picture reference differs from its position")
        path = directory / f"docling-image-{index}.png"
        embedded_picture(item, path)
        segments.append(IngestionSegment(id=f"docling-image-{index}", kind="image",
            location=location(document, item, element, image=element), artifact=str(path),
            method="docling-service-reported-embedded-image"))
    check_worker(cancelled, deadline)
    return ParsedSource(segments=segments, limitations=LIMITATIONS + [
        f"Skipped {skipped} whitespace-only Docling text items; source references and raw text remain retained"])


def validate_table(data):
    """Bound sparse grids before span traversal and reject overlapping cell reports."""
    rows, columns = integer(data["num_rows"]), integer(data["num_cols"])
    cells = data["table_cells"]
    if type(cells) is not list or len(cells) > 4096 or rows * columns > 4096:
        raise ValueError("Docling table grid/cell population exceeds limits")
    grid = data.get("grid")
    if grid is not None and (type(grid) is not list or len(grid) != rows or any(
            type(row) is not list or len(row) != columns for row in grid)):
        raise ValueError("Docling computed grid shape differs from its declaration")
    occupied = set()
    for cell in cells:
        if type(cell.get("text")) is not str or len(cell["text"]) > 32768:
            raise ValueError("Docling table cell text is invalid or oversized")
        r0, r1, c0, c1 = [integer(cell[k]) for k in (
            "start_row_offset_idx", "end_row_offset_idx", "start_col_offset_idx", "end_col_offset_idx")]
        if not (0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= columns):
            raise ValueError("Docling cell span is outside its grid")
        if integer(cell["row_span"], 1) != r1 - r0 or integer(cell["col_span"], 1) != c1 - c0:
            raise ValueError("Docling cell span differs from its offsets")
        for row in range(r0, r1):
            for column in range(c0, c1):
                if (row, column) in occupied:
                    raise ValueError("Docling cells overlap in the reported grid")
                if grid is not None and grid[row][column] != cell:
                    raise ValueError("Docling computed grid differs from its actual cells")
                occupied.add((row, column))
        if cell.get("bbox") is not None:
            box = cell["bbox"]
            for key in ("l", "t", "r", "b"):
                number(box[key])
            if box["coord_origin"] not in {"TOPLEFT", "BOTTOMLEFT"}:
                raise ValueError("Docling cell box coordinate origin is invalid")


def validate_population(document):
    """Reject oversized populations, invalid refs and geometry before output allocation."""
    total = 0
    refs = {"#/body", "#/furniture"}
    for name in ("texts", "tables", "pictures", "groups"):
        items = document.get(name, [])
        if type(items) is not list or len(items) > (56 if name == "pictures" else 4096):
            raise ValueError("Docling element population exceeds limits")
        for index, item in enumerate(items):
            ref = f"#/{name}/{index}"
            if not isinstance(item, dict) or item.get("self_ref") != ref:
                raise ValueError("Docling element reference differs from its position")
            refs.add(ref)
            if name == "tables":
                validate_table(item["data"])
                total += len(item["data"]["table_cells"])
        total += len(items) if name in {"texts", "pictures"} else 0
    if total > 4096:
        raise ValueError("Docling segment population exceeds limits")
    pages = document.get("pages", {})
    if type(pages) is not dict or len(pages) > 4096:
        raise ValueError("Docling page population exceeds limits")
    for key, page in pages.items():
        if key != str(integer(page["page_no"], 1)) or any(number(page["size"][k]) <= 0 for k in ("width", "height")):
            raise ValueError("Docling page identity/dimensions are invalid")
    validate_refs(document, refs)


def validate_refs(document, refs):
    """Check every wire reference without following external resources."""
    stack, visited = [document], 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > 32768:
            raise ValueError("Docling nested population exceeds limits")
        if isinstance(node, dict):
            for key in ("$ref", "cref"):
                if key in node and (not isinstance(node[key], str) or node[key] not in refs):
                    raise ValueError("Docling document contains an unresolved reference")
            stack.extend(node.values())
        elif isinstance(node, list):
            if len(node) > 8192:
                raise ValueError("Docling nested list population exceeds limits")
            stack.extend(node)
