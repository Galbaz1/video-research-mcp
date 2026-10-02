"""Native API edge mocks exercise the renderer contract without rendering a real PDF."""

import json
import math
import struct
import zlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from video_research_mcp.video_note import render
from video_research_mcp.video_note.io import NoteError, digest, write_bytes


def png(width=16, height=10):
    """Independent synthetic RGB PNG fixture; no native media code."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


@pytest.fixture
def document(tmp_path):
    return {"title": "Retained source tutorial", "source": {"sha256": "1" * 64},
            "manifest_sha256": "2" * 64, "warnings": [],
            "steps": [{"title": "Inspect phase", "instruction": "Read literal <b> & source text.",
                       "start_seconds": .4, "end_seconds": .6, "origin": "caller_proposal"}]}


class FakeFPDF:
    """A transparent plaintext/native API recorder, not a PDF writer."""

    latest = None

    def __init__(self, **kwargs):
        self.h, self.y, self.pages = 842, 48, 0
        self.texts, self.images, self.fonts = [], [], []
        FakeFPDF.latest = self

    def set_margins(self, *args):
        self.margins = args

    def set_auto_page_break(self, **kwargs):
        self.breaks = kwargs

    def add_page(self):
        self.pages += 1
        self.y = 48

    def set_font(self, font, size):
        self.fonts.append((font, size))

    def multi_cell(self, **kwargs):
        self.texts.append(kwargs["text"])
        self.y += kwargs["h"]

    def page_no(self):
        return self.pages

    def get_y(self):
        return self.y

    def set_y(self, value):
        self.y = value

    def image(self, data, **kwargs):
        self.images.append({"data": data.getvalue(), "page": self.pages, **kwargs})

    def output(self):
        return bytearray(b"%PDF-synthetic-native-API-recorder")


def test_plaintext_exact_buffers_and_actual_layout(document, tmp_path, monkeypatch):
    data = png()
    frame = {"step_index": 1, "width": 16, "height": 10, "sha256": digest(data),
             "actual_seconds": .5, "original_pts": 5120, "time_base": "1/10240"}
    monkeypatch.setattr(render, "_fpdf_class", lambda: FakeFPDF)
    pdf, layout = render._create_pdf(document, [frame], [data], tmp_path, threading.Event(), time.monotonic() + 2)
    recorder = FakeFPDF.latest
    assert "Read literal <b> & source text." in recorder.texts
    assert document["source"]["sha256"] in "\n".join(recorder.texts)
    assert document["manifest_sha256"] in "\n".join(recorder.texts)
    assert "PTS 5120" in "\n".join(recorder.texts)
    assert recorder.images[0]["data"] == data
    assert set(font for font, _ in recorder.fonts) == {"Helvetica"}
    assert ("Helvetica", 11) in recorder.fonts and ("Helvetica", 8) in recorder.fonts
    actual = json.loads(open(layout["path"]).read())["images"][0]
    placed = recorder.images[0]
    assert actual["page"] == placed["page"] == 2
    for key, point_key in [("x_mm", "x"), ("y_mm", "y"), ("width_mm", "w"), ("height_mm", "h")]:
        assert actual[key] == pytest.approx(placed[point_key] * 25.4 / 72)
    assert actual["png_sha256"] == digest(data)
    assert pdf["sha256"] == digest(open(pdf["path"], "rb").read())


class Handles:
    """Track every simulated native handle, including failure paths."""

    def __init__(self, text, count=2, size=(20, 20), fail=None):
        self.text, self.count, self.size, self.fail = text, count, size, fail
        self.opened, self.closed, self.pages_rendered = [], [], []
        self.active, self.maximum = 0, 0

    def doc(self, data):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        self.opened.append("document")
        owner = self
        class Doc:
            def __len__(self):
                return owner.count
            def __getitem__(self, index):
                return owner.page(index)
            def close(self):
                owner.closed.append("document")
                owner.active -= 1
        return Doc()

    def page(self, index):
        owner = self
        self.opened.append(f"page{index}")
        class Page:
            def get_size(self):
                return owner.size
            def get_textpage(self):
                owner.opened.append(f"text{index}")
                return SimpleNamespace(get_text_bounded=lambda: owner.text,
                    close=lambda: owner.closed.append(f"text{index}"))
            def render(self, scale):
                assert scale == 1
                if owner.fail == "render":
                    raise RuntimeError("controlled native raster failure")
                owner.opened.append(f"bitmap{index}")
                owner.pages_rendered.append(index)
                return SimpleNamespace(to_pil=lambda: owner.image(index),
                    close=lambda: owner.closed.append(f"bitmap{index}"))
            def close(self):
                owner.closed.append(f"page{index}")
        return Page()

    def image(self, index):
        owner = self
        class Image:
            def convert(self, mode):
                assert mode == "RGB"
                return Image()
            def save(self, buffer, format):
                assert format == "PNG"
                time.sleep(.005)
                buffer.write(png(20, 20))
            def close(self):
                owner.closed.append(f"image{index}")
        return Image()


def required_text(document):
    return "\n".join([document["title"], document["source"]["sha256"], document["manifest_sha256"],
                      *[item for step in document["steps"] for item in (step["title"], step["instruction"])]])


def test_every_page_decoded_rasterized_and_closed(document, tmp_path, monkeypatch):
    handles = Handles(required_text(document))
    monkeypatch.setattr(render, "_pdfium_module", lambda: SimpleNamespace(PdfDocument=handles.doc))
    pdf = write_bytes(tmp_path / "document.pdf", b"%PDF-synthetic-native-boundary")
    pages = render._verify_pdf(pdf, document, [], tmp_path, threading.Event(), time.monotonic() + 2)
    assert len(pages) == 2 and handles.pages_rendered == [0, 1]
    assert all(handle in handles.closed for handle in handles.opened)
    assert handles.active == 0 and not render.PDFIUM_LOCK.locked()
    assert all(item["width"] * item["height"] <= 1_000_000 for item in pages)


@pytest.mark.parametrize("failure", ["zero", "41pages", "nonfinite", "oversized", "render", "missing-text", "oversized-text"])
def test_native_qualification_failure_closes_handles(document, tmp_path, monkeypatch, failure):
    handles = Handles(required_text(document))
    if failure == "zero":
        handles.count = 0
    elif failure == "41pages":
        handles.count = 41
    elif failure == "nonfinite":
        handles.size = (math.nan, 20)
    elif failure == "oversized":
        handles.size = (2000, 2000)
    elif failure == "render":
        handles.fail = "render"
    elif failure == "missing-text":
        handles.text = "missing source/step references"
    else:
        handles.text = "x" * 32769
    monkeypatch.setattr(render, "_pdfium_module", lambda: SimpleNamespace(PdfDocument=handles.doc))
    pdf = write_bytes(tmp_path / "document.pdf", b"%PDF-synthetic-native-boundary")
    with pytest.raises((NoteError, RuntimeError)):
        render._verify_pdf(pdf, document, [], tmp_path, threading.Event(), time.monotonic() + 2)
    assert all(handle in handles.closed for handle in handles.opened)
    assert handles.active == 0 and not render.PDFIUM_LOCK.locked()


def test_pdfium_operations_serialized_across_threads(document, tmp_path, monkeypatch):
    handles = Handles(required_text(document), count=1)
    monkeypatch.setattr(render, "_pdfium_module", lambda: SimpleNamespace(PdfDocument=handles.doc))
    def verify(index):
        directory = tmp_path / str(index)
        directory.mkdir()
        pdf = write_bytes(directory / "document.pdf", b"%PDF-synthetic-native-boundary")
        return render._verify_pdf(pdf, document, [], directory, threading.Event(), time.monotonic() + 2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(verify, range(2)))
    assert all(len(result) == 1 for result in results)
    assert handles.maximum == 1 and handles.active == 0


def test_waiting_pdfium_lock_honors_overall_deadline(document, tmp_path):
    pdf = write_bytes(tmp_path / "document.pdf", b"%PDF-synthetic-native-boundary")
    render.PDFIUM_LOCK.acquire()
    try:
        with pytest.raises(TimeoutError):
            render._verify_pdf(pdf, document, [], tmp_path, threading.Event(), time.monotonic() + .01)
    finally:
        render.PDFIUM_LOCK.release()


@pytest.mark.parametrize("versions", [{"fpdf2": "2.8.9", "pypdfium2": "5.13.0"},
                                      {"fpdf2": "1.0", "pypdfium2": "5.13.0"}])
def test_dependency_metadata_major_admission_without_import(versions, monkeypatch):
    import importlib.metadata
    monkeypatch.setattr(importlib.metadata, "version", lambda name: versions[name])
    if versions["fpdf2"].startswith("2."):
        assert render.dependencies_ready() == versions
    else:
        with pytest.raises(ImportError, match="major2"):
            render.dependencies_ready()
