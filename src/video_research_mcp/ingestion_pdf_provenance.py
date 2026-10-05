"""Narrow original-byte correspondence; unsupported PDF syntax retains unresolved pixels."""

import hashlib
import json
import math
import zlib
from pathlib import Path
from xml.etree import ElementTree

from .ingestion_pdf_pixels import file_record

MAX_SOURCE = 8 * 1024 * 1024


def validate_layout_pages(data, pages):
    """Reject disagreement between measured Poppler and PDFium page populations/sizes."""
    layout = list(ElementTree.fromstring(data).iter("{http://www.w3.org/1999/xhtml}page"))
    if len(layout) != len(pages):
        raise ValueError("Poppler/PDFium page count disagreement")
    for number, page in enumerate(layout, 1):
        sizes = [float(page.attrib[k]) for k in ("width", "height")]
        if sizes != [pages[number][k] for k in ("page_width", "page_height")]:
            raise ValueError("Poppler/PDFium page dimension disagreement")


def _page_geometry(records, source):
    """Validate ordered source-bound page measurements, including image-free pages."""
    fields = {"page", "page_width", "page_height", "rotation_degrees", "rotation_direction",
              "units", "source_pdf_sha256", "method"}
    if not isinstance(records, list) or not 1 <= len(records) <= 4096:
        raise ValueError("Invalid PDFium page geometry count")
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError("Unknown PDFium page geometry fields")
        if (type(record["page"]) is not int or record["page"] != number
                or record["source_pdf_sha256"] != source["sha256"]
                or record["method"] != "pdfium-page-geometry-v1"
                or record["units"] != "PDF_canvas_units" or record["rotation_direction"] != "clockwise"
                or type(record["rotation_degrees"]) is not int or record["rotation_degrees"] not in (0, 90, 180, 270)
                or any(type(record[k]) not in (int, float) or not math.isfinite(record[k]) or record[k] <= 0
                       for k in ("page_width", "page_height"))):
            raise ValueError("Invalid source-bound PDFium page geometry")
    return {record["page"]: record for record in records}


def _object_body(data, entries, xref, number, generation):
    """Locate one live object through its exact xref offset and generation."""
    if (type(number) is not int or type(generation) is not int or not 0 < number < len(entries)
            or entries[number][1:] != (generation, b"n")):
        raise ValueError("Object absent from exact live xref")
    start = entries[number][0]
    end = min([e[0] for e in entries if e[2] == b"n" and e[0] > start] + [xref])
    header = f"{number} {generation} obj\n".encode()
    body = data[start:end]
    if not body.startswith(header) or not body.endswith(b"\nendobj\n"):
        raise ValueError("Live object offset/generation/framing mismatch")
    return start + len(header), body[len(header):-len(b"\nendobj\n")]


def _xref_entries(rows):
    """Read fixed-width canonical entries without scanning arbitrary PDF dictionaries."""
    entries = []
    for row in rows:
        if (len(row) != 19 or not row[:10].isdigit() or row[10:11] != b" "
                or not row[11:16].isdigit() or row[16:17] != b" " or row[17:] not in (b"n ", b"f ")):
            raise ValueError("Malformed canonical xref entry")
        entries.append((int(row[:10]), int(row[11:16]), row[17:18]))
    if entries[0] != (0, 65535, b"f") or any(e[2] != b"n" or e[1] >= 65535 for e in entries[1:]):
        raise ValueError("Unsupported free/live xref entries")
    return entries


def classic_xref(data):
    """Accept one canonical classic xref with a live Catalog; abstain on other variants."""
    marker = data.rfind(b"\nstartxref\n")
    tail = data[marker+11:].splitlines() if marker >= 0 else []
    if (not data.startswith(b"%PDF-") or not data.endswith(b"\n%%EOF\n")
            or len(tail) != 2 or not tail[0].isdigit() or tail[1] != b"%%EOF"):
        raise ValueError("Unsupported startxref/EOF")
    offset = int(tail[0])
    rows = data[offset:marker].splitlines() if 0 < offset < marker else []
    if len(rows) < 6 or rows[0] != b"xref":
        raise ValueError("Only classic xref is supported")
    section = rows[1].split()
    if len(section) != 2 or section[0] != b"0" or not section[1].isdigit():
        raise ValueError("Only one zero-based xref subsection is supported")
    count = int(section[1])
    if not 1 < count <= 4096 or len(rows) != count + 4 or rows[count+2] != b"trailer":
        raise ValueError("Unsupported xref population/trailer")
    trailer = rows[-1].split()
    if (len(trailer) != 8 or trailer[:2] != [b"<<", b"/Size"] or trailer[2] != section[1]
            or trailer[3] != b"/Root" or not trailer[4].isdigit() or trailer[5:] != [b"0", b"R", b">>"]):
        raise ValueError("Unsupported trailer fields")
    entries = _xref_entries(rows[2:count+2])
    offsets = [entry[0] for entry in entries[1:]]
    if len(offsets) != len(set(offsets)) or any(not 0 < p < offset for p in offsets):
        raise ValueError("Ambiguous xref offsets")
    for number, entry in enumerate(entries[1:], 1):
        _object_body(data, entries, offset, number, entry[1])
    _, catalog = _object_body(data, entries, offset, int(trailer[4]), 0)
    tokens = catalog.split()
    if (len(tokens) != 8 or tokens[:4] != [b"<<", b"/Type", b"/Catalog", b"/Pages"]
            or not tokens[4].isdigit() or tokens[5:] != [b"0", b"R", b">>"]):
        raise ValueError("Unsupported or wrong live Catalog root")
    _, pages = _object_body(data, entries, offset, int(tokens[4]), 0)
    if not pages.startswith(b"<< /Type /Pages ") or not pages.endswith(b">>"):
        raise ValueError("Catalog Pages reference is not a live page tree")
    return entries, offset


def direct_image(data, entries, xref, number, generation):
    """Check a flat direct-Length RGB8/Flate object and its exact stream framing."""
    start, body = _object_body(data, entries, xref, number, generation)
    if b"\nstream\n" not in body:
        raise ValueError("Unsupported direct image stream framing")
    dictionary, rest = body.split(b"\nstream\n", 1)
    tokens = dictionary.split()
    if tokens[:1] != [b"<<"] or tokens[-1:] != [b">>"] or len(tokens) != 18:
        raise ValueError("Only flat eight-field image dictionaries are supported")
    keys, values = tokens[1:-1:2], tokens[2:-1:2]
    fields = dict(zip(keys, values))
    expected = {b"/Length", b"/Type", b"/Subtype", b"/Width", b"/Height", b"/ColorSpace", b"/BitsPerComponent", b"/Filter"}
    if set(fields) != expected or len(keys) != len(set(keys)):
        raise ValueError("Masks/Decode/indirect/unknown image fields abstained")
    if (fields[b"/Type"] != b"/XObject" or fields[b"/Subtype"] != b"/Image"
            or fields[b"/ColorSpace"] != b"/DeviceRGB" or fields[b"/BitsPerComponent"] != b"8"
            or fields[b"/Filter"] != b"/FlateDecode" or any(not fields[k].isdigit() for k in (b"/Length", b"/Width", b"/Height"))):
        raise ValueError("Unsupported original RGB/Flate object")
    length, width, height = (int(fields[k]) for k in (b"/Length", b"/Width", b"/Height"))
    if not 0 < 3 * width * height <= MAX_SOURCE or length <= 0 or rest[length:] != b"\nendstream":
        raise ValueError("Direct Length/dimensions do not delimit a bounded exact stream")
    return start + len(dictionary) + len(b"\nstream\n"), length, width, height


def _source_rgb(stream, width, height):
    """Bound source Flate decoding and reject trailing, truncated or oversized data."""
    decoder = zlib.decompressobj()
    rgb = decoder.decompress(stream, 3 * width * height + 1)
    if len(rgb) != 3 * width * height or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Original Flate data does not contain exactly RGB8 pixels")
    return hashlib.sha256(rgb).hexdigest()


def _candidate(data, entries, xref, listed, record, stream):
    """Require Poppler, source dictionary, encoded bytes and decoded RGB to agree."""
    if (listed["page"] != record["page"] or listed["type"] != "image"
            or (listed["width"], listed["height"]) != (record["width"], record["height"])):
        return None
    start, length, width, height = direct_image(data, entries, xref, listed["object_number"], listed["object_generation"])
    if (data[start:start+length] != stream or (width, height) != (record["width"], record["height"])
            or record["colorspace"] != 2 or record["filters"] != ["FlateDecode"]
            or hashlib.sha256(stream).hexdigest() != record["raw_stream_sha256"]
            or _source_rgb(stream, width, height) != record["pixel_sha256"]):
        return None
    return {"object_number": listed["object_number"], "object_generation": listed["object_generation"],
            "source_stream_offset": start, "source_stream_length": length, "source_stream_range": [start, start+length]}


def image_bindings(records, directory, source):
    """Add unique exact-byte inferences without removing previously validated pixels."""
    if not records:
        return [], []
    original = file_record(Path(source["path"]))
    if original != source or original["bytes"] > MAX_SOURCE:
        return [], ["Original image correspondence abstained: source bound/size mismatch"]
    data = Path(source["path"]).read_bytes()
    if len(data) != source["bytes"] or hashlib.sha256(data).hexdigest() != source["sha256"]:
        return [], ["Original image correspondence abstained: source changed while reading"]
    try:
        entries, xref = classic_xref(data)
    except ValueError as error:
        return [], ["Original image correspondence abstained: " + str(error)]
    paths = list(directory.glob("pdf-image-*.json"))
    if len(paths) > 60 or any(file_record(p)["bytes"] > 4096 for p in paths):
        raise ValueError("Poppler descriptors exceed byte/count bounds")
    descriptors = [json.loads(p.read_bytes()) for p in paths]
    links, limits = [], []
    for record in records:
        stream_path = directory / record["stream"]
        if file_record(stream_path)["bytes"] > MAX_SOURCE:
            raise ValueError("Native stream exceeds source correspondence bound")
        stream = stream_path.read_bytes()
        candidates = []
        for listed in descriptors:
            try:
                candidate = _candidate(data, entries, xref, listed, record, stream)
            except (ValueError, zlib.error):
                continue
            if candidate is not None:
                candidates.append(candidate)
        if (len(candidates) != 1 or not stream or data.count(stream) != 1
                or sum(r["raw_stream_sha256"] == record["raw_stream_sha256"] for r in records) != 1):
            limits.append(f"Page {record['page']} ordinal {record['object_ordinal']}: unresolved ambiguous/unsupported original image correspondence")
            continue
        links.append({**candidates[0], "source_pdf_sha256": source["sha256"], "page": record["page"],
            "object_ordinal": record["object_ordinal"], "source_colorspace": "DeviceRGB", "native_colorspace_enum": record["colorspace"],
            "raw_stream_sha256": record["raw_stream_sha256"], "pixel_sha256": record["pixel_sha256"],
            "width": record["width"], "height": record["height"], "filters": record["filters"],
            "method": "classic-xref-direct-length-unique-exact-byte-correspondence-v1",
            "trust_boundary": "Source byte/hash and bounded RGB independently verified; occurrence page/ordinal from PDFium and object number/generation from Poppler; correspondence is inference, not a PDFium object-number API"})
    return links, limits
