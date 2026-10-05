"""Stdlib bootstrap and bounded PDFium stream/RGB export for one admitted PDF."""

from __future__ import annotations

import hashlib
from ctypes import c_float, c_int
import importlib
import json
import math
import os
import stat
import sys
import sysconfig
from contextlib import contextmanager
from importlib.machinery import PathFinder
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 64
RESULT_BYTES = 128 * 1024
PACKAGES = ("pypdfium2", "pypdfium2_raw", "pypdfium2_cfg")
BOUNDARY = "Selected interpreter, worker, complete three-package/metadata inventory (including bytecode); pypdfium2_cli excluded; host/interpreter initialization/libc/stdlib/native dependency closure and atomic mutation defence unknown; no OS sandbox"
IMAGE_LIMITATIONS = "Masks/compositing, clipping, Decode and color-key masking not applied; mask presence unknown; raw-source-pixel-to-page orientation unknown; source-file byte offset unresolved unless a separate original-image binding is committed; PDFium ordinal is not itself a Poppler object number"
SIMPLE_FILTERS = {"ASCIIHexDecode", "ASCII85Decode", "FlateDecode", "RunLengthDecode", "LZWDecode"}


def regular(path: Path) -> Path:
    """Reject traversal, symlinks and nonregular files at the filesystem boundary."""
    path = path.absolute()
    if ".." in path.parts or any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("PDF path contains traversal or symlink")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("PDF path is not a regular file")
    return path


def file_record(path: Path) -> dict:
    """Hash a regular file without reading its full body into memory."""
    path = regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(65536):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def inventory(root: Path, names: list[str]) -> list[dict]:
    """Bind every selected package/metadata file, including native libraries/notices."""
    records = []
    for name in names:
        directory = root / name
        if Path(name).name != name or directory.is_symlink() or not directory.is_dir():
            raise ValueError("Invalid selected PDFium package directory")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("Selected PDFium inventory contains a symlink")
            if path.is_file():
                records.append(file_record(path))
            elif not path.is_dir():
                raise ValueError("Selected PDFium inventory contains a special file")
    return records


def pixel_profile() -> dict:
    """Select the current interpreter's installed packages without foreign imports."""
    root = Path(sysconfig.get_path("purelib")).resolve()
    worker = file_record(Path(__file__).resolve())
    python = {"selected_path": sys.executable, **file_record(Path(sys.executable).resolve())}
    names = list(PACKAGES)
    metadata = sorted(p.name for p in root.glob("pypdfium2*.dist-info"))
    if not all((root / n).is_dir() for n in names) or not metadata:
        return {"available": False, "limitation": "PDFium runtime unavailable; descriptors retained",
                "worker": worker, "python": python, "checked_boundary": BOUNDARY}
    names += metadata
    return {"available": True, "package_root": str(root), "directories": names,
            "inventory": inventory(root, names), "worker": worker, "python": python,
            "checked_boundary": BOUNDARY}


def encoded(value: dict) -> bytes:
    """Serialize finite canonical JSON matching the ingestion segment encoding."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def usage(directory: Path) -> tuple[int, int]:
    """Count all contained regular outputs; reject subdirectories and links."""
    if directory.is_symlink() or directory.absolute() != directory.resolve():
        raise ValueError("PDF output directory contains a symlink")
    records = [file_record(p) for p in directory.iterdir()]
    return sum(r["bytes"] for r in records), len(records)


def write_output(directory: Path, name: str, data: bytes, reserve: int = 0) -> Path:
    """Create private artifacts only within the original aggregate limits."""
    if Path(name).name != name:
        raise ValueError("PDF output traversal")
    size, count = usage(directory)
    if not data or size + len(data) + reserve > MAX_BYTES or count + 1 >= MAX_FILES:
        raise ValueError("PDF outputs exceed 8 MiB/64 artifacts including segments")
    path = directory / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as writer:
        writer.write(data)
    return path


def verify_runtime(profile: dict) -> None:
    """Recheck the selected runtime before import and after native extraction."""
    if set(profile) != {"available", "package_root", "directories", "inventory", "worker", "python", "checked_boundary"}:
        raise ValueError("Unknown PDFium runtime fields")
    if profile["available"] is not True or profile["checked_boundary"] != BOUNDARY:
        raise ValueError("Invalid PDFium runtime boundary")
    if file_record(Path(__file__).resolve()) != profile["worker"]:
        raise ValueError("PDFium worker binding changed")
    root = Path(profile["package_root"])
    expected = list(PACKAGES) + sorted(p.name for p in root.glob("pypdfium2*.dist-info"))
    if len(expected) < 4 or profile["directories"] != expected:
        raise ValueError("PDFium selected package/metadata directories changed")
    python = profile["python"]
    if set(python) != {"selected_path", "path", "bytes", "sha256"} or sys.executable != python["selected_path"] or Path(python["selected_path"]).resolve() != Path(python["path"]):
        raise ValueError("PDFium selected interpreter changed")
    if file_record(Path(sys.executable).resolve()) != {k: python[k] for k in ("path", "bytes", "sha256")}:
        raise ValueError("PDFium interpreter binding changed")
    if inventory(root, profile["directories"]) != profile["inventory"]:
        raise ValueError("PDFium package inventory changed")


def refuse_loader_overrides():
    """Refuse inherited native-loader overrides without exposing their values."""
    if any(name.startswith(("DYLD_", "LD_")) for name in os.environ):
        raise ValueError("PDFium loader override environment is unsupported")


class PdfiumFinder:
    """Admit only selected PDFium specs before their loaders may execute."""

    def __init__(self, profile):
        self.root = profile["package_root"]
        self.records = {r["path"]: r for r in profile["inventory"]}

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top in sys.stdlib_module_names:
            return None
        if top not in PACKAGES:
            raise ImportError("PDFium unselected foreign package refused before import")
        spec = PathFinder.find_spec(fullname, [self.root] if path is None else path, target)
        origin = str(Path(spec.origin).absolute()) if spec and spec.origin else None
        if origin not in self.records or file_record(Path(origin)) != self.records[origin]:
            raise ImportError("PDFium module origin outside selected inventory before import")
        return spec


def module_origins(profile):
    """Validate selected cached modules too, including direct mocked calls."""
    selected = {r["path"] for r in profile["inventory"]}
    origins = {n: str(Path(m.__file__).absolute()) for n, m in list(sys.modules.items())
               if n.split(".")[0] in PACKAGES}
    if any(p not in selected for p in origins.values()):
        raise ImportError("PDFium cached module origin outside selected inventory")
    return origins


@contextmanager
def selected_imports(profile):
    """Keep original stdlib roots and restore the import boundary on every exit."""
    refuse_loader_overrides()
    module_origins(profile)
    previous = sys.meta_path
    sys.meta_path = [PdfiumFinder(profile), *previous]
    try:
        yield
    finally:
        sys.meta_path = previous


def _image_data(image, raw, remaining):
    """Preflight both native lengths before the helper may allocate any data."""
    width, height = image.get_px_size()
    meta = image.get_metadata()
    filters = image.get_filters()
    if (width <= 0 or height <= 0 or meta.width != width or meta.height != height
            or meta.colorspace != raw.FPDF_COLORSPACE_DEVICERGB or meta.bits_per_pixel != 24
            or not set(filters) <= SIMPLE_FILTERS):
        raise ValueError("Unsupported PDFium RGB24/filter route")
    raw_size = raw.FPDFImageObj_GetImageDataRaw(image, None, 0)
    rgb_size = raw.FPDFImageObj_GetImageDataDecoded(image, None, 0)
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    if raw_size <= 0 or rgb_size != 3 * width * height or raw_size + rgb_size + len(header) > remaining:
        raise ValueError("PDFium image lengths exceed remaining budget or RGB dimensions")
    stream = bytes(image.get_data(decode_simple=False))
    rgb = bytes(image.get_data(decode_simple=True))
    if len(stream) != raw_size or len(rgb) != rgb_size:
        raise ValueError("PDFium image lengths changed during allocation")
    return stream, rgb, header, width, height, filters, meta.colorspace


def _export_image(image, raw, directory, identity, reserve):
    """Export original encoded bytes and decoded source pixels with native geometry."""
    left, bottom, right, top = image.get_bounds()
    width, height = identity["page_width"], identity["page_height"]
    if not all(math.isfinite(v) for v in (left, bottom, right, top)) or not (
            0 <= left < right <= width and 0 <= bottom < top <= height):
        raise ValueError("Unsupported PDFium image bounds")
    size, count = usage(directory)
    if count + 4 >= MAX_FILES:
        raise ValueError("PDFium artifact count exceeds remaining budget")
    stream, rgb, header, w, h, filters, colorspace = _image_data(image, raw, MAX_BYTES - size - reserve)
    name = f"pdfium-{identity['page']}-{identity['object_ordinal']}"
    record = {**identity, "native_bbox": [left, bottom, right, top],
              "bbox": [left, height-top, right, height-bottom], "coordinate_origin": "top_left",
              "native_coordinate_origin": "bottom_left",
              "width": w, "height": h, "filters": filters, "colorspace": colorspace,
              "raw_stream_sha256": hashlib.sha256(stream).hexdigest(),
              "pixel_sha256": hashlib.sha256(rgb).hexdigest(),
              "stream": name + ".stream", "ppm": name + ".ppm", "metadata": name + ".json",
              "stream_bytes": len(stream), "ppm_bytes": len(header) + len(rgb),
              "limitations": IMAGE_LIMITATIONS}
    metadata = encoded(record)
    if len(stream) + len(header) + len(rgb) + len(metadata) + size + reserve > MAX_BYTES:
        raise ValueError("PDFium metadata exceeds remaining byte budget")
    write_output(directory, record["stream"], stream, reserve)
    write_output(directory, record["ppm"], header + rgb, reserve)
    write_output(directory, record["metadata"], metadata, reserve)
    return record


def _ruling(obj, raw, identity, ordinal):
    """Measure identity two-point strokes and retain the native clip sentinel explicitly."""
    fill, stroke = c_int(), c_int()
    clip = raw.FPDFPageObj_GetClipPath(obj)
    count = raw.FPDFClipPath_CountPaths(clip) if clip else None
    if (obj.get_matrix().get() != (1, 0, 0, 1, 0, 0) or raw.FPDFPageObj_HasTransparency(obj)
            or type(count) is not int or count not in (-1, 0) or raw.FPDFPath_CountSegments(obj) != 2
            or not raw.FPDFPath_GetDrawMode(obj, fill, stroke) or fill.value != raw.FPDF_FILLMODE_NONE or not stroke.value):
        raise ValueError("Unsupported ruling path state")
    points = []
    for index, kind in enumerate((raw.FPDF_SEGMENT_MOVETO, raw.FPDF_SEGMENT_LINETO)):
        segment = raw.FPDFPath_GetPathSegment(obj, index)
        x, y = c_float(), c_float()
        if (not segment or raw.FPDFPathSegment_GetType(segment) != kind or raw.FPDFPathSegment_GetClose(segment)
                or not raw.FPDFPathSegment_GetPoint(segment, x, y)):
            raise ValueError("Unsupported ruling path segment")
        points.extend((x.value, y.value))
    return {"page": identity["page"], "object_ordinal": ordinal, "points": points,
            "source_pdf_sha256": identity["source_pdf_sha256"], "clip_path_count": count,
            "method": "pdfium-identity-stroked-line-v1"}


def _objects(page, raw, descriptor, directory, result, identity, emitted):
    """Collect top-level ruling measurements and preserve separate pixel occurrences."""
    first_ruling, rejected = len(result["rulings"]), False
    for ordinal, image in enumerate(page.get_objects(max_depth=1)):
        if rejected and image.type in (raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_FORM):
            continue
        try:
            if image.type == raw.FPDF_PAGEOBJ_PATH:
                ruling = _ruling(image, raw, identity, ordinal)
                if len(encoded(result)) + len(encoded(ruling)) + 32768 > RESULT_BYTES:
                    raise ValueError("Ruling observations exceed reserved 128 KiB result budget")
                result["rulings"].append(ruling)
                continue
            if image.type == raw.FPDF_PAGEOBJ_FORM:
                raise ValueError("Form/nested route unsupported")
            if image.type != raw.FPDF_PAGEOBJ_IMAGE:
                continue
            if emitted >= 4096 or len(result["images"]) >= 20:
                raise ValueError("PDFium image export exceeds element/image result budget")
            record = _export_image(image, raw, directory, {**identity, "object_ordinal": ordinal},
                                   descriptor["reserve_bytes"] + RESULT_BYTES)
        except ValueError as error:
            rejected = rejected or image.type in (raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_FORM)
            result["limitations"].append(f"Page {identity['page']} object {ordinal}: {error}")
        else:
            result["images"].append(record)
            emitted += 1
    if rejected:
        del result["rulings"][first_ruling:]
        result["limitations"].append(f"Page {identity['page']}: all rulings abstained after rejected path/form or result budget")
    return emitted


def extract_images(pdf, raw, descriptor, directory):
    """Enumerate top-level objects with explicit MediaBox and measured full-page bounds."""
    result = {"images": [], "pages": [], "rulings": [], "limitations": [], "module_origins": {}}
    emitted, native_objects = descriptor["elements"], 0
    with pdf.PdfDocument(descriptor["input"]["path"]) as document:
        for number in range(len(document)):
            if number >= 4096:
                raise ValueError("PDFium page count exceeds element ceiling")
            page = document[number]
            try:
                width, height = page.get_size()
                rotation = page.get_rotation()
                result["pages"].append({"page": number+1, "page_width": width, "page_height": height,
                    "rotation_degrees": rotation, "rotation_direction": "clockwise", "units": "PDF_canvas_units",
                    "source_pdf_sha256": descriptor["input"]["sha256"], "method": "pdfium-page-geometry-v1"})
                box = (0, 0, width, height)
                if (rotation != 0 or page.get_mediabox(fallback_ok=False) != box
                        or page.get_cropbox(fallback_ok=False) not in (None, box)
                        or page.get_bbox() != box):
                    result["limitations"].append(f"Page {number+1}: unsupported rotation/page bounds")
                    continue
                native_objects += raw.FPDFPage_CountObjects(page)
                if native_objects > 4096:
                    raise ValueError("PDFium native object work exceeds 4096")
                identity = {"page": number+1, "page_width": width, "page_height": height,
                            "source_pdf_sha256": descriptor["input"]["sha256"]}
                emitted = _objects(page, raw, descriptor, directory, result, identity, emitted)
            finally:
                page.close()
    limitations = list(dict.fromkeys(result["limitations"]))
    result["limitations"] = limitations if len(limitations) <= 24 else limitations[:23] + [
        "Additional PDFium limitations truncated"]
    return result


def worker(descriptor_path: Path, input_path: Path, directory: Path) -> None:
    """Admit exact paths/hashes before selected-package imports, with no .pth."""
    regular(descriptor_path)
    usage(directory)
    if descriptor_path.parent != directory or descriptor_path.stat().st_size > MAX_BYTES:
        raise ValueError("PDFium descriptor must be contained and bounded")
    descriptor = json.loads(descriptor_path.read_bytes())
    if set(descriptor) != {"runtime", "input", "output", "elements", "reserve_bytes"}:
        raise ValueError("Unknown PDFium descriptor fields")
    if str(directory) != descriptor["output"] or file_record(input_path) != descriptor["input"]:
        raise ValueError("PDFium input/output binding changed")
    if type(descriptor["elements"]) is not int or not 0 <= descriptor["elements"] <= 4096:
        raise ValueError("Invalid PDFium element budget")
    if type(descriptor["reserve_bytes"]) is not int or not 0 <= descriptor["reserve_bytes"] <= MAX_BYTES:
        raise ValueError("Invalid PDFium byte reservation")
    profile = descriptor["runtime"]
    verify_runtime(profile)
    with selected_imports(profile):
        pdf = importlib.import_module("pypdfium2")
        raw = importlib.import_module("pypdfium2_raw")
        result = extract_images(pdf, raw, descriptor, directory)
        result["module_origins"] = module_origins(profile)
    verify_runtime(profile)
    if file_record(input_path) != descriptor["input"]:
        raise ValueError("PDFium original changed during extraction")
    result["runtime"] = {"worker": profile["worker"], "python": profile["python"],
                         "selected_native_paths": [r["path"] for r in profile["inventory"]
                                          if Path(r["path"]).suffix in {".so", ".dylib", ".dll"}],
                         "checked_boundary": BOUNDARY}
    data = encoded(result)
    if len(data) > RESULT_BYTES:
        raise ValueError("PDFium result exceeds its reserved body budget")
    write_output(directory, "pdfium-result.json", data, descriptor["reserve_bytes"])


if __name__ == "__main__":
    worker(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
