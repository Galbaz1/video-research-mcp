"""Actual owned DOCX ZIP/XML fixtures, original fidelity and bounded safety controls."""

from __future__ import annotations

import hashlib
import html
import io
import json
import os
import stat
import struct
import warnings
import zipfile
from pathlib import Path

import pytest

from video_research_mcp.ingestion_docx import parse_docx_source

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


def document(body: str) -> str:
    """Construct an owned main-document fixture, without a foreign DOCX runtime."""
    return (f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:a="{A}" xmlns:m="{M}">'
            f"<w:body>{body}</w:body></w:document>")


def relationship(identifier: str, target: str, *, external: bool = False, kind: str = "image") -> str:
    """Build explicit relationship data with actual XML attribute escaping."""
    mode = ' TargetMode="External"' if external else ""
    return (f'<Relationship Id="{identifier}" Type="{R}/{kind}" '
            f'Target="{html.escape(target, quote=True)}"{mode}/>')


def source(tmp_path: Path, body: str = "", *, relations: str | None = None,
           extras: list[tuple[str | zipfile.ZipInfo, bytes | str]] | None = None,
           main_xml: str | bytes | None = None, compression: int = zipfile.ZIP_STORED):
    """Write bounded fixture members and a separate owned artifact directory."""
    members = [("word/document.xml", document(body) if main_xml is None else main_xml)]
    if relations is not None:
        members.append(("word/_rels/document.xml.rels", f'<Relationships xmlns="{P}">{relations}</Relationships>'))
    members.extend(extras or [])
    stream = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(stream, "w", compression=compression) as archive:
        warnings.simplefilter("ignore", UserWarning)
        for name, data in members:
            archive.writestr(name, data)
    original, derived = tmp_path / "original.docx", tmp_path / "derived"
    original.write_bytes(stream.getvalue())
    derived.mkdir()
    return original, derived


def test_paragraphs_preserve_unicode_tabs_breaks_and_zip_original(tmp_path):
    body = ('<w:p><w:r><w:t>Café α</w:t><w:tab/><w:t>second</w:t><w:br/><w:t>line</w:t></w:r></w:p>'
            '<w:p/><w:p><w:r><w:t>Final.</w:t></w:r></w:p>')
    original, derived = source(tmp_path, body)
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    result = parse_docx_source(original, derived)
    assert [s.text for s in result.segments] == ["Café α\tsecond\nline", "Final."]
    assert [s.location.paragraph for s in result.segments] == [0, 2]
    assert all(s.location.start_char is None and s.location.page is None and s.location.bbox is None
               for s in result.segments)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    assert list(derived.iterdir()) == []


def test_tables_keep_actual_cells_multiple_paragraphs_and_nested_table_identity(tmp_path):
    body = ('<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>B</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Nested</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '</w:tc><w:tc><w:p/></w:tc><w:tc><w:p><w:r><w:t>C</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    original, derived = source(tmp_path, body)
    result = parse_docx_source(original, derived)
    cells = {(s.location.table, s.location.row, s.location.column): s.text for s in result.segments}
    assert cells == {(0, 0, 0): "A\nB", (0, 0, 2): "C", (1, 0, 0): "Nested"}
    assert all(s.kind == "table_cell" and s.location.page is None for s in result.segments)


def test_embedded_image_bytes_are_exact_private_and_reused_with_cell_provenance(tmp_path):
    body = ('<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Image caption</w:t><w:drawing>'
            '<a:blip r:embed="image1"/></w:drawing></w:r></w:p></w:tc></w:tr></w:tbl>'
            '<w:p><w:r><w:drawing><a:blip r:embed="image1"/></w:drawing></w:r></w:p>')
    image = b"\x89PNG\r\n\x1a\nowned opaque image bytes; pixel decoding is unverified"
    original, derived = source(tmp_path, body, relations=relationship("image1", "media/own.png"),
                               extras=[("word/media/own.png", image)])
    before = original.read_bytes()
    result = parse_docx_source(original, derived)
    images = [s for s in result.segments if s.kind == "image"]
    assert len(images) == 2 and images[0].artifact == images[1].artifact
    assert (images[0].location.table, images[0].location.row, images[0].location.column) == (0, 0, 0)
    assert [s.location.paragraph for s in images] == [0, 1]
    artifact = Path(images[0].artifact)
    assert artifact.parent == derived and artifact.read_bytes() == image
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
    assert json.loads(images[0].text)["member"] == "word/media/own.png"
    assert len(list(derived.iterdir())) == 1 and original.read_bytes() == before


def test_external_images_hyperlinks_and_anchors_stay_unfetched_descriptors(tmp_path):
    body = ('<w:p><w:hyperlink r:id="link1"><w:r><w:t>External</w:t></w:r></w:hyperlink>'
            '<w:hyperlink w:anchor="bookmark"><w:r><w:t>Anchor</w:t></w:r></w:hyperlink>'
            '<w:r><w:drawing><a:blip r:link="image1"/></w:drawing></w:r></w:p>')
    relations = (relationship("link1", "https://example.invalid/?a=1&b=2", external=True, kind="hyperlink")
                 + relationship("image1", "file:///etc/passwd", external=True))
    original, derived = source(tmp_path, body, relations=relations)
    before = original.read_bytes()
    result = parse_docx_source(original, derived)
    references = [s for s in result.segments if s.artifact]
    records = [json.loads(Path(s.artifact).read_bytes()) for s in references]
    assert [r["target"] for r in records] == ["https://example.invalid/?a=1&b=2", "#bookmark", "file:///etc/passwd"]
    assert [s.kind for s in references] == ["text", "text", "image"]
    assert all(r["fetched"] is False and r["location"]["paragraph"] == 0 for r in records)
    assert all(stat.S_IMODE(Path(s.artifact).stat().st_mode) == 0o600 for s in references)
    assert original.read_bytes() == before


def test_equation_retains_literal_math_and_serialized_structure_without_page_guess(tmp_path):
    body = ('<w:p><w:r><w:t>Formula:</w:t></w:r><m:oMath><m:f><m:num><m:r><m:t>x</m:t></m:r>'
            '</m:num><m:den><m:r><m:t>2</m:t></m:r></m:den></m:f></m:oMath></w:p>')
    original, derived = source(tmp_path, body)
    result = parse_docx_source(original, derived)
    assert [s.kind for s in result.segments] == ["text", "equation"]
    equation = result.segments[1]
    assert equation.text == "x2" and equation.location.paragraph == 0
    assert equation.location.page is None and equation.location.bbox is None
    record = json.loads(Path(equation.artifact).read_bytes())
    assert record["rendered"] is False and "num" in record["xml"] and "den" in record["xml"]
    assert any("visual mathematical interpretation is unverified" in item for item in result.limitations)


def test_empty_docx_body_returns_empty_result(tmp_path):
    original, derived = source(tmp_path, "<w:p/><w:sectPr/>")
    result = parse_docx_source(original, derived)
    assert result.segments == [] and list(derived.iterdir()) == []


@pytest.mark.parametrize("member", ["../escape", "/absolute", "word/../escape", "word\\evil",
                                   "word//evil", "C:drive", "word/\x00evil"])
def test_unsafe_member_names_are_rejected_before_extraction(tmp_path, member):
    stored_name = member.replace("\x00", "X")
    original, derived = source(tmp_path, extras=[(stored_name, b"inert")])
    if "\x00" in member:
        original.write_bytes(original.read_bytes().replace(stored_name.encode(), member.encode()))
    with pytest.raises(ValueError, match="unsafe ZIP member"):
        parse_docx_source(original, derived)
    assert list(derived.iterdir()) == []


@pytest.mark.parametrize("case", ["duplicate", "symlink", "encrypted", "bad_crc", "bad_zip"])
def test_unsafe_or_malformed_zip_is_explicit_failure(tmp_path, case):
    extras = []
    if case == "duplicate":
        extras = [("word/document.xml", document(""))]
    elif case == "symlink":
        info = zipfile.ZipInfo("word/media/link")
        info.create_system, info.external_attr = 3, (stat.S_IFLNK | 0o777) << 16
        extras = [(info, b"../../outside")]
    original, derived = source(tmp_path, "<w:p><w:r><w:t>KNOWNPAYLOAD</w:t></w:r></w:p>", extras=extras)
    data = bytearray(original.read_bytes())
    if case == "encrypted":
        central = data.index(b"PK\x01\x02")
        for offset in (6, central + 8):
            struct.pack_into("<H", data, offset, struct.unpack_from("<H", data, offset)[0] | 1)
    elif case == "bad_crc":
        data[data.index(b"KNOWNPAYLOAD")] = ord("J")
    elif case == "bad_zip":
        data = bytearray(b"not a ZIP")
    original.write_bytes(data)
    with pytest.raises(ValueError):
        parse_docx_source(original, derived)
    assert original.read_bytes() == bytes(data) and list(derived.iterdir()) == []


@pytest.mark.parametrize("target", ["../../escape", "%2e%2e/%2e%2e/escape", "/absolute", "media\\escape",
                                   "https://example.invalid/image", "media/a.png#fragment", "missing.png"])
def test_internal_relationship_cannot_escape_or_silently_drop_missing_media(tmp_path, target):
    original, derived = source(tmp_path, '<w:p><a:blip r:embed="i"/></w:p>',
                               relations=relationship("i", target))
    with pytest.raises(ValueError, match="relationship"):
        parse_docx_source(original, derived)
    assert list(derived.iterdir()) == []


@pytest.mark.parametrize("body,relations", [('<w:p><a:blip/></w:p>', None),
    ('<w:p><a:blip r:embed="unknown"/></w:p>', None),
    ('<w:p><a:blip r:embed="i" r:link="j"/></w:p>', None),
    ("", relationship("i", "a.png", external=True) + relationship("i", "b.png", external=True)),
    ('<w:p><a:blip r:link="i"/></w:p>', relationship("i", "https://example.invalid", external=True, kind="hyperlink"))])
def test_missing_ambiguous_or_duplicate_relationships_fail(tmp_path, body, relations):
    original, derived = source(tmp_path, body, relations=relations)
    with pytest.raises(ValueError, match="reference|relationship"):
        parse_docx_source(original, derived)
    assert list(derived.iterdir()) == []


@pytest.mark.parametrize("xml", ["<not-word/>", f'<w:document xmlns:w="{W}"/>', "<broken>",
    '<!DOCTYPE w:document [<!ENTITY e "unsafe">]>' + document('<w:p><w:r><w:t>&e;</w:t></w:r></w:p>'),
    document("<w:p/>" * 32769), document("<w:sdt>" * 65 + "</w:sdt>" * 65), b"\xff"])
def test_invalid_unsupported_or_unbounded_xml_has_no_output(tmp_path, xml):
    original, derived = source(tmp_path, main_xml=xml)
    with pytest.raises(ValueError):
        parse_docx_source(original, derived)
    assert list(derived.iterdir()) == []


@pytest.mark.parametrize("case", ["members", "expanded_bytes", "expansion_ratio", "text", "segments", "artifacts", "artifact_bytes"])
def test_docx_bounds_are_enforced_before_artifact_publication(tmp_path, case):
    body, extras, relations = "", [], None
    if case == "members":
        extras = [(f"own/{i}", b"") for i in range(128)]
    elif case == "expanded_bytes":
        extras = [("own/large", b"x" * (8 * 1024 * 1024 + 1))]
    elif case == "expansion_ratio":
        extras = [("own/large", b"x" * 500000)]
    elif case == "text":
        body = f"<w:p><w:r><w:t>{'x' * 32769}</w:t></w:r></w:p>"
    elif case == "segments":
        body = "<w:p><w:r><w:t>x</w:t></w:r></w:p>" * 4097
    elif case == "artifact_bytes":
        extras = [("word/media/own.png", b"x" * 8000000)]
        relations = relationship("i", "media/own.png")
        attribute = "\\" * 300000
        body = ('<w:p><a:blip r:embed="i"/><m:oMath own="' + attribute +
                '"><m:r><m:t>x</m:t></m:r></m:oMath></w:p>')
    else:
        body = "<w:p>" + "".join(f'<a:blip r:link="i{n}"/>' for n in range(61)) + "</w:p>"
        relations = "".join(relationship(f"i{n}", f"https://example.invalid/{n}", external=True) for n in range(61))
    original, derived = source(tmp_path, body, extras=extras, relations=relations,
                               compression=zipfile.ZIP_DEFLATED if case in {"expanded_bytes", "expansion_ratio"} else zipfile.ZIP_STORED)
    with pytest.raises(ValueError):
        parse_docx_source(original, derived)
    assert list(derived.iterdir()) == []


def test_missing_main_document_is_not_treated_as_empty_success(tmp_path):
    original, derived = source(tmp_path)
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr("own/other.xml", "<other/>")
    with pytest.raises(ValueError, match="no word/document.xml"):
        parse_docx_source(original, derived)
    assert list(derived.iterdir()) == []


def test_docx_exclusive_artifact_collision_preserves_prior_file(tmp_path):
    body = '<w:p><a:blip r:link="i"/></w:p>'
    original, derived = source(tmp_path, body, relations=relationship("i", "https://example.invalid", external=True))
    existing = derived / "docx-0000.json"
    existing.write_bytes(b"prior file")
    with pytest.raises(FileExistsError):
        parse_docx_source(original, derived)
    assert existing.read_bytes() == b"prior file" and list(derived.iterdir()) == [existing]


def test_docx_nonregular_original_is_rejected(tmp_path):
    original, derived = source(tmp_path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(PermissionError, match="regular"):
        parse_docx_source(fifo, derived)
    assert original.exists() and list(derived.iterdir()) == []
