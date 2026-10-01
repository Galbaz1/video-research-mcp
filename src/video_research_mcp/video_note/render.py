"""Lazy core-font plaintext PDF generation and serialized complete PDFium readback."""

import io
import math
import threading
import time

from ..image_preprocessing import BoundedEncoding, check_worker
from .io import (MAX_PAGE_BYTES, MAX_PAGE_PIXELS, MAX_PAGES, MAX_PDF_BYTES,
                 MAX_TOTAL_PAGE_PIXELS, NoteError, canonical, png_shape, read_bytes, write_bytes)

PDFIUM_LOCK = threading.Lock()


def _fpdf_class():
    """Load the optional font-free authoring package only for an actual render."""
    try:
        from fpdf import FPDF
    except ImportError as error:
        raise ImportError("Tutorial PDF dependencies missing; install video-research-mcp[tutorial]") from error
    return FPDF


def _pdfium_module():
    """Load PDFium only while its global native boundary is locked."""
    try:
        import pypdfium2
    except ImportError as error:
        raise ImportError("Tutorial PDF verification missing; install video-research-mcp[tutorial]") from error
    return pypdfium2


def dependencies_ready():
    """Check installed distribution metadata without importing PDF/native packages."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        selected = {"fpdf2": version("fpdf2"), "pypdfium2": version("pypdfium2")}
    except PackageNotFoundError as error:
        raise ImportError("Tutorial PDF dependencies missing; install video-research-mcp[tutorial]") from error
    if not selected["fpdf2"].startswith("2.") or not selected["pypdfium2"].startswith("5."):
        raise ImportError("Tutorial PDF requires fpdf2 major2 and pypdfium2 major5")
    return selected


def caption(frame):
    """Make actual source PTS and exact PNG identity visible without a semantic claim."""
    return (f"Source point {frame['actual_seconds']:.6f}s; PTS {frame['original_pts']} "
            f"at time base {frame['time_base']}. PNG SHA256: {frame['sha256']}")


def _text(pdf, text, size=11):
    pdf.set_font("Helvetica", size=size)
    pdf.multi_cell(w=0, h=size * 1.4, text=text, new_x="LMARGIN", new_y="NEXT")


def _place_image(pdf, frame, data, index):
    width = min(450, frame["width"] * 240 / frame["height"])
    height = width * frame["height"] / frame["width"]
    if pdf.get_y() + height + 60 > pdf.h - 48:
        pdf.add_page()
    image_y = pdf.get_y()
    placement = {"step_index": index, "page": pdf.page_no(), "x_mm": 48 * 25.4 / 72,
                 "y_mm": image_y * 25.4 / 72, "width_mm": width * 25.4 / 72,
                 "height_mm": height * 25.4 / 72, "png_sha256": frame["sha256"]}
    pdf.image(io.BytesIO(data), x=48, y=image_y, w=width, h=height)
    pdf.set_y(image_y + height + 10)
    _text(pdf, caption(frame), 8)
    return placement


def _create_pdf(document, frames, buffers, directory, cancelled, deadline):
    """Render finite plaintext and immutable image buffers; no HTML or custom fonts."""
    check_worker(cancelled, deadline)
    pdf = _fpdf_class()(unit="pt", format="A4")
    pdf.core_fonts_encoding = "cp1252"
    pdf.set_margins(48, 48, 48)
    pdf.set_auto_page_break(auto=True, margin=48)
    pdf.add_page()
    _text(pdf, document["title"], 19)
    _text(pdf, "Source-linked tutorial. Instructions are unreviewed proposals or labeled model inference.")
    _text(pdf, "Original source SHA256: " + document["source"]["sha256"], 8)
    _text(pdf, "Manifest SHA256: " + document["manifest_sha256"], 8)
    for warning in document["warnings"]:
        _text(pdf, warning, 9)
    images = {frame["step_index"]: (frame, data) for frame, data in zip(frames, buffers, strict=True)}
    placements = []
    for index, step in enumerate(document["steps"], 1):
        check_worker(cancelled, deadline)
        pdf.add_page()
        _text(pdf, f"Step {index}: {step['title']}", 15)
        _text(pdf, f"Source interval [{step['start_seconds']:.6f}, {step['end_seconds']:.6f}) seconds; "
                   f"origin: {step['origin']}", 9)
        _text(pdf, step["instruction"])
        if index in images:
            placements.append(_place_image(pdf, *images[index], index))
        else:
            _text(pdf, "Illustration unavailable. Supplied text remains; no visual claim was verified.", 9)
        if pdf.page_no() > MAX_PAGES:
            raise NoteError("Tutorial layout exceeds 40 pages")
    check_worker(cancelled, deadline)
    data = bytes(pdf.output())
    if not data.startswith(b"%PDF-") or len(data) > MAX_PDF_BYTES:
        raise NoteError("Tutorial PDF output is invalid or exceeds 8 MiB")
    pdf_record = write_bytes(directory / "document.pdf", data)
    layout = write_bytes(directory / "layout.json", canonical({"schema_version": 1,
        "page_size_mm": {"width": 210, "height": 297}, "images": placements}))
    return pdf_record, layout


def _page_artifact(page, index, directory, remaining_bytes, cancelled, deadline):
    check_worker(cancelled, deadline)
    width, height = page.get_size()
    if not all(math.isfinite(value) for value in (width, height)) or min(width, height) <= 0 or width * height > MAX_PAGE_PIXELS:
        raise NoteError("Tutorial PDF page exceeds raster geometry bound")
    bitmap = page.render(scale=1)
    try:
        image = bitmap.to_pil()
        try:
            converted = image.convert("RGB")
            try:
                with BoundedEncoding(remaining_bytes) as buffer:
                    converted.save(buffer, format="PNG")
                    data = buffer.getvalue()
            finally:
                converted.close()
        finally:
            image.close()
    finally:
        bitmap.close()
    check_worker(cancelled, deadline)
    pixel_width, pixel_height = png_shape(data, MAX_PAGE_PIXELS)
    return {**write_bytes(directory / f"page-{index:02d}.png", data),
            "width": pixel_width, "height": pixel_height}


def _decoded_page(page, index, directory, remaining, cancelled, deadline):
    try:
        text_page = page.get_textpage()
        try:
            text = text_page.get_text_bounded()
            if len(text) > 32768:
                raise NoteError("Tutorial decoded page text exceeds bound")
        finally:
            text_page.close()
        artifact = _page_artifact(page, index, directory, remaining, cancelled, deadline)
        return text, artifact
    finally:
        page.close()


def _verify_pdf(pdf, document, frames, directory, cancelled, deadline):
    """Decode every text page and raster under one locked, bounded native lifetime."""
    while not PDFIUM_LOCK.acquire(timeout=min(0.05, max(0, deadline - time.monotonic()))):
        check_worker(cancelled, deadline)
    try:
        check_worker(cancelled, deadline)
        opened = _pdfium_module().PdfDocument(read_bytes(pdf["path"], MAX_PDF_BYTES))
        try:
            count = len(opened)
            if not 1 <= count <= MAX_PAGES:
                raise NoteError("Tutorial PDF must have 1..40 decoded pages")
            pages, texts, pixels, consumed = [], [], 0, 0
            for index in range(count):
                check_worker(cancelled, deadline)
                text, artifact = _decoded_page(opened[index], index + 1, directory,
                    MAX_PAGE_BYTES - consumed, cancelled, deadline)
                consumed += artifact["bytes"]
                pixels += artifact["width"] * artifact["height"]
                if pixels > MAX_TOTAL_PAGE_PIXELS:
                    raise NoteError("Tutorial pages exceed24million aggregate raster pixels")
                texts.append(text)
                pages.append(artifact)
        finally:
            opened.close()
    finally:
        PDFIUM_LOCK.release()
    actual = "".join("".join(texts).split())
    required = [document["title"], document["source"]["sha256"], document["manifest_sha256"]]
    required.extend(value for step in document["steps"] for value in (step["title"], step["instruction"]))
    required.extend(caption(frame) for frame in frames)
    if any("".join(value.split()) not in actual for value in required):
        raise NoteError("Tutorial PDF decoded text is missing required source/step/frame provenance")
    check_worker(cancelled, deadline)
    return pages


def render_verified(document, frames, buffers, directory, cancelled, deadline):
    """Create and read back all native pages before any final PDF promotion."""
    pdf, layout = _create_pdf(document, frames, buffers, directory, cancelled, deadline)
    pages = _verify_pdf(pdf, document, frames, directory, cancelled, deadline)
    return pdf, pages, layout
