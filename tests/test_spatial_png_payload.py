"""Stdlib boundary tests; synthetic archives never receive pinned admission.

Run directly with Python -I -B to avoid repository pytest fixtures and foreign
imports. Set TMPDIR to the assigned worker evidence directory when executing.
"""

from __future__ import annotations

import base64
from contextlib import redirect_stdout
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/spatial_png_payload.py"
SPEC = importlib.util.spec_from_file_location("spatial_png_payload", SCRIPT)
payload_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(payload_builder)
RECORD = payload_builder.RECORD
TTF = "matplotlib/mpl-data/fonts/ttf/cmr10.ttf"
AFM = "matplotlib/mpl-data/fonts/afm/cmr10.afm"
CORE_AFM = "matplotlib/mpl-data/fonts/pdfcorefonts/Courier.afm"
LICENSE = f"{payload_builder.DIST_INFO}/LICENSE"


def record_bytes(files: dict[str, bytes]) -> bytes:
    """Build an independent synthetic RECORD oracle, not a trusted wheel."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for name, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(data)))
    writer.writerow((RECORD, "", ""))
    return buffer.getvalue().encode()


def archive_bytes(files: dict[str, bytes], modes: dict | None = None,
                  extra: tuple[str, bytes] | None = None) -> bytes:
    """Represent regular files, directories or deliberately invalid ZIP metadata."""
    files = {**files, RECORD: files.get(RECORD, record_bytes(files))}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in list(files.items()) + ([extra] if extra else []):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            mode = (modes or {}).get(name, stat.S_IFREG | 0o644)
            info.external_attr = mode << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def fixture_files() -> dict[str, bytes]:
    """Include both AFM directories, executable content, TTF and notices."""
    return {
        TTF: b"synthetic TTF; never rendered",
        AFM: b"synthetic AFM metric",
        CORE_AFM: b"synthetic core metric",
        LICENSE: b"synthetic notice; not a production license",
        "matplotlib/mpl-data/fonts/pdfcorefonts/readme.txt": b"retain notice",
        "matplotlib/mpl-data/fonts/afm/notice.txt": b"retain non-metric content",
        "matplotlib/mpl-data/fonts/ttf/LICENSE_STIX": b"retain TTF notice",
        "matplotlib/mpl-data/fonts/ttf/LICENSE_DEJAVU": b"retain TTF notice",
        "matplotlib/mathtext.py": b"synthetic mathtext body",
        "matplotlib/backends/backend_agg.py": b"synthetic Agg body",
        "matplotlib/elsewhere.afm": b"retain AFM outside exact directories",
        "matplotlib/mpl-data/fonts/afm/nested/keep.afm": b"retain nested asset",
    }


class ArchiveBoundaryTests(unittest.TestCase):
    """Validate transformation identity and archive refusal boundaries."""

    def test_retained_bytes_modes_directories_and_record(self):
        """GIVEN synthetic data WHEN deriving THEN only the two metrics disappear."""
        files = fixture_files()
        directory = "matplotlib/mpl-data/fonts/afm/"
        files[RECORD] = record_bytes(files)
        files[directory] = b""
        modes = {directory: stat.S_IFDIR | 0o755, "matplotlib/mathtext.py": stat.S_IFREG | 0o755}
        source = archive_bytes(files, modes)
        derived, receipt = payload_builder._derive(source)
        with zipfile.ZipFile(io.BytesIO(derived)) as archive:
            for name, data in files.items():
                if name not in (AFM, CORE_AFM, RECORD):
                    self.assertEqual(archive.read(name), data)
                    self.assertEqual(archive.getinfo(name).external_attr >> 16,
                                     modes.get(name, stat.S_IFREG | 0o644))
            rows = list(csv.reader(io.StringIO(archive.read(RECORD).decode())))
            expected = {n for n in archive.namelist() if not n.endswith("/")}
            self.assertEqual({r[0] for r in rows}, expected)
            self.assertEqual(len(rows), len(expected))
            for name, digest, size in rows:
                if name == RECORD:
                    self.assertEqual((digest, size), ("", ""))
                else:
                    data = archive.read(name)
                    decoded = base64.urlsafe_b64decode(digest.removeprefix("sha256=") + "=")
                    self.assertEqual(decoded, hashlib.sha256(data).digest())
                    self.assertEqual(size, str(len(data)))
            self.assertIn(b"Changes:", archive.read(payload_builder.ATTRIBUTION))
        self.assertEqual({r["member"] for r in receipt["excluded"]}, {AFM, CORE_AFM})
        self.assertEqual(receipt["source_admission"], "NOT_PERFORMED")
        self.assertEqual(receipt["derived"]["sha256"], hashlib.sha256(derived).hexdigest())
        self.assertEqual(receipt["original"]["sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual({r["member"] for r in receipt["retained"]}, set(files) - {AFM, CORE_AFM, RECORD})

    def test_deterministic_output_ignores_input_order(self):
        files = fixture_files()
        first, first_receipt = payload_builder._derive(archive_bytes(files))
        alternate = io.BytesIO()
        source = archive_bytes(dict(reversed(list(files.items()))))
        with zipfile.ZipFile(io.BytesIO(source)) as original, zipfile.ZipFile(alternate, "w") as archive:
            archive.comment = b"different archive comment"
            for info in original.infolist():
                data = original.read(info)
                info.date_time = (2025, 6, 1, 12, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.comment = b"different entry comment"
                info.extra = b"\x01\xf0\x01\x00z"
                archive.writestr(info, data)
        second, second_receipt = payload_builder._derive(alternate.getvalue())
        self.assertEqual(first, second)
        self.assertEqual(first_receipt["derived"], second_receipt["derived"])
        self.assertNotEqual(first_receipt["original"], second_receipt["original"])

    def test_unsafe_member_names(self):
        for name in ("../escape", "/absolute", "a/../../escape", "a//b", "a/./b",
                     "a\\b", "C:/escape", "a\nname", "nonascii-é"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsafe archive member"):
                payload_builder._derive(archive_bytes({**fixture_files(), name: b"unsafe"}))

    def test_raw_nul_member_name_refused(self):
        """GIVEN raw ZIP filename headers WHEN parsed THEN the unsafe name is refused."""
        source = archive_bytes({"aXsuffix": b"unsafe"})
        changed = bytearray(source)
        # Change both filename headers without touching data or RECORD checksums.
        for offset in (30, source.index(b"PK\x01\x02") + 46):
            self.assertEqual(source[offset:offset + 8], b"aXsuffix")
            changed[offset + 1] = 0
        with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
            payload_builder._derive(bytes(changed))

    def test_duplicate_case_alias_and_file_directory_conflict(self):
        for extra in ((TTF, b"duplicate"), (TTF.upper(), b"case alias"),
                      (TTF + "/nested", b"conflict")):
            with self.subTest(extra=extra), warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with self.assertRaises(ValueError):
                    payload_builder._derive(archive_bytes(fixture_files(), extra=extra))

    def test_nonregular_members_and_nonempty_directory(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o644, stat.S_IFCHR | 0o644,
                     stat.S_IFDIR | 0o755, 0o644):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                payload_builder._derive(archive_bytes(fixture_files(), {TTF: mode}))
        for name in ("bad/", "bad//"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                payload_builder._derive(archive_bytes({**fixture_files(), name: b"not empty"},
                                                      {name: stat.S_IFDIR | 0o755}))

    def test_record_coverage_tampering_and_self_entry(self):
        files = fixture_files()
        rows = list(csv.reader(io.StringIO(record_bytes(files).decode())))
        variants = [rows[:-2] + rows[-1:], rows + [rows[0]],
                    rows + [["missing", "sha256=garbage", "1"]],
                    [["one-column"]] + rows[1:]]
        for column, value in ((1, "sha256=tampered"), (1, "md5=bad"), (1, ""),
                              (2, "9999"), (2, "")):
            variant = [list(row) for row in rows]
            variant[0][column] = value
            variants.append(variant)
        variants.append(rows[:-1] + [[RECORD, "sha256=bad", "0"]])
        for variant in variants:
            with self.subTest(variant=variant):
                buffer = io.StringIO()
                csv.writer(buffer).writerows(variant)
                with self.assertRaises(ValueError):
                    payload_builder._derive(archive_bytes({**files, RECORD: buffer.getvalue().encode()}))
        with self.assertRaises(csv.Error):
            payload_builder._derive(archive_bytes({**files, RECORD: b'"unterminated'}))

    def test_bad_archive_and_missing_record(self):
        with self.assertRaises(zipfile.BadZipFile):
            payload_builder._derive(b"not a zip")
        with self.assertRaises(ValueError):
            payload_builder._derive(b"PK\x05\x06" + b"\0" * 18)

    def test_existing_attribution_refused(self):
        with self.assertRaises(ValueError):
            payload_builder._derive(archive_bytes({**fixture_files(), payload_builder.ATTRIBUTION: b"preexisting"}))


class FilesystemBoundaryTests(unittest.TestCase):
    """Keep untrusted input and filesystem output separate from archive seam tests."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.wheel = self.root / payload_builder.WHEEL_NAME
        self.output = self.root / "derived"

    def test_synthetic_wheel_cannot_pass_production_admission(self):
        source = archive_bytes(fixture_files())
        self.wheel.write_bytes(source)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            payload_builder.build(self.wheel, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.wheel.read_bytes(), source)

    def test_wrong_filename_refused_before_read(self):
        with self.assertRaisesRegex(ValueError, "filename"):
            payload_builder.build(self.root / "other.whl", self.output)
        self.assertFalse(self.output.exists())

    def test_symlink_input_and_parent_and_nonregular_input(self):
        target = self.root / "target"
        target.write_bytes(b"untrusted")
        self.wheel.symlink_to(target)
        with self.assertRaises(OSError):
            payload_builder.build(self.wheel, self.output)
        self.wheel.unlink()
        self.wheel.mkdir()
        with self.assertRaises(ValueError):
            payload_builder.build(self.wheel, self.output)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            payload_builder.build(alias / payload_builder.WHEEL_NAME, self.output)
        self.assertFalse(self.output.exists())

    def test_parent_traversal_refused(self):
        with self.assertRaises(ValueError):
            payload_builder.build(self.root / ".." / payload_builder.WHEEL_NAME, self.output)
        with self.assertRaises(ValueError):
            payload_builder._publish(self.root / ".." / "escape", b"wheel", {})

    def test_publish_receipt_and_refuse_all_existing_outputs(self):
        derived, receipt = payload_builder._derive(archive_bytes(fixture_files()))
        payload_builder._publish(self.output, derived, receipt)
        self.assertEqual((self.output / payload_builder.WHEEL_NAME).read_bytes(), derived)
        self.assertEqual(json.loads((self.output / "receipt.json").read_text()), receipt)
        with self.assertRaises(FileExistsError):
            payload_builder._publish(self.output, b"replacement", {})
        self.assertEqual((self.output / payload_builder.WHEEL_NAME).read_bytes(), derived)
        for name, kind in (("empty", "dir"), ("file", "file"), ("link", "link")):
            path = self.root / name
            if kind == "dir":
                path.mkdir()
            elif kind == "file":
                path.write_bytes(b"keep")
            else:
                path.symlink_to(self.output, target_is_directory=True)
            with self.subTest(kind=kind), self.assertRaises(FileExistsError):
                payload_builder._publish(path, b"replacement", {})

    def test_publish_symlink_parent_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            payload_builder._publish(alias / "new-output", b"wheel", {})
        self.assertFalse((self.root / "new-output").exists())

    def test_failed_publication_leaves_no_partial_output(self):
        """GIVEN a failed second fsync WHEN publishing THEN owned partial files vanish."""
        with mock.patch.object(payload_builder.os, "fsync", side_effect=[None, OSError("synthetic disk failure")]):
            with self.assertRaisesRegex(OSError, "synthetic disk failure"):
                payload_builder._publish(self.output, b"synthetic wheel", {})
        self.assertFalse(self.output.exists())

    def test_cli_argument_wiring_without_admission(self):
        with mock.patch.object(sys, "argv", [str(SCRIPT), str(self.wheel), str(self.output)]):
            with mock.patch.object(payload_builder, "build", return_value={
                "source_admission": "NOT_PERFORMED", "original": {}, "derived": {}}) as build:
                with redirect_stdout(io.StringIO()) as stdout:
                    payload_builder.main()
                build.assert_called_once_with(self.wheel, self.output)
                self.assertEqual(json.loads(stdout.getvalue())["source_admission"], "NOT_PERFORMED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
