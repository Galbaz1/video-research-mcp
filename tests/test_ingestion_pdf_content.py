"""Provider-free PDF content boundaries; native acceptance is a separate epoch."""

import asyncio
import hashlib
import importlib
import json
import stat
import sys
import zlib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from video_research_mcp import ingestion_pdf as pdf
from video_research_mcp import ingestion_pdf_pixels as pixels
from video_research_mcp.ingestion_pdf_tables import rectangular_tables


def layout(rows=None):
    """Build measured development geometry, including a second prose page."""
    rows = rows or [["Item", "Reading"], ["Rotor", "12"], ["Guard", "Amber"]]
    words = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            x, y = 80 + c * 128, 110 + r * 30
            words.append(f'<word xMin="{x}" yMin="{y}" xMax="{x+40}" yMax="{y+11}">{text}</word>')
    return ('<html xmlns="http://www.w3.org/1999/xhtml"><page width="612" height="792">'
            + ''.join(words) + '</page><page width="612" height="792">'
            '<word xMin="72" yMin="40" xMax="100" yMax="51">Prose.</word></page></html>').encode()


async def test_rectangular_cells_preserve_original_geometry(tmp_path, monkeypatch):
    """GIVEN measured XML WHEN parsing THEN cells retain the source page and artifact."""
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF-test-only")
    derived = tmp_path / "derived"
    derived.mkdir()
    profile = {"executables": {name: {"path": name} for name in ("pdftotext", "pdfimages")},
               "pixels": {"available": False, "limitation": "PDFium runtime unavailable"}}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    monkeypatch.setattr(pdf, "run_media_process", AsyncMock(side_effect=[(layout(), b""), (b"", b"")]))
    parsed = await pdf.parse_pdf_source(source, derived, profile, 30)
    cells = [s for s in parsed.segments if s.kind == "table_cell"]
    assert [s.text for s in cells] == ["Item", "Reading", "Rotor", "12", "Guard", "Amber"]
    assert [(s.location.table, s.location.row, s.location.column) for s in cells] == [
        (0, r, c) for r in range(3) for c in range(2)]
    assert all(s.location.page == 1 and s.artifact for s in cells)
    table = json.loads(Path(cells[0].artifact).read_bytes())["tables"][0]
    assert table["source_pdf_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert table["raw_xml_sha256"] == hashlib.sha256(layout()).hexdigest()
    assert table["cells"][0]["source_word_ordinals"] == [0]
    assert table["cells"][0]["bbox"] == [80., 110., 120., 121.]
    assert "semantic accuracy unknown" in table["limitations"]
    assert (derived / "pdf-layout.xml").read_bytes() == layout()
    assert len([s for s in parsed.segments if s.kind == "text"]) == 7
    assert any("unavailable" in s for s in parsed.limitations)


@pytest.mark.parametrize("mutate", [
    lambda x: x.replace(b'xMin="208"', b'xMin="211"', 1),
    lambda x: x.replace(b'yMin="170"', b'yMin="180"').replace(b'yMax="181"', b'yMax="191"'),
    lambda x: x.replace(b'xMin="208"', b'xMin="140"'),
    lambda x: x.replace(b'width="612"', b'width="240"'),
    lambda x: x.replace(b'xMin="80"', b'xMin="nan"', 1),
    lambda x: x.replace(b'xMin="208"', b'xMin="110"'),
    lambda x: x.replace(b'>Guard<', b'>Guard.<'),
    lambda x: x.replace(b'<word xMin="208" yMin="140" xMax="248" yMax="151">12</word>', b''),
])
def test_ambiguous_geometry_and_prose_abstain(mutate):
    """GIVEN a broken rectangle WHEN reconstructing THEN no table is claimed."""
    assert rectangular_tables(mutate(layout()), "a" * 64) == []


def test_multiword_cell_retains_native_ordinals():
    """GIVEN an internal small gap WHEN reconstructing THEN both source words survive."""
    data = layout().replace(b'xMax="120" yMax="121">Item</word>',
        b'xMax="100" yMax="121">Item</word><word xMin="104" yMin="110" xMax="130" yMax="121">Name</word>')
    cell = rectangular_tables(data, "a" * 64)[0]["cells"][0]
    assert cell["text"] == "Item Name"
    assert cell["source_word_ordinals"] == [0, 1]
    assert cell["bbox"] == [80., 110., 130., 121.]
    assert (cell["row_span"], cell["column_span"]) == (1, 1)


def test_two_rows_and_too_many_columns_abstain():
    assert rectangular_tables(layout([["A", "B"], ["C", "D"]]), "a"*64) == []
    data = layout([[str(c) for c in range(9)] for _ in range(3)]).replace(b'width="612"', b'width="2000"')
    assert rectangular_tables(data, "a"*64) == []


def test_entity_and_aggregate_elements_rejected(tmp_path):
    directory = tmp_path / "owned-derived"
    directory.mkdir()
    with pytest.raises(ValueError, match="entity"):
        rectangular_tables(b'<!ENTITY x "x">', "a"*64)
    source = {"sha256": "a"*64}
    cells, limitations = pdf._tables(layout(), source, directory, [None]*4091)
    assert cells == [] and any("4096" in s for s in limitations)
    assert not list(directory.iterdir())


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """Use complete fabricated packages and metadata, never installed native imports."""
    root = tmp_path / "selected"
    for name in ("pypdfium2", "pypdfium2_raw", "pypdfium2_cfg", "pypdfium2-5.13.0.dist-info"):
        (root / name).mkdir(parents=True)
    for name in ("pypdfium2/__init__.py", "pypdfium2_raw/__init__.py", "pypdfium2_cfg/__init__.py",
                 "pypdfium2/helper.py", "pypdfium2_raw/libpdfium.dylib",
                 "pypdfium2-5.13.0.dist-info/METADATA", "pypdfium2-5.13.0.dist-info/NOTICE"):
        (root / name).write_bytes(b"fabricated test bytes")
    monkeypatch.setattr(pixels.sysconfig, "get_path", lambda _: str(root))
    interpreter = tmp_path / "selected-python"
    interpreter.write_bytes(b"fabricated interpreter")
    monkeypatch.setattr(sys, "executable", str(interpreter))
    return pixels.pixel_profile()


def test_complete_inventory_rechecks_metadata_additions_and_removals(runtime):
    """GIVEN a selected package WHEN any file changes THEN verification refuses it."""
    pixels.verify_runtime(runtime)
    root = Path(runtime["package_root"])
    assert any(r["path"].endswith("NOTICE") for r in runtime["inventory"])
    extra = root / "pypdfium2" / "new.py"
    extra.write_bytes(b"new")
    with pytest.raises(ValueError, match="inventory"):
        pixels.verify_runtime(runtime)
    extra.unlink()
    notice = root / "pypdfium2-5.13.0.dist-info" / "NOTICE"
    notice.write_bytes(b"changed notice")
    with pytest.raises(ValueError, match="inventory"):
        pixels.verify_runtime(runtime)


def test_missing_backend_profile_does_not_import(tmp_path, monkeypatch):
    interpreter = tmp_path / "selected-python"
    interpreter.write_bytes(b"fabricated interpreter")
    monkeypatch.setattr(sys, "executable", str(interpreter))
    monkeypatch.setattr(pixels.sysconfig, "get_path", lambda _: str(tmp_path))
    monkeypatch.setattr(pixels.importlib, "import_module", lambda _: pytest.fail("foreign import"))
    profile = pixels.pixel_profile()
    assert profile["available"] is False
    assert "unavailable" in profile["limitation"]


@pytest.mark.parametrize("name", ["../escape", "sub/file"])
def test_output_traversal_refused(tmp_path, name):
    with pytest.raises(ValueError, match="traversal"):
        pixels.write_output(tmp_path, name, b"data")


def test_source_and_output_symlinks_refused(tmp_path):
    original = tmp_path / "original"
    original.write_bytes(b"data")
    link = tmp_path / "link"
    link.symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        pixels.file_record(link)
    with pytest.raises(ValueError, match="symlink"):
        pixels.usage(tmp_path)


def test_aggregate_bytes_and_reserved_segment_count(tmp_path):
    directory = tmp_path / "owned-derived"
    directory.mkdir()
    with pytest.raises(ValueError, match="8 MiB"):
        pixels.write_output(directory, "oversized", b"x", pixels.MAX_BYTES)
    for i in range(63):
        (directory / str(i)).write_bytes(b"x")
    with pytest.raises(ValueError, match="64 artifacts"):
        pixels.write_output(directory, "sixty-fourth", b"x")


class FakeImage:
    """Foreign API double with controlled size queries and allocations."""

    type = 3
    rgb = b"\x01\x7f\xff\x03\x06\x09"

    def __init__(self):
        self.stream = zlib.compress(self.rgb)
        self.events = []
        self.filters = ["FlateDecode"]
        self.meta = SimpleNamespace(width=2, height=1, colorspace=2, bits_per_pixel=24)

    def get_px_size(self):
        return 2, 1

    def get_metadata(self):
        return self.meta

    def get_filters(self):
        return self.filters

    def get_bounds(self):
        return 20., 30., 60., 50.

    def get_data(self, decode_simple=False):
        self.events.append(("allocation", decode_simple))
        return self.rgb if decode_simple else self.stream


def raw_api(image, raw_length=None, decoded_length=None):
    """Only native API calls are substituted; allocation/serialization stays real."""
    def query(decoded):
        image.events.append(("length", decoded))
        value = decoded_length if decoded else raw_length
        return value if value is not None else len(image.rgb if decoded else image.stream)
    return SimpleNamespace(FPDF_PAGEOBJ_IMAGE=3, FPDF_PAGEOBJ_FORM=5, FPDF_COLORSPACE_DEVICERGB=2,
        FPDFPage_CountObjects=lambda page: page.object_count,
        FPDFImageObj_GetImageDataRaw=lambda *_: query(False),
        FPDFImageObj_GetImageDataDecoded=lambda *_: query(True))


@pytest.mark.parametrize("raw_length,decoded_length,remaining", [(1000, 6, 20), (10, 5, 100), (0, 6, 100)])
def test_native_lengths_checked_before_allocation(raw_length, decoded_length, remaining):
    image = FakeImage()
    with pytest.raises(ValueError, match="lengths"):
        pixels._image_data(image, raw_api(image, raw_length, decoded_length), remaining)
    assert image.events == [("length", False), ("length", True)]


@pytest.mark.parametrize("attribute,value", [("colorspace", 1), ("bits_per_pixel", 8), ("width", 3)])
def test_unsupported_rgb_metadata_never_allocates(attribute, value):
    image = FakeImage()
    setattr(image.meta, attribute, value)
    with pytest.raises(ValueError, match="Unsupported"):
        pixels._image_data(image, raw_api(image), 1000)
    assert image.events == []


def test_complex_filter_and_changed_lengths_refused():
    image = FakeImage()
    image.filters = ["DCTDecode"]
    with pytest.raises(ValueError, match="filter"):
        pixels._image_data(image, raw_api(image), 1000)
    image.filters = ["FlateDecode"]
    with pytest.raises(ValueError, match="changed"):
        pixels._image_data(image, raw_api(image, raw_length=1), 1000)


def install_fake_api(monkeypatch, runtime, image, *, rotation=0,
                     crop=(0., 0., 612., 792.), effective_box=(0., 0., 612., 792.), objects=None):
    """Supply top-level PDFium doubles without executing foreign implementation."""
    def get_objects(max_depth):
        assert max_depth == 1
        return iter(objects if objects is not None else [SimpleNamespace(type=1), image])
    page = SimpleNamespace(get_size=lambda: (612., 792.), get_rotation=lambda: rotation,
        get_mediabox=lambda **_: (0., 0., 612., 792.),
        get_cropbox=lambda **_: crop, get_bbox=lambda: effective_box,
        get_objects=get_objects, closes=[], close=lambda: page.closes.append(True),
        object_count=len(objects) if objects is not None else 2)
    class Document:
        def __len__(self):
            return 1
        def __getitem__(self, index):
            assert index == 0
            return page
    root = Path(runtime["package_root"])
    modules = {"pypdfium2": SimpleNamespace(PdfDocument=lambda _: nullcontext(Document())),
               "pypdfium2_raw": raw_api(image), "pypdfium2_cfg": SimpleNamespace()}
    for name, module in modules.items():
        module.__file__ = str(root / name / "__init__.py")
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(pixels.importlib, "import_module", lambda name: modules[name])
    monkeypatch.setattr(sys, "path", list(sys.path))
    return page


@pytest.fixture
def admitted(tmp_path, runtime):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF-fabricated-only")
    directory = tmp_path / "derived"
    directory.mkdir()
    descriptor = {"runtime": runtime, "input": pixels.file_record(source), "output": str(directory),
                  "elements": 0, "reserve_bytes": 4096}
    path = pixels.write_output(directory, "pdfium-descriptor.json", pixels.encoded(descriptor))
    return source, directory, descriptor, path


@pytest.mark.parametrize("emitted,non_images", [(0, 1), (4095, 4095)])
def test_worker_exports_distinct_encoded_stream_and_exact_rgb(admitted, monkeypatch, emitted, non_images):
    """GIVEN mocked PDFium WHEN bootstrapping THEN actual files retain both byte domains."""
    source, directory, descriptor, path = admitted
    image = FakeImage()
    descriptor["elements"] = emitted
    path.write_bytes(pixels.encoded(descriptor))
    page = install_fake_api(monkeypatch, descriptor["runtime"], image,
                            objects=[SimpleNamespace(type=1)]*non_images + [image])
    meta_path, search_path = list(sys.meta_path), list(sys.path)
    pixels.worker(path, source, directory)
    assert page.closes == [True]
    assert sys.meta_path == meta_path and sys.path == search_path
    assert "pypdfium2_cfg" in pixels.module_origins(descriptor["runtime"])
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    record = result["images"][0]
    assert (directory / record["stream"]).read_bytes() == image.stream != image.rgb
    assert (directory / record["ppm"]).read_bytes() == b"P6\n2 1\n255\n" + image.rgb
    assert record["pixel_sha256"] == hashlib.sha256(image.rgb).hexdigest()
    assert record["raw_stream_sha256"] == hashlib.sha256(image.stream).hexdigest()
    assert record["object_ordinal"] == non_images
    assert record["native_bbox"] == [20., 30., 60., 50.]
    assert record["bbox"] == [20., 742., 60., 762.]
    assert "mask presence unknown" in record["limitations"]
    assert image.events[:2] == [("length", False), ("length", True)]
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in directory.iterdir())
    segments, _ = pdf._pixel_result(directory, {path.name}, descriptor["input"], descriptor["runtime"])
    assert segments[0].location.bbox == record["bbox"]


@pytest.mark.parametrize("effective_box,exported", [
    ((0., 0., 612., 792.), True), ((0., 0., 600., 792.), False),
])
def test_missing_cropbox_requires_measured_full_page(admitted, monkeypatch, effective_box, exported):
    """An absent explicit CropBox admits only measured, uncropped effective geometry."""
    source, directory, descriptor, path = admitted
    image = FakeImage()
    install_fake_api(monkeypatch, descriptor["runtime"], image, crop=None, effective_box=effective_box)
    pixels.worker(path, source, directory)
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    assert bool(result["images"]) is exported
    if not exported:
        assert result["limitations"] and image.events == []


@pytest.mark.parametrize("mutation", ["source", "notice", "cfg", "worker", "extra", "output"])
def test_bootstrap_refuses_before_foreign_import(admitted, monkeypatch, mutation):
    source, directory, descriptor, path = admitted
    monkeypatch.setattr(pixels.importlib, "import_module", lambda _: pytest.fail("foreign import before admission"))
    if mutation == "source":
        source.write_bytes(b"changed")
    elif mutation == "notice":
        (Path(descriptor["runtime"]["package_root"]) / "pypdfium2-5.13.0.dist-info/NOTICE").unlink()
    elif mutation == "worker":
        descriptor["runtime"]["worker"]["sha256"] = "b"*64
    elif mutation == "cfg":
        (Path(descriptor["runtime"]["package_root"]) / "pypdfium2_cfg/__init__.py").write_bytes(b"drift")
    elif mutation == "extra":
        descriptor["unrecognised"] = True
    else:
        descriptor["output"] = str(directory.parent)
    path.write_bytes(pixels.encoded(descriptor))
    with pytest.raises(ValueError):
        pixels.worker(path, source, directory)


@pytest.mark.parametrize("rotation,crop,objects,emitted", [
    (90, None, None, 0), (0, (0., 0., 600., 792.), None, 0),
    (0, None, [SimpleNamespace(type=5)], 0), (0, None, None, 4096)])
def test_unsupported_page_and_nested_routes_remain_partial(admitted, monkeypatch, rotation, crop, objects, emitted):
    source, directory, descriptor, path = admitted
    descriptor["elements"] = emitted
    path.write_bytes(pixels.encoded(descriptor))
    image = FakeImage()
    install_fake_api(monkeypatch, descriptor["runtime"], image, rotation=rotation, crop=crop, objects=objects)
    pixels.worker(path, source, directory)
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    assert result["images"] == [] and result["limitations"]
    assert image.events == []


@pytest.mark.parametrize("mutation", ["unknown", "traversal", "pixel", "geometry", "symlink"])
def test_parent_rejects_invalid_outputs(admitted, monkeypatch, mutation):
    source, directory, descriptor, path = admitted
    install_fake_api(monkeypatch, descriptor["runtime"], FakeImage())
    pixels.worker(path, source, directory)
    result_path = directory / "pdfium-result.json"
    result = json.loads(result_path.read_bytes())
    record = result["images"][0]
    if mutation == "unknown":
        result["extra"] = 1
    elif mutation == "traversal":
        record["ppm"] = "../escape.ppm"
    elif mutation == "pixel":
        (directory / record["ppm"]).write_bytes(b"P6\n2 1\n255\nBADBAD")
    elif mutation == "geometry":
        record["bbox"][1] = 741.
    else:
        (directory / record["stream"]).unlink()
        (directory / record["stream"]).symlink_to(source)
    result_path.write_bytes(pixels.encoded(result))
    with pytest.raises(ValueError):
        pdf._pixel_result(directory, {path.name}, descriptor["input"], descriptor["runtime"])


async def test_three_commands_share_deadline_and_exact_isolated_argv(admitted, monkeypatch):
    """GIVEN one deadline WHEN commands consume time THEN later budgets shrink."""
    source, directory, descriptor, old_path = admitted
    old_path.unlink()
    install_fake_api(monkeypatch, descriptor["runtime"], FakeImage())
    profile = {"executables": {n: {"path": n} for n in ("pdftotext", "pdfimages")},
               "pixels": descriptor["runtime"]}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    clock, calls = [0.], []
    monkeypatch.setattr(pdf.time, "monotonic", lambda: clock[0])
    async def run(command, timeout):
        calls.append((command, timeout))
        clock[0] += 10
        if len(calls) == 1:
            return layout(), b""
        if len(calls) == 2:
            return b"1 0 image 2 1 rgb 3 8 image no 17 0 72 72 12B 10%\n", b""
        pixels.worker(Path(command[5]), Path(command[6]), Path(command[7]))
        return b"", b""
    monkeypatch.setattr(pdf, "run_media_process", run)
    parsed = await pdf.parse_pdf_source(source, directory, profile, 35.)
    assert [t for _, t in calls] == [30., 25., 15.]
    assert calls[2][0][:5] == [sys.executable, "-I", "-S", "-B", descriptor["runtime"]["worker"]["path"]]
    assert len([s for s in parsed.segments if s.kind == "image"]) == 2
    assert {s.location.image for s in parsed.segments if s.kind == "image"} == {"object:17:0", "pdfium-object:1"}
    assert len(parsed.segments) == 15


async def test_expired_deadline_and_cancellation_do_not_return_partial(tmp_path, monkeypatch):
    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF-fake")
    profile = {"executables": {n: {"path": n} for n in ("pdftotext", "pdfimages")},
               "pixels": {"available": False, "limitation": "unavailable"}}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    runner = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(pdf, "run_media_process", runner)
    with pytest.raises(TimeoutError, match="deadline"):
        await pdf.parse_pdf_source(source, tmp_path, profile, 0.)
    runner.assert_not_called()
    with pytest.raises(asyncio.CancelledError):
        await pdf.parse_pdf_source(source, tmp_path, profile, 30.)
    assert not (tmp_path / "pdf-layout.xml").exists()


@pytest.mark.parametrize("name", ["vrm_unknown_foreign", "pypdfium2_cli", "pypdfium2_cli.tool"])
def test_unknown_import_refused_before_spec_lookup(runtime, monkeypatch, name):
    """No finder/loader for an unselected package may run under the boundary."""
    def lookup(*_):
        pytest.fail("unknown package spec lookup")
    monkeypatch.setattr(pixels.PathFinder, "find_spec", lookup)
    before = sys.meta_path
    with pytest.raises(ImportError, match="before import"), pixels.selected_imports(runtime):
        importlib.import_module(name)
    assert sys.meta_path is before


def test_origin_checked_before_execution_and_stdlib_roots_retained(runtime, monkeypatch):
    """A forged selected-package spec is refused before its loader executes."""
    root = Path(runtime["package_root"])
    executions = []
    spec = SimpleNamespace(origin=str(root / "outside.py"), loader=SimpleNamespace(
        exec_module=lambda _: executions.append(True)))
    monkeypatch.setattr(pixels.PathFinder, "find_spec", lambda *_: spec)
    before, search = sys.meta_path, list(sys.path)
    with pixels.selected_imports(runtime):
        finder = sys.meta_path[0]
        assert finder.find_spec("json") is None
        with pytest.raises(ImportError, match="origin.*before import"):
            finder.find_spec("pypdfium2.helper", [str(root / "pypdfium2")])
        spec.origin = str(root / "pypdfium2/helper.py")
        assert finder.find_spec("pypdfium2.helper", [str(root / "pypdfium2")]) is spec
    assert not executions and sys.meta_path is before and sys.path == search


@pytest.mark.parametrize("failure", ["native", "objects", "drift"])
def test_plain_page_closes_and_drift_never_publishes_result(admitted, monkeypatch, failure):
    source, directory, descriptor, path = admitted
    image = FakeImage()
    page = install_fake_api(monkeypatch, descriptor["runtime"], image,
                            objects=[SimpleNamespace(type=2)]*4097 if failure == "objects" else None)
    if failure == "native":
        image.get_bounds = lambda: (_ for _ in ()).throw(KeyError("native mapping failure"))
    elif failure == "drift":
        original = image.get_data
        def changed(decode_simple=False):
            (Path(descriptor["runtime"]["package_root"]) / "pypdfium2_cfg/__init__.py").write_bytes(b"changed")
            return original(decode_simple)
        image.get_data = changed
    before = sys.meta_path
    with pytest.raises((ValueError, KeyError)):
        pixels.worker(path, source, directory)
    assert page.closes == [True] and sys.meta_path is before
    assert not (directory / "pdfium-result.json").exists()


@pytest.mark.parametrize("name", ["DYLD_TEST_OVERRIDE", "LD_TEST_OVERRIDE"])
async def test_loader_overrides_refused_before_import_and_launch(admitted, monkeypatch, name):
    source, directory, descriptor, path = admitted
    monkeypatch.setenv(name, "test-only")
    monkeypatch.setattr(pixels.importlib, "import_module", lambda _: pytest.fail("foreign import"))
    with pytest.raises(ValueError, match="loader override"):
        pixels.worker(path, source, directory)
    path.unlink()
    monkeypatch.setattr(pdf, "run_media_process", AsyncMock(side_effect=AssertionError("launch")))
    images, limits = await pdf._pixels(source, directory, descriptor["input"], descriptor["runtime"], [], float("inf"))
    assert images == [] and limits == [
        "PDFium pixel export unavailable: loader override environment unsupported; descriptors retained"]
    pdf.run_media_process.assert_not_called()
    assert not (directory / "pdfium-descriptor.json").exists()


@pytest.mark.parametrize("boundary", ["files", "bytes"])
async def test_optional_pixel_budget_abstains_without_writing(admitted, monkeypatch, boundary):
    source, directory, descriptor, path = admitted
    path.unlink()
    if boundary == "files":
        for i in range(62):
            (directory / str(i)).write_bytes(b"x")
    else:
        (directory / "full").write_bytes(b"x" * (pixels.MAX_BYTES - pixels.RESULT_BYTES))
    before = set(directory.iterdir())
    monkeypatch.setattr(pdf, "run_media_process", AsyncMock(side_effect=AssertionError("launch")))
    images, limits = await pdf._pixels(source, directory, descriptor["input"], descriptor["runtime"], [], float("inf"))
    assert images == [] and any("budget" in s for s in limits)
    assert set(directory.iterdir()) == before


def test_worker_reserves_result_body_and_marks_truncated_limitations(admitted, monkeypatch):
    source, directory, descriptor, path = admitted
    images = [FakeImage() for _ in range(25)]
    for image in images:
        image.filters = ["DCTDecode"]
    install_fake_api(monkeypatch, descriptor["runtime"], images[0], objects=images)
    pixels.worker(path, source, directory)
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    assert len(result["limitations"]) == 24
    assert result["limitations"][-1] == "Additional PDFium limitations truncated"
    assert (directory / "pdfium-result.json").stat().st_size <= pixels.RESULT_BYTES
    assert all(not image.events for image in images)


def test_image_exports_leave_result_and_segment_reservation(admitted, monkeypatch):
    source, directory, descriptor, path = admitted
    size, _ = pixels.usage(directory)
    padding = pixels.MAX_BYTES - size - descriptor["reserve_bytes"] - pixels.RESULT_BYTES - 10
    (directory / "padding").write_bytes(b"x" * padding)
    image = FakeImage()
    install_fake_api(monkeypatch, descriptor["runtime"], image)
    pixels.worker(path, source, directory)
    result = json.loads((directory / "pdfium-result.json").read_bytes())
    assert result["images"] == [] and result["limitations"]
    assert image.events == [("length", False), ("length", True)]
    assert pixels.usage(directory)[0] + descriptor["reserve_bytes"] <= pixels.MAX_BYTES


async def test_parse_abstains_cells_preserving_words_and_descriptors(tmp_path, monkeypatch):
    source, directory = tmp_path / "original.pdf", tmp_path / "derived"
    source.write_bytes(b"%PDF-fake")
    directory.mkdir()
    extra = b'<word xMin="72" yMin="40" xMax="100" yMax="51">Prose.</word>' * 4084
    data = layout().replace(b'</page>', extra + b'</page>', 1)
    profile = {"executables": {n: {"path": n} for n in ("pdftotext", "pdfimages")},
               "pixels": {"available": False, "limitation": "unavailable"}}
    monkeypatch.setattr(pdf, "pdf_profile", lambda: profile)
    monkeypatch.setattr(pdf, "run_media_process", AsyncMock(side_effect=[(data, b""),
        (b"1 0 image 2 1 rgb 3 8 image no 17 0 72 72 12B 10%\n", b"")]))
    parsed = await pdf.parse_pdf_source(source, directory, profile, 30)
    assert len(parsed.segments) == 4092 and not any(s.kind == "table_cell" for s in parsed.segments)
    assert parsed.segments[-1].location.image == "object:17:0"
    assert any("4096-element budget" in s for s in parsed.limitations)
    assert (directory / "pdf-layout.xml").read_bytes() == data
    assert not (directory / "pdf-tables.json").exists()


def test_one_tables_artifact_and_whitespace_ordinals(tmp_path):
    directory = tmp_path / "derived"
    directory.mkdir()
    body = layout().split(b'<page', 1)[1].split(b'</page>', 1)[0]
    data = b'<html xmlns="http://www.w3.org/1999/xhtml"><page' + body + b'</page><page' + body + b'</page></html>'
    cells, limits = pdf._tables(data, {"sha256": "a"*64}, directory, [])
    assert len(cells) == 12 and limits == [] and len({s.artifact for s in cells}) == 1
    assert len(json.loads(Path(cells[0].artifact).read_bytes())["tables"]) == 2
    blank = layout().replace(b'<word', b'<word> </word>'*4096 + b'<word', 1)
    assert rectangular_tables(blank, "a"*64)[0]["cells"][0]["source_word_ordinals"] == [4096]


def test_trusted_install_roots_bind_canonical_paths(runtime, monkeypatch):
    root = Path(runtime["package_root"])
    alias = root.parent / "install-link"
    alias.symlink_to(root.parent, target_is_directory=True)
    worker = root.parent / "worker.py"
    worker.write_bytes(b"fabricated worker")
    monkeypatch.setattr(pixels, "__file__", str(alias / worker.name))
    monkeypatch.setattr(pixels.sysconfig, "get_path", lambda _: str(alias / root.name))
    profile = pixels.pixel_profile()
    assert profile["package_root"] == str(root.resolve())
    assert profile["worker"]["path"] == str(worker.resolve())
    pixels.verify_runtime(profile)
