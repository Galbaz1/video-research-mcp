"""Optional installed Poppler extraction with original-page and image identities."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from xml.etree import ElementTree

from .media_local_io import _copy_hash, _open_regular
from .media_process import run_media_process
from .models.ingestion import IngestionLocation, IngestionSegment, ParsedSource

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
            "table_structure": "unavailable; text locations retained",
            "image_pixels": "not_exported; embedded image descriptors retained"}


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
        path = directory / f"pdf-image-{page}-{number}.json"
        with path.open("x", encoding="utf-8") as writer:
            path.chmod(0o600)
            json.dump(descriptor, writer, sort_keys=True, allow_nan=False)
        segments.append(IngestionSegment(
            id=f"image-{page}-{number}", kind="image", artifact=str(path),
            location=IngestionLocation(page=page, image=f"object:{fields[10]}:{fields[11]}"),
            method="poppler-embedded-image-list-v1",
        ))
    return segments


async def parse_pdf_source(path: Path, directory: Path, profile: dict, timeout: float) -> ParsedSource:
    """Parse the retained PDF with bounded stdout and recheck executable bindings."""
    with _open_regular(path) as reader:
        if not reader.read(8).startswith(b"%PDF-"):
            raise ValueError("PDF source has no PDF header")
    executables = profile["executables"]
    if pdf_profile() != profile:
        raise ValueError("PDF parser executable changed before dispatch")
    output, _ = await run_media_process(
        [executables["pdftotext"]["path"], "-bbox-layout", "-enc", "UTF-8", str(path), "-"],
        timeout,
    )
    segments = _text_segments(output)
    if pdf_profile() != profile:
        raise ValueError("PDF parser executable changed before image-list dispatch")
    images, _ = await run_media_process(
        [executables["pdfimages"]["path"], "-list", str(path)], timeout,
    )
    segments.extend(_image_segments(images, directory))
    if pdf_profile() != profile:
        raise ValueError("PDF parser executable changed during extraction")
    raw = directory / "pdf-layout.xml"
    with raw.open("xb") as writer:
        raw.chmod(0o600)
        writer.write(output)
    return ParsedSource(segments=segments, limitations=[
        "OCR, table-cell reconstruction and embedded pixel export are unavailable in this parser",
        "PDF text positions use native top-left XY bounds in measured page units",
    ])
