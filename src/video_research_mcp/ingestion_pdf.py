"""Optional installed Poppler extraction with original-page and image identities."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from xml.etree import ElementTree

from .media_local_io import _copy_hash, _open_regular
from .media_process import run_media_process
from .models.ingestion import IngestionLocation, IngestionSegment, ParsedSource
from .ingestion_pdf_pixels import (
    IMAGE_LIMITATIONS, MAX_BYTES, MAX_FILES, PACKAGES, RESULT_BYTES, SIMPLE_FILTERS,
    encoded, file_record, pixel_profile, refuse_loader_overrides, usage, write_output,
)
from .ingestion_pdf_tables import rectangular_tables
from .ingestion_pdf_provenance import _page_geometry, image_bindings, validate_layout_pages
from .ingestion_pdf_rulings import attach_rulings, validate_rulings

MAX_ELEMENTS = 4096


def pdf_profile() -> dict:
    """Bind separately installed parser executables without importing foreign code."""
    executables = {}
    for name in ("pdftotext", "pdfimages"):
        command = shutil.which(name)
        if command is None:
            raise FileNotFoundError(
                f"PDF parser unavailable: {name} missing from PATH; configure installed Poppler"
            )
        path = Path(command).resolve()
        digest, size = _copy_hash(path, max_bytes=32 * 1024 * 1024)
        executables[name] = {"path": str(path), "sha256": digest, "bytes": size}
    return {"parser": "installed_poppler", "executables": executables,
            "foreign_code_bundled": False, "ocr": False,
            "table_structure": "positioned-text rectangular inference; semantic accuracy unknown",
            "image_pixels": "optional selected PDFium source RGB; descriptors retained",
            "pixels": pixel_profile()}


def _text_segments(data: bytes) -> list[IngestionSegment]:
    """Keep native word coordinates in measured page units, without guessing tables."""
    if b"<!ENTITY" in data:
        raise ValueError("PDF parser emitted an unsupported XML entity declaration")
    document = ElementTree.fromstring(data)
    segments = []
    for page_number, page in enumerate(document.iter("{http://www.w3.org/1999/xhtml}page"), 1):
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        for word in page.iter("{http://www.w3.org/1999/xhtml}word"):
            text = "".join(word.itertext())
            if not text.strip():
                continue
            location = IngestionLocation(
                page=page_number,
                bbox=[float(word.attrib[key]) for key in ("xMin", "yMin", "xMax", "yMax")],
                coordinate_origin="top_left", page_width=width, page_height=height,
            )
            segments.append(IngestionSegment(id=f"word-{len(segments)}", kind="text",
                                             text=text, location=location,
                                             method="poppler-bbox-layout-v1"))
            if len(segments) > MAX_ELEMENTS:
                raise ValueError("PDF extraction exceeds 4096 elements")
    return segments


def _image_segments(data: bytes, directory: Path) -> list[IngestionSegment]:
    """Retain listed PDF object identity and dimensions as descriptors, not pixels."""
    segments = []
    for line in data.decode("utf-8", errors="strict").splitlines():
        fields = line.split()
        if not fields or not fields[0].isdecimal():
            continue
        if len(fields) < 16:
            raise ValueError("Unsupported pdfimages image-list record")
        page, number = int(fields[0]), int(fields[1])
        descriptor = {"page": page, "number": number, "type": fields[2],
                      "width": int(fields[3]), "height": int(fields[4]),
                      "object_number": int(fields[10]), "object_generation": int(fields[11]),
                      "pixel_bytes_exported": False, "source_role": "original PDF image object"}
        if descriptor["width"] < 1 or descriptor["height"] < 1 or len(segments) >= 60:
            raise ValueError("PDF image descriptors exceed dimension or count bounds")
        path = write_output(directory, f"pdf-image-{page}-{number}.json", encoded(descriptor))
        segments.append(IngestionSegment(
            id=f"image-{page}-{number}", kind="image", artifact=str(path),
            location=IngestionLocation(page=page, image=f"object:{fields[10]}:{fields[11]}"),
            method="poppler-embedded-image-list-v1",
        ))
    return segments


def _tables(output, source, directory, existing):
    """Abstain optional cells before consuming the original words/descriptors' budget."""
    segments = []
    tables = rectangular_tables(output, source["sha256"])
    if sum(len(t["cells"]) for t in tables) > MAX_ELEMENTS - len(existing):
        return [], ["Table cells abstained: words/descriptors leave insufficient 4096-element budget"]
    artifact = directory / "pdf-tables.json"
    for table in tables:
        for cell in table["cells"]:
            location = IngestionLocation(
                page=table["page"], table=table["table"], row=cell["row"], column=cell["column"],
                bbox=cell["bbox"], coordinate_origin="top_left",
                page_width=table["page_width"], page_height=table["page_height"],
            )
            segments.append(IngestionSegment(
                id=f"cell-{table['table']}-{cell['row']}-{cell['column']}", kind="table_cell",
                text=cell["text"], location=location, artifact=str(artifact), method=table["method"],
            ))
    if not segments:
        return [], []
    data = encoded({"tables": tables})
    reserve = len(encoded(ParsedSource(segments=existing + segments).model_dump(mode="json"))) + 4096
    size, count = usage(directory)
    if size + len(data) + reserve > MAX_BYTES or count + 2 > MAX_FILES:
        return [], ["Table cells abstained: insufficient table artifact/segment byte or file budget"]
    write_output(directory, artifact.name, data, reserve)
    return segments, []


def _remaining(deadline):
    """Keep all three subprocesses inside the caller's single original deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("PDF extraction exceeded its original deadline")
    return min(30.0, remaining)


def _same_profile(profile):
    """Reject any selected executable/package/worker drift before publication."""
    if pdf_profile() != profile:
        raise ValueError("PDF parser executable or selected runtime changed during extraction")


def _pixel_record(record, directory, source):
    """Validate strict worker metadata, exact stream/pixels and original geometry."""
    fields = {"page", "object_ordinal", "page_width", "page_height", "source_pdf_sha256",
              "native_bbox", "bbox", "coordinate_origin", "native_coordinate_origin", "width", "height", "filters",
              "raw_stream_sha256", "pixel_sha256", "stream", "ppm", "metadata",
              "stream_bytes", "ppm_bytes", "limitations", "colorspace"}
    if not isinstance(record, dict) or set(record) != fields:
        raise ValueError("Unknown PDFium image metadata fields")
    if (record["limitations"] != IMAGE_LIMITATIONS or record["colorspace"] != 2 or not isinstance(record["filters"], list)
            or any(not isinstance(f, str) or f not in SIMPLE_FILTERS for f in record["filters"])
            or any(type(record[k]) is not int or record[k] <= 0 for k in ("stream_bytes", "ppm_bytes"))):
        raise ValueError("Invalid PDFium pixel metadata contract")
    if record["source_pdf_sha256"] != source["sha256"] or type(record["object_ordinal"]) is not int or record["object_ordinal"] < 0:
        raise ValueError("Invalid PDFium original/object identity")
    name = f"pdfium-{record['page']}-{record['object_ordinal']}"
    for key, suffix in (("stream", ".stream"), ("ppm", ".ppm"), ("metadata", ".json")):
        if record[key] != name + suffix:
            raise ValueError("PDFium output traversal or unexpected artifact name")
    location = IngestionLocation(page=record["page"], image=f"pdfium-object:{record['object_ordinal']}",
                                 bbox=record["bbox"], coordinate_origin=record["coordinate_origin"],
                                 page_width=record["page_width"], page_height=record["page_height"])
    left, bottom, right, top = record["native_bbox"]
    if record["native_coordinate_origin"] != "bottom_left" or record["coordinate_origin"] != "top_left" or record["bbox"] != [left, record["page_height"]-top, right, record["page_height"]-bottom]:
        raise ValueError("PDFium native/top-left coordinate mismatch")
    stream = file_record(directory / record["stream"])
    if (stream["sha256"], stream["bytes"]) != (record["raw_stream_sha256"], record["stream_bytes"]):
        raise ValueError("PDFium raw stream commitment mismatch")
    file_record(directory / record["metadata"])
    if json.loads((directory / record["metadata"]).read_bytes()) != record:
        raise ValueError("PDFium metadata commitment mismatch")
    ppm = file_record(directory / record["ppm"])
    w, h = record["width"], record["height"]
    if type(w) is not int or type(h) is not int or w <= 0 or h <= 0:
        raise ValueError("Invalid PDFium RGB dimensions")
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    data = (directory / record["ppm"]).read_bytes()
    if (ppm["bytes"] != record["ppm_bytes"] or not data.startswith(header)
            or len(data) != len(header) + 3*w*h
            or hashlib.sha256(data[len(header):]).hexdigest() != record["pixel_sha256"]):
        raise ValueError("PDFium RGB pixel commitment mismatch")
    return IngestionSegment(id=name, kind="image", location=location,
                            artifact=str(directory / record["ppm"]), method="pdfium-source-rgb-v1")


def _runtime_result(result, profile):
    """Check the selected worker and every reported foreign module origin."""
    expected_runtime = {"worker": profile["worker"], "python": profile["python"],
                        "selected_native_paths": [r["path"] for r in profile["inventory"]
                                         if Path(r["path"]).suffix in {".so", ".dylib", ".dll"}],
                        "checked_boundary": profile["checked_boundary"]}
    if result["runtime"] != expected_runtime or not isinstance(result["module_origins"], dict):
        raise ValueError("Invalid PDFium runtime result")
    selected = {r["path"] for r in profile["inventory"]}
    if not set(PACKAGES) <= set(result["module_origins"]) or any(
            n.split(".")[0] not in PACKAGES or p not in selected
            for n, p in result["module_origins"].items()):
        raise ValueError("PDFium module origin outside selected inventory")


def _pixel_result(directory, previous, source, profile, reserve):
    """Validate bounded native observations before adding optional source correspondence."""
    size, count = usage(directory)
    body = file_record(directory / "pdfium-result.json")
    if size > MAX_BYTES or count >= MAX_FILES or body["bytes"] > RESULT_BYTES:
        raise ValueError("PDFium result exceeds byte/artifact limits")
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    if not isinstance(result, dict) or set(result) != {"images", "pages", "rulings", "limitations", "module_origins", "runtime"}:
        raise ValueError("Unknown PDFium result fields")
    if not isinstance(result["images"], list) or len(result["images"]) > 20:
        raise ValueError("PDFium image result count exceeds bounds")
    if not isinstance(result["limitations"], list) or len(result["limitations"]) > 24 or any(
            not isinstance(s, str) or len(s) > 4096 for s in result["limitations"]):
        raise ValueError("Invalid PDFium capability limitations")
    _runtime_result(result, profile)
    pages = _page_geometry(result["pages"], source)
    occurrences = validate_rulings(result["rulings"], source["sha256"], pages)
    segments, names = [], set()
    for record in result["images"]:
        if not isinstance(record, dict):
            raise ValueError("Invalid PDFium image record")
        segment = _pixel_record(record, directory, source)
        page = pages.get(record["page"])
        if page is None or page["rotation_degrees"] != 0 or any(
                record[k] != page[k] for k in ("page_width", "page_height")):
            raise ValueError("PDFium image/page geometry mismatch")
        occurrence = (record["page"], record["object_ordinal"])
        if occurrence in occurrences:
            raise ValueError("Duplicate PDFium image occurrence")
        occurrences.add(occurrence)
        segments.append(segment)
        names.update(record[k] for k in ("stream", "ppm", "metadata"))
    if {p.name for p in directory.iterdir()} != previous | names | {"pdfium-result.json"}:
        raise ValueError("PDFium emitted unknown artifacts")
    links, limits = image_bindings(result["images"], directory, source)
    if links:
        data = encoded({"images": links})
        if count + 2 <= MAX_FILES and size + len(data) + reserve <= MAX_BYTES:
            write_output(directory, "pdf-original-image-bindings.json", data, reserve)
        else:
            limits.append("Original image correspondence artifact abstained: remaining byte/file budget")
    return segments, result["limitations"] + limits


async def _pixels(path, directory, source, profile, segments, deadline):
    """Dispatch the exact isolated stdlib bootstrap, then validate its contained outputs."""
    if not profile["available"]:
        return [], [profile["limitation"]]
    reserve = len(encoded(ParsedSource(segments=segments).model_dump(mode="json"))) + 256*1024
    descriptor = {"runtime": profile, "input": source, "output": str(directory),
                  "elements": len(segments), "reserve_bytes": reserve}
    data = encoded(descriptor)
    size, count = usage(directory)
    if count + 3 > MAX_FILES or size + len(data) + reserve + RESULT_BYTES > MAX_BYTES:
        return [], ["PDFium pixel export unavailable: insufficient descriptor/result/segment budget; descriptors retained"]
    try:
        refuse_loader_overrides()
    except ValueError:
        return [], ["PDFium pixel export unavailable: loader override environment unsupported; descriptors retained"]
    descriptor_path = write_output(directory, "pdfium-descriptor.json", data, reserve + RESULT_BYTES)
    previous = {p.name for p in directory.iterdir()}
    await run_media_process([profile["python"]["selected_path"], "-I", "-S", "-B",
                             profile["worker"]["path"], str(descriptor_path), str(path), str(directory)],
                            _remaining(deadline))
    return _pixel_result(directory, previous, source, profile, reserve)


def _refine_tables(output, source, directory, segments):
    """Refine already reserved content tables only within the remaining byte budget."""
    native, artifact = directory / "pdfium-result.json", directory / "pdf-tables.json"
    if not artifact.exists() or not native.exists():
        return []
    result = json.loads(native.read_bytes())
    pages = _page_geometry(result["pages"], source)
    try:
        validate_layout_pages(output, pages)
    except ValueError:
        return ["Measured table region abstained: Poppler/PDFium page geometry disagreement"]
    tables = json.loads(artifact.read_bytes())["tables"]
    data = encoded({"tables": attach_rulings(tables, result["rulings"], source["sha256"], pages)})
    size, _ = usage(directory)
    reserve = len(encoded(ParsedSource(segments=segments).model_dump(mode="json"))) + 4096
    if size - artifact.stat().st_size + len(data) + reserve > MAX_BYTES:
        return ["Measured table region abstained: reserved content tables leave insufficient byte budget"]
    artifact.write_bytes(data)
    return []


async def parse_pdf_source(path: Path, directory: Path, profile: dict, timeout: float) -> ParsedSource:
    """Retain source/XML/words and bounded inferred cells plus optional embedded pixels."""
    deadline = time.monotonic() + timeout
    path, directory = path.absolute(), directory.absolute()
    source = file_record(path)
    with _open_regular(path) as reader:
        if not reader.read(8).startswith(b"%PDF-"):
            raise ValueError("PDF source has no PDF header")
    executables = profile["executables"]
    _same_profile(profile)
    output, _ = await run_media_process(
        [executables["pdftotext"]["path"], "-bbox-layout", "-enc", "UTF-8", str(path), "-"],
        _remaining(deadline),
    )
    segments = _text_segments(output)
    write_output(directory, "pdf-layout.xml", output)
    _same_profile(profile)
    images, _ = await run_media_process(
        [executables["pdfimages"]["path"], "-list", str(path)], _remaining(deadline),
    )
    segments.extend(_image_segments(images, directory))
    ParsedSource(segments=segments)
    cells, table_limits = _tables(output, source, directory, segments)
    segments.extend(cells)
    _same_profile(profile)
    pixels, limitations = await _pixels(path, directory, source, profile["pixels"], segments, deadline)
    segments.extend(pixels)
    table_limits.extend(_refine_tables(output, source, directory, segments))
    parsed = ParsedSource(segments=segments, limitations=[
        "OCR unavailable; cells are positioned-text inference; measured ruling regions require a complete unambiguous native line grid; semantic accuracy unknown",
        "PDF text positions use native top-left XY bounds in measured page units",
        "Poppler descriptors and PDFium pixel occurrences use separate identities; no duplicate verified image count",
        IMAGE_LIMITATIONS,
        *table_limits, *limitations[:26],
        *(["Additional provenance limitations truncated; unresolved pixels retained"] if len(limitations) > 26 else []),
    ])
    size, count = usage(directory)
    if size + len(encoded(parsed.model_dump(mode="json"))) > MAX_BYTES or count + 1 > MAX_FILES:
        raise ValueError("PDF outputs including segments exceed 8 MiB/64 artifacts")
    _same_profile(profile)
    if file_record(path) != source:
        raise ValueError("Original PDF changed during extraction")
    _remaining(deadline)
    return parsed
