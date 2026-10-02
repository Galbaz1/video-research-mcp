"""Regressions for planned image allocation and original physical-line coverage."""

import json
import struct
import zlib

import pytest

from tests.test_core_dispatch import call_directory, dispatch, selection, setup


def png(width, height, orientation=None):
    """Build a complete first-party grayscale PNG without resizing or foreign handlers."""
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    body = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    if orientation is not None:
        exif = b"II*\x00\x08\x00\x00\x00\x01\x00" + struct.pack("<HHIHH", 274, 3, 1, orientation, 0) + b"\x00" * 4
        body += chunk(b"eXIf", exif)
    return body + chunk(b"IDAT", zlib.compress(b"\x00" * ((width + 1) * height))) + chunk(b"IEND", b"")


@pytest.mark.parametrize("name,width,height,arguments,orientation", [
    ("read_image", 1048576, 1, {"budget": "normal"}, None),
    ("read_image", 1, 1048576, {"budget": "normal"}, None),
    ("read_image", 1048576, 1, {"budget": "large"}, None),
    ("visualize", 1048576, 1, {"max_pages": 1}, None),
    ("crop", 1048576, 1, {"box": [0, 0, 1000, 1000]}, None),
    ("crop", 1048576, 16, {"box": [0, 0, 1000, 63]}, None),
    ("crop", 1048576, 16, {"box": [0, 0, 63, 1000]}, 6),
])
def test_planned_grid_refuses_before_original_handler(tmp_path, name, width, height, arguments, orientation):
    boundary, row = setup(tmp_path, png(width, height, orientation), ".png")
    directory = call_directory(boundary)
    key = "file_path" if name == "visualize" else "image_path"
    with pytest.raises(ValueError, match="preview grid"):
        dispatch.prepare_call(name, {key: row["path"], **arguments}, boundary.data, boundary.inputs, directory)


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\u0085"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_unicode_in_json_does_not_invent_skipped_physical_lines(tmp_path, separator, newline):
    text = json.dumps({"text": separator * 501}, ensure_ascii=False) + newline
    boundary, row = setup(tmp_path, text.encode(), ".json")
    boundary.data["family_extensions"]["code"].append(".json")
    directory = call_directory(boundary)
    selected = selection(boundary, row, directory)
    result = dispatch.content_result([{"type": "text", "text": text}], selected, directory)
    assert result["state"] == "complete"
    assert result["coverage"]["total_lines"] == 1
    assert result["coverage"]["retained_lines"] == 1
    assert result["coverage"]["skipped_lines"] == 0
