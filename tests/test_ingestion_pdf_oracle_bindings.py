"""Pure-byte and mocked composition boundaries; Root alone runs these tests."""

import copy
import hashlib
import json
import sys
import zlib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_research_mcp import ingestion_pdf as pdf
from video_research_mcp import ingestion_pdf_pixels as pixels
from video_research_mcp.ingestion_pdf_provenance import classic_xref, direct_image, image_bindings
from video_research_mcp.ingestion_pdf_rulings import attach_rulings, validate_rulings
from tests.test_ingestion_pdf_content import FakeImage, install_fake_api, layout
from tests.test_ingestion_pdf_content import admitted as admitted, runtime as runtime


def simple_pdf(rgb=b"\x40\x80\xc0", *, image_fields=None, duplicate=False):
    """Build a real bounded Catalog/page tree and direct-Length RGB image, with exact xref."""
    stream = zlib.compress(rgb)
    fields = image_fields or f"/Length {len(stream)} /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode".encode()
    contents = b"q 18 0 0 18 72 640 cm /Im1 Do Q"
    bodies = [b"<< /Type /Catalog /Pages 2 0 R >>",
              b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
              b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Rotate 0 /Resources << >> /Contents 4 0 R >>",
              b"<< /Length 0 >>\nstream\n\nendstream",
              b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Rotate 0 /Resources << /XObject << /Im1 8 0 R >> >> /Contents 6 0 R >>",
              b"<< /Length " + str(len(contents)).encode() + b" >>\nstream\n" + contents + b"\nendstream",
              b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
              b"<< " + fields + b" >>\nstream\n" + stream + b"\nendstream"]
    if duplicate:
        bodies.append(bodies[-1])
    data, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(bodies)+1}\n".encode() + b"0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    data += f"trailer\n<< /Size {len(bodies)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return data, stream


def page_records(source_sha):
    """Represent measured pages with explicit rotation method, including no-image page one."""
    return [{"page": n, "page_width": 612., "page_height": 792., "rotation_degrees": 0,
             "rotation_direction": "clockwise", "units": "PDF_canvas_units",
             "source_pdf_sha256": source_sha, "method": "pdfium-page-geometry-v1"} for n in (1, 2)]


def table_and_rulings():
    """Use a complete three-by-two line grid with positioned content cells."""
    table = {"page": 1, "rows": 3, "columns": 2, "page_width": 612., "page_height": 792.,
             "source_pdf_sha256": "a"*64, "bbox": [80.,110.,248.,181.],
             "cells": [{"row": r, "column": c, "bbox": [80+c*128,110+r*30,120+c*128,121+r*30]}
                       for r in range(3) for c in range(2)]}
    lines = [[72,y,360,y] for y in (690,660,630,600)] + [[x,600,x,690] for x in (72,200,360)]
    records = [{"page": 1, "object_ordinal": i, "points": line, "source_pdf_sha256": "a"*64,
                "method": "pdfium-identity-stroked-line-v1", "clip_path_count": 0} for i, line in enumerate(lines)]
    return table, records


@pytest.fixture
def bound_image(tmp_path):
    """Retain independently generated source, native-stream and Poppler descriptor domains."""
    source, directory = tmp_path / "original.pdf", tmp_path / "derived"
    directory.mkdir()
    data, stream = simple_pdf()
    source.write_bytes(data)
    (directory / "pdfium-2-2.stream").write_bytes(stream)
    descriptor = {"page": 2, "number": 0, "type": "image", "width": 1, "height": 1,
                  "object_number": 8, "object_generation": 0, "pixel_bytes_exported": False,
                  "source_role": "original PDF image object"}
    (directory / "pdf-image-2-0.json").write_bytes(pixels.encoded(descriptor))
    record = {"page": 2, "object_ordinal": 2, "width": 1, "height": 1, "colorspace": 2,
              "filters": ["FlateDecode"], "stream": "pdfium-2-2.stream",
              "raw_stream_sha256": hashlib.sha256(stream).hexdigest(),
              "pixel_sha256": hashlib.sha256(b"\x40\x80\xc0").hexdigest()}
    return source, directory, record, descriptor


def test_exact_original_range_and_distinct_rgb_commitments(bound_image):
    source, directory, record, _ = bound_image
    data = source.read_bytes()
    links, limits = image_bindings([record], directory, pixels.file_record(source))
    assert limits == [] and len(links) == 1
    link = links[0]
    start, end = link["source_stream_range"]
    assert data[start:end] == (directory / record["stream"]).read_bytes()
    assert link["source_stream_length"] == end-start
    assert link["object_number"] == 8 and link["object_ordinal"] == 2
    assert link["object_generation"] == 0 and link["source_colorspace"] == "DeviceRGB"
    assert link["raw_stream_sha256"] != link["pixel_sha256"]
    assert link["raw_stream_sha256"] == hashlib.sha256(data[start:end]).hexdigest()
    assert link["pixel_sha256"] == hashlib.sha256(zlib.decompress(data[start:end])).hexdigest()
    assert "inference" in link["trust_boundary"]


@pytest.mark.parametrize("mutation", ["root", "generation", "free", "offset", "length", "trailing", "prev", "xrefstream"])
def test_canonical_source_rejects_wrong_root_liveness_and_framing(mutation):
    data, _ = simple_pdf()
    entries, xref = classic_xref(data)
    if mutation == "root":
        data = data.replace(b"/Root 1 0 R", b"/Root 8 0 R")
    elif mutation in {"generation", "free", "offset"}:
        row = f"{entries[8][0]:010d} 00000 n ".encode()
        altered = {"generation": row.replace(b"00000 n", b"00001 n"),
                   "free": row.replace(b" n ", b" f "),
                   "offset": f"{entries[8][0]+1:010d} 00000 n ".encode()}[mutation]
        data = data.replace(row, altered)
    elif mutation == "length":
        start, length, _, _ = direct_image(data, entries, xref, 8, 0)
        data = data.replace(f"/Length {length}".encode(), f"/Length {length-1}".encode())
        with pytest.raises(ValueError):
            direct_image(data, entries, xref, 8, 0)
        assert start > 0
        return
    elif mutation == "trailing":
        data += b"unexpected"
    elif mutation == "prev":
        data = data.replace(b"/Root", b"/Prev")
    else:
        data = data[:xref] + data[xref:].replace(b"xref\n", b"xxxx\n", 1)
    with pytest.raises(ValueError):
        classic_xref(data)


@pytest.mark.parametrize("mutation", ["sourcehash", "sourcebytes", "rawhash", "rgbhash", "color", "nativewidth", "popplerwidth", "generation", "duplicate_descriptor", "duplicate_native", "duplicate_source", "filter"])
def test_composed_candidates_abstain_on_disagreement(bound_image, mutation):
    source, directory, record, descriptor = bound_image
    binding = pixels.file_record(source)
    records = [record]
    if mutation == "sourcehash":
        binding["sha256"] = "0"*64
    elif mutation == "sourcebytes":
        binding["bytes"] += 1
    elif mutation in {"rawhash", "rgbhash", "color", "nativewidth", "filter"}:
        key, value = {"rawhash": ("raw_stream_sha256", "0"*64), "rgbhash": ("pixel_sha256", "0"*64),
                      "color": ("colorspace", 1), "nativewidth": ("width", 2),
                      "filter": ("filters", [])}[mutation]
        record[key] = value
    elif mutation == "duplicate_native":
        records.append({**record, "object_ordinal": 3})
    elif mutation == "duplicate_source":
        source.write_bytes(simple_pdf(duplicate=True)[0])
        binding = pixels.file_record(source)
    else:
        if mutation == "popplerwidth":
            descriptor["width"] = 2
        elif mutation == "generation":
            descriptor["object_generation"] = 1
        (directory / "pdf-image-2-0.json").write_bytes(pixels.encoded(descriptor))
        if mutation == "duplicate_descriptor":
            (directory / "pdf-image-2-1.json").write_bytes(pixels.encoded(descriptor))
    links, limits = image_bindings(records, directory, binding)
    assert links == [] and limits


@pytest.mark.parametrize("fields", [b"/Length 11 /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode",
    b"/Length 11 /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Decode [0 1]",
    b"/Length 11 /Type /XObject /Subtype /Image /Width 9999999 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode"])
def test_unsupported_image_dictionary_does_not_claim_source_range(fields):
    data, _ = simple_pdf(image_fields=fields)
    entries, xref = classic_xref(data)
    with pytest.raises(ValueError):
        direct_image(data, entries, xref, 8, 0)


def test_complete_grid_preserves_content_and_reports_ruling_region():
    table, records = table_and_rulings()
    pages = pdf._page_geometry(page_records("a"*64), {"sha256": "a"*64})
    attached = attach_rulings([table], records, "a"*64, pages)[0]
    assert attached["bbox"] == [72,102,360,192]
    assert attached["content_bbox"] == [80.,110.,248.,181.]
    assert attached["bbox_role"] == "measured_ruling_centerline_region"
    assert len(attached["ruling_object_ordinals"]) == 7


@pytest.mark.parametrize("mutation", ["missing", "partial", "duplicate_line", "outside_cell", "duplicate_cell", "bad_index", "ambiguous_table", "page_size", "rotated"])
def test_partial_ambiguous_or_mismatched_grid_abstains(mutation):
    table, records = table_and_rulings()
    pages = pdf._page_geometry(page_records("a"*64), {"sha256": "a"*64})
    tables = [table]
    if mutation == "missing":
        records.pop()
    elif mutation == "partial":
        records[0]["points"][2] -= 1
    elif mutation == "duplicate_line":
        records[-1]["points"] = records[-2]["points"][:]
    elif mutation == "outside_cell":
        table["cells"][0]["bbox"][0] = 0
    elif mutation == "duplicate_cell":
        table["cells"][1] = copy.deepcopy(table["cells"][0])
    elif mutation == "bad_index":
        table["cells"][0]["row"] = -1
    elif mutation == "ambiguous_table":
        tables.append(copy.deepcopy(table))
    elif mutation == "page_size":
        table["page_width"] = 613.
    else:
        pages[1]["rotation_degrees"] = 90
        records = []
    original = table["bbox"][:]
    attached = attach_rulings(tables, records, "a"*64, pages)[0]
    assert attached["bbox"] == original and attached["bbox_role"] == "text_content_bounds"
    assert "abstained" in attached["ruling_limitation"]


@pytest.mark.parametrize("field,value", [("page", 3), ("object_ordinal", -1), ("source_pdf_sha256", "b"*64),
    ("method", "oracle"), ("points", [0, 0, float("nan"), 10]), ("points", [0, 0, 700, 10])])
def test_parent_rejects_unbound_ruling_records(field, value):
    _, records = table_and_rulings()
    pages = pdf._page_geometry(page_records("a"*64), {"sha256": "a"*64})
    records[0][field] = value
    with pytest.raises(ValueError):
        validate_rulings(records, "a"*64, pages)


def test_parent_rejects_duplicate_and_rotated_ruling_occurrences():
    _, records = table_and_rulings()
    pages = pdf._page_geometry(page_records("a"*64), {"sha256": "a"*64})
    with pytest.raises(ValueError):
        validate_rulings(records + [records[0]], "a"*64, pages)
    pages[1]["rotation_degrees"] = 90
    with pytest.raises(ValueError):
        validate_rulings(records, "a"*64, pages)


@pytest.mark.parametrize("field,value", [("page", 2), ("source_pdf_sha256", "b"*64), ("rotation_degrees", 45),
    ("rotation_degrees", False), ("page_width", float("nan")), ("page_height", 0.),
    ("method", "authored"), ("units", "pixels"), ("rotation_direction", "unknown")])
def test_page_geometry_rejects_forged_measurements(field, value):
    pages = page_records("a"*64)
    pages[0][field] = value
    with pytest.raises(ValueError):
        pdf._page_geometry(pages, {"sha256": "a"*64})


def test_poppler_native_page_disagreement_is_not_silently_bound():
    pages = pdf._page_geometry(page_records("a"*64), {"sha256": "a"*64})
    with pytest.raises(ValueError, match="dimension"):
        pdf.validate_layout_pages(layout().replace(b'width="612"', b'width="613"'), pages)
    with pytest.raises(ValueError, match="count"):
        pdf.validate_layout_pages(layout(), {1: pages[1]})


def test_pixel_provenance_abstention_keeps_valid_base_behavior(admitted, monkeypatch):
    source, directory, descriptor, path = admitted
    image = FakeImage()
    install_fake_api(monkeypatch, descriptor["runtime"], image)
    pixels.worker(path, source, directory)
    segments, limits = pdf._pixel_result(directory, {path.name}, descriptor["input"], descriptor["runtime"], descriptor["reserve_bytes"])
    assert len(segments) == 1 and segments[0].location.bbox == [20.,742.,60.,762.]
    assert any("correspondence abstained" in s for s in limits)
    assert not (directory / "pdf-original-image-bindings.json").exists()


def path_api(raw):
    """Mock the exact selected ctypes signatures, keeping non-null handles distinct."""
    raw.FPDF_FILLMODE_NONE = 0
    raw.FPDF_SEGMENT_MOVETO, raw.FPDF_SEGMENT_LINETO = 2, 0
    raw.FPDFPageObj_GetClipPath = lambda obj: None if getattr(obj, "null_clip", False) else obj
    raw.FPDFClipPath_CountPaths = lambda obj: obj.clip_count
    raw.FPDFPageObj_HasTransparency = lambda obj: getattr(obj, "transparent", False)
    raw.FPDFPath_CountSegments = lambda _: 2
    raw.FPDFPath_GetPathSegment = lambda obj, n: (obj, n)
    raw.FPDFPathSegment_GetType = lambda seg: (2, 0)[seg[1]]
    raw.FPDFPathSegment_GetClose = lambda _: False
    def draw(_, fill, stroke):
        fill.value, stroke.value = 0, 1
        return True
    def point(seg, x, y):
        obj, n = seg
        x.value, y.value = obj.points[2*n:2*n+2]
        return True
    raw.FPDFPath_GetDrawMode = draw
    raw.FPDFPathSegment_GetPoint = point
    return raw


def fake_path(points, count=0):
    """Represent a valid measured identity stroke with a controlled clip reference count."""
    return SimpleNamespace(type=2, points=points, clip_count=count,
        get_matrix=lambda: SimpleNamespace(get=lambda: (1,0,0,1,0,0)))


@pytest.mark.parametrize("count,accepted", [(-2, False), (-1, True), (0, True), (1, False), (3, False)])
def test_clip_counts_are_distinguished_under_valid_handle_precondition(count, accepted):
    obj = fake_path([10.,20.,30.,20.], count)
    raw = path_api(SimpleNamespace())
    identity = {"page": 1, "source_pdf_sha256": "a"*64}
    if accepted:
        record = pixels._ruling(obj, raw, identity, 2)
        assert record["clip_path_count"] == count and record["points"] == obj.points
    else:
        with pytest.raises(ValueError):
            pixels._ruling(obj, raw, identity, 2)
    obj.null_clip = True
    with pytest.raises(ValueError):
        pixels._ruling(obj, raw, identity, 2)


@pytest.mark.parametrize("rejected", ["form", "clipped", "transformed", "volume"])
def test_rejected_same_page_path_or_form_discards_entire_grid(admitted, monkeypatch, rejected):
    source, directory, descriptor, path = admitted
    image = FakeImage()
    _, lines = table_and_rulings()
    paths = [fake_path(r["points"]) for r in lines]
    if rejected == "form":
        paths.append(SimpleNamespace(type=5))
    elif rejected == "volume":
        paths *= 600
        descriptor["elements"] = 0
        # Keep the original 4096 work bound; 3999 path observations hit the result cap.
        paths = paths[:3999]
    else:
        extra = fake_path([1.,1.,2.,1.], 1 if rejected == "clipped" else 0)
        if rejected == "transformed":
            extra.get_matrix = lambda: SimpleNamespace(get=lambda: (2,0,0,2,0,0))
        paths.append(extra)
    install_fake_api(monkeypatch, descriptor["runtime"], image, objects=paths + [image])
    path_api(sys.modules["pypdfium2_raw"])
    pixels.worker(path, source, directory)
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    assert result["rulings"] == [] and len(result["images"]) == 1
    assert any("all rulings abstained" in s for s in result["limitations"])
    assert (directory / "pdfium-result.json").stat().st_size <= pixels.RESULT_BYTES


async def test_original_mode_composes_measured_pages_grid_and_source_rgb(admitted, monkeypatch):
    """GIVEN unchanged input domains WHEN composing THEN C2/C3/C4 metadata share the source."""
    source, directory, descriptor, old_path = admitted
    original, _ = simple_pdf()
    source.write_bytes(original)
    old_path.unlink()
    image = FakeImage()
    image.rgb = b"\x40\x80\xc0"
    image.stream = zlib.compress(image.rgb)
    image.meta.width = 1
    image.get_px_size = lambda: (1, 1)
    _, lines = table_and_rulings()
    page2 = install_fake_api(monkeypatch, descriptor["runtime"], image,
                             objects=[SimpleNamespace(type=1), SimpleNamespace(type=1), image])
    page1 = SimpleNamespace(**vars(page2))
    paths = [fake_path(r["points"], -1) for r in lines]
    page1.get_objects = lambda **_: iter(paths)
    page1.object_count = len(paths)
    class Document:
        def __len__(self):
            return 2
        def __getitem__(self, number):
            return (page1, page2)[number]
    sys.modules["pypdfium2"].PdfDocument = lambda _: nullcontext(Document())
    path_api(sys.modules["pypdfium2_raw"])
    profile = {"executables": {n: {"path": n} for n in ("pdftotext", "pdfimages")}, "pixels": descriptor["runtime"]}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    async def run(command, timeout):
        assert 0 < timeout <= 30
        if command[0] == "pdftotext":
            return layout(), b""
        if command[0] == "pdfimages":
            return b"2 0 image 1 1 rgb 3 8 image no 8 0 72 72 11B 10%\n", b""
        pixels.worker(Path(command[5]), Path(command[6]), Path(command[7]))
        return b"", b""
    monkeypatch.setattr(pdf, "run_media_process", run)
    parsed = await pdf.parse_pdf_source(source, directory, profile, 30)
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    assert [(p["page"], p["rotation_degrees"], p["method"]) for p in result["pages"]] == [
        (1, 0, "pdfium-page-geometry-v1"), (2, 0, "pdfium-page-geometry-v1")]
    assert len(result["rulings"]) == 7 and all(r["page"] == 1 for r in result["rulings"])
    recovered = json.loads((directory / "pdf-tables.json").read_bytes())["tables"][0]
    assert recovered["bbox"] == [72.,102.,360.,192.]
    assert [s.text for s in parsed.segments if s.kind == "table_cell"] == ["Item","Reading","Rotor","12","Guard","Amber"]
    binding = json.loads((directory / "pdf-original-image-bindings.json").read_bytes())["images"][0]
    assert (binding["page"], binding["object_number"], binding["object_generation"], binding["object_ordinal"]) == (2,8,0,2)
    assert binding["source_colorspace"] == "DeviceRGB" and binding["source_pdf_sha256"] == hashlib.sha256(original).hexdigest()
    assert len([s for s in parsed.segments if s.kind == "image"]) == 2
    assert pixels.usage(directory)[1] + 1 <= 64
    assert pixels.usage(directory)[0] + len(pixels.encoded(parsed.model_dump(mode="json"))) <= pixels.MAX_BYTES


@pytest.mark.parametrize("mutation", ["rotation", "page_size", "duplicate_image", "image_ruling_overlap", "result_bytes"])
def test_parent_rejects_composed_invalid_native_observations(admitted, monkeypatch, mutation):
    source, directory, descriptor, path = admitted
    install_fake_api(monkeypatch, descriptor["runtime"], FakeImage())
    pixels.worker(path, source, directory)
    result_path = directory / "pdfium-result.json"
    result = json.loads(result_path.read_bytes())
    if mutation == "rotation":
        result["pages"][0]["rotation_degrees"] = 90
    elif mutation == "page_size":
        result["pages"][0]["page_width"] += 1
    elif mutation == "duplicate_image":
        result["images"].append(copy.deepcopy(result["images"][0]))
    elif mutation == "image_ruling_overlap":
        record = result["images"][0]
        result["rulings"] = [{"page": 1, "object_ordinal": record["object_ordinal"],
            "points": [20.,30.,60.,30.], "source_pdf_sha256": descriptor["input"]["sha256"],
            "clip_path_count": 0, "method": "pdfium-identity-stroked-line-v1"}]
    else:
        result["limitations"] = ["x" * pixels.RESULT_BYTES]
    result_path.write_bytes(pixels.encoded(result))
    with pytest.raises(ValueError):
        pdf._pixel_result(directory, {path.name}, descriptor["input"], descriptor["runtime"], descriptor["reserve_bytes"])


async def test_original_file_budget_reserves_content_tables_before_optional_pixels(admitted, monkeypatch):
    source, directory, descriptor, path = admitted
    path.unlink()
    for n in range(61):
        (directory / f"existing-{n}").write_bytes(b"x")
    profile = {"executables": {n: {"path": n} for n in ("pdftotext", "pdfimages")}, "pixels": descriptor["runtime"]}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    async def run(command, timeout):
        if command[0] == "pdftotext":
            return layout(), b""
        assert command[0] == "pdfimages", "Optional worker must abstain at the file cap"
        return b"", b""
    monkeypatch.setattr(pdf, "run_media_process", run)
    parsed = await pdf.parse_pdf_source(source, directory, profile, 30)
    assert len([s for s in parsed.segments if s.kind == "table_cell"]) == 6
    assert pixels.usage(directory)[1] + 1 == 64
    assert any("budget" in s for s in parsed.limitations)
    assert not (directory / "pdfium-result.json").exists()


@pytest.mark.parametrize("geometry", ["a4_float32", "rotation", "crop", "population"])
async def test_page_geometry_disagreement_preserves_base_journey(tmp_path, monkeypatch, geometry):
    """GIVEN valid base outputs WHEN optional page geometry disagrees THEN only refinement abstains."""
    source, directory = tmp_path / "original.pdf", tmp_path / "derived"
    source.write_bytes(simple_pdf()[0])
    directory.mkdir()
    data = layout()
    if geometry == "a4_float32":
        data = data.replace(b'width="612" height="792"', b'width="595.276" height="841.89"', 1)
    profile = {"executables": {n: {"path": n} for n in ("pdftotext", "pdfimages")}, "pixels": {}}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    async def run(command, timeout):
        return (data if command[0] == "pdftotext" else b"2 0 image 1 1 rgb 3 8 image no 8 0 72 72 11B 10%\n"), b""
    monkeypatch.setattr(pdf, "run_media_process", run)
    retained = {}
    async def native(path, output, original, runtime, segments, deadline):
        retained["table"] = (output / "pdf-tables.json").read_bytes()
        retained["segments"] = [s.model_dump(mode="json") for s in segments]
        pages = page_records(original["sha256"])
        width, height, rotation = {"a4_float32": (595.2760009765625, 841.8900146484375, 0),
                                  "rotation": (792., 612., 90), "crop": (600., 780., 0),
                                  "population": (612., 792., 0)}[geometry]
        pages[0].update(page_width=width, page_height=height, rotation_degrees=rotation)
        if geometry == "population":
            pages.append({**pages[-1], "page": 3})
        pixels.write_output(output, "pdfium-result.json", pixels.encoded({"pages": pages, "rulings": []}))
        ppm = pixels.write_output(output, "retained.ppm", b"P6\n1 1\n255\n\x40\x80\xc0")
        retained["ppm"] = ppm.read_bytes()
        return [pdf.IngestionSegment(id="retained-pixel", kind="image", artifact=str(ppm),
            location=pdf.IngestionLocation(page=2, image="pdfium-object:2"), method="pdfium-source-rgb-v1")], []
    monkeypatch.setattr(pdf, "_pixels", native)
    parsed = await pdf.parse_pdf_source(source, directory, profile, 30)
    assert [s.model_dump(mode="json") for s in parsed.segments[:-1]] == retained["segments"]
    assert len([s for s in parsed.segments if s.kind == "table_cell"]) == 6
    assert len([s for s in parsed.segments if s.kind == "text"]) == 7
    assert len([s for s in parsed.segments if s.kind == "image"]) == 2
    assert (directory / "pdf-tables.json").read_bytes() == retained["table"]
    assert (directory / "retained.ppm").read_bytes() == retained["ppm"]
    assert "Measured table region abstained: Poppler/PDFium page geometry disagreement" in parsed.limitations
    assert source.read_bytes() == simple_pdf()[0]


def test_no_table_skips_optional_page_comparison(tmp_path, monkeypatch):
    """No table means neither native metadata nor cross-parser comparison is needed."""
    (tmp_path / "pdfium-result.json").write_bytes(b"not read: validated upstream, irrelevant here")
    def compare(*_):
        pytest.fail("Cross-parser comparison must not run without a table")
    monkeypatch.setattr(pdf, "validate_layout_pages", compare)
    assert pdf._refine_tables(b"not parsed", {"sha256": "a"*64}, tmp_path, []) == []


def test_source_binding_error_is_not_optional_geometry_abstention(tmp_path):
    table, _ = table_and_rulings()
    (tmp_path / "pdf-tables.json").write_bytes(pixels.encoded({"tables": [table]}))
    (tmp_path / "pdfium-result.json").write_bytes(pixels.encoded({"pages": page_records("b"*64), "rulings": []}))
    with pytest.raises(ValueError, match="source-bound"):
        pdf._refine_tables(layout(), {"sha256": "a"*64}, tmp_path, [])


async def test_native_worker_failure_remains_terminal(bound_image, monkeypatch):
    source, directory, _, _ = bound_image
    profile = {"executables": {n: {"path": n} for n in ("pdftotext", "pdfimages")}, "pixels": {}}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    async def run(command, timeout):
        return (layout() if command[0] == "pdftotext" else b""), b""
    async def native(*_):
        raise RuntimeError("native worker failure retained")
    monkeypatch.setattr(pdf, "run_media_process", run)
    monkeypatch.setattr(pdf, "_pixels", native)
    with pytest.raises(RuntimeError, match="native worker failure retained"):
        await pdf.parse_pdf_source(source, directory, profile, 30)
