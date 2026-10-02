"""Operator-file authority tests; no original source or native code is executed."""

import os
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core_inputs as inputs


def record(path, body=b"print('data only')\n"):
    """Create a complete first-party byte commitment."""
    path.write_bytes(body)
    return {"path": str(path), "bytes": len(body), "sha256": inputs.sha256(body)}


def authority(tmp_path, count=1):
    """Create independent selected files rather than shared aliases."""
    rows = [record(tmp_path / f"source-{n}.py") for n in range(count)]
    path = tmp_path / "inputs.json"
    binding = inputs.write_json(path, {"schema_version": 1, "files": rows})
    return inputs.Inputs(path, binding["sha256"]), rows


@pytest.mark.parametrize("count", [1, 8, 32])
def test_complete_operator_population_and_private_copy(tmp_path, count):
    selected, rows = authority(tmp_path, count)
    directory = tmp_path / "copies"
    directory.mkdir()
    copy = selected.copy(rows[0], directory)
    assert copy["path"] != rows[0]["path"]
    assert inputs.verify(copy) == inputs.verify(rows[0])
    assert os.stat(copy["path"]).st_mode & 0o777 == 0o400
    selected.readback()
    with pytest.raises(FileExistsError):
        selected.copy(rows[0], directory)


@pytest.mark.parametrize("value", ["relative.py", "https://example.test/a.py", "/tmp/../tmp/a", "file:///tmp/a", "\x00"])
def test_url_relative_alias_traversal_refused(value):
    with pytest.raises(ValueError):
        inputs.canonical(value)


def test_symlink_fifo_and_external_path_not_admitted(tmp_path):
    selected, rows = authority(tmp_path)
    link = tmp_path / "alias.py"
    link.symlink_to(rows[0]["path"])
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for path in (link, fifo):
        with pytest.raises(ValueError):
            inputs.read_body(path, 100)
    extra = record(tmp_path / "other.py")
    with pytest.raises(ValueError):
        selected.selected(extra["path"])


@pytest.mark.parametrize("change", ["source", "authority"])
def test_readback_refuses_changed_exact_commitments(tmp_path, change):
    selected, rows = authority(tmp_path)
    path = Path(rows[0]["path"]) if change == "source" else selected.path
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        selected.readback()


@pytest.mark.parametrize("change", ["empty", "duplicate", "extra", "too-many", "bool-schema"])
def test_authority_rejects_ambiguous_or_excessive_populations(tmp_path, change):
    row = record(tmp_path / "a.py")
    data = {"schema_version": 1, "files": [row]}
    if change == "empty":
        data["files"] = []
    elif change == "duplicate":
        data["files"] *= 2
    elif change == "extra":
        data["files"][0] = {**row, "provider": "forbidden"}
    elif change == "too-many":
        data["files"] = [record(tmp_path / f"p{n}.py") for n in range(33)]
    else:
        data["schema_version"] = True
    binding = inputs.write_json(tmp_path / "bad.json", data)
    with pytest.raises(ValueError):
        inputs.Inputs(binding["path"], binding["sha256"])


@pytest.mark.parametrize("body", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_authority_json_is_unambiguous(body):
    with pytest.raises(ValueError):
        inputs.parse_json(body)


@pytest.mark.parametrize("pages,maximum", [(None, 4), ("1-3,3,4", 4), ("9", 1)])
def test_finite_page_selection(pages, maximum):
    assert len(inputs.page_selection(pages, maximum)) <= maximum


@pytest.mark.parametrize("pages,maximum", [("1-100000", 4), ("1,3,5", 2), ("0", 4), ("3-1", 4), ("one", 4), (None, 20), (None, True), (None, 0), (None, float("inf")), (None, 1.5)])
def test_page_ranges_cannot_bypass_cap(pages, maximum):
    with pytest.raises(ValueError):
        inputs.page_selection(pages, maximum)


@pytest.mark.parametrize("shape", [(0, 1), (1, 0), (4097, 4097)])
def test_png_grid_preallocation_bound(shape):
    body = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", *shape) + b"\0" * 9
    with pytest.raises(ValueError):
        inputs.png_grid(body)


def test_atomic_receipt_bound_and_hash(tmp_path):
    binding = inputs.write_json(tmp_path / "receipt.json", {"state": "pending"})
    assert inputs.trusted_json(binding["path"], binding["sha256"])["state"] == "pending"
    with pytest.raises(ValueError):
        inputs.trusted_json(binding["path"], "0" * 64)
    with pytest.raises(ValueError):
        inputs.write_json(tmp_path / "large.json", {"text": "x" * 100}, maximum=50)
    assert not (tmp_path / "large.json").exists()
