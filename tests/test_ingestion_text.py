"""Independent local text transformations, provenance and exclusive-output controls."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from video_research_mcp.ingestion_text import parse_text_source


def source(tmp_path: Path, data: bytes | str) -> tuple[Path, Path]:
    """Create owned original bytes and an independent derived directory."""
    original = tmp_path / "original"
    original.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    derived = tmp_path / "derived"
    derived.mkdir()
    return original, derived


def test_plain_paragraphs_keep_unicode_and_original_intervals(tmp_path):
    """GIVEN Unicode paragraphs WHEN extracted THEN positions identify the original text."""
    text = "  Café α\r\nsecond line  \r\n\r\n\tLast paragraph.\n"
    original, derived = source(tmp_path, text)
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    result = parse_text_source(original, "text", derived)
    assert [segment.text for segment in result.segments] == ["Café α\r\nsecond line", "Last paragraph."]
    assert [segment.location.paragraph for segment in result.segments] == [0, 1]
    for segment in result.segments:
        location = segment.location
        assert text[location.start_char:location.end_char] == segment.text
        assert location.page is None and location.bbox is None
    assert list(derived.iterdir()) == []
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before


def test_html_decodes_body_entities_and_measured_cell_coordinates(tmp_path):
    text = ('<head><title>Hidden title</title></head><p>A<strong>B</strong> &amp; &#945;.</p>'
            '<script>ignore()</script><table><tr><th>Key</th><th>Value</th></tr>'
            '<tr><td>α</td><td>two<br>lines</td></tr></table>')
    original, derived = source(tmp_path, text)
    result = parse_text_source(original, "html", derived)
    assert [s.text for s in result.segments] == ["AB & α.", "Key", "Value", "α", "two\nlines"]
    cells = [s for s in result.segments if s.kind == "table_cell"]
    assert [(s.location.table, s.location.row, s.location.column) for s in cells] == [
        (0, 0, 0), (0, 0, 1), (0, 1, 0), (0, 1, 1)]
    assert text[cells[-1].location.start_char:cells[-1].location.end_char] == "two<br>lines"
    assert original.read_bytes() == text.encode()


def test_html_references_are_private_unfetched_descriptors(tmp_path):
    text = ('<p><a href="https://example.invalid/?a=1&amp;b=2">Link</a></p>'
            '<img src="file:///etc/passwd" alt="Local reference">'
            '<img src="data:image/png;base64,AAAA" alt="Inert data">')
    original, derived = source(tmp_path, text)
    result = parse_text_source(original, "html", derived)
    references = [s for s in result.segments if s.artifact]
    records = [json.loads(Path(s.artifact).read_bytes()) for s in references]
    assert [r["target"] for r in records] == [
        "https://example.invalid/?a=1&b=2", "file:///etc/passwd", "data:image/png;base64,AAAA"]
    assert all(r["fetched"] is False for r in records)
    assert [s.kind for s in references] == ["text", "image", "image"]
    assert all(s.location.image for s in references[1:])
    for segment, record in zip(references, records, strict=True):
        artifact = Path(segment.artifact)
        assert artifact.parent == derived and stat.S_IMODE(artifact.stat().st_mode) == 0o600
        assert record["location"]["start_char"] == segment.location.start_char
        assert text[segment.location.start_char:segment.location.end_char].startswith("<")
    assert any("no linked resource" in limitation for limitation in result.limitations)
    assert original.read_bytes() == text.encode()


def test_markdown_preserves_literal_source_tables_and_named_image_targets(tmp_path):
    text = ("# Title\n\n| Key | Empty | Value |\n| --- | --- | --- |\n| α | | β |\n\n"
            "![Plot](https://example.invalid/a.png \"caption\") and [Link](../other.md).\n"
            "![Named][asset]\n[asset]: https://example.invalid/b.svg\n")
    original, derived = source(tmp_path, text)
    result = parse_text_source(original, "markdown", derived)
    cells = [s for s in result.segments if s.kind == "table_cell"]
    assert [(s.text, s.location.row, s.location.column) for s in cells] == [
        ("Key", 0, 0), ("Empty", 0, 1), ("Value", 0, 2), ("α", 1, 0), ("β", 1, 2)]
    assert all(text[s.location.start_char:s.location.end_char] == s.text for s in cells)
    records = [json.loads(Path(s.artifact).read_bytes()) for s in result.segments if s.artifact]
    assert [r["target"] for r in records] == ["https://example.invalid/a.png", "../other.md",
                                            "https://example.invalid/b.svg"]
    assert all(r["fetched"] is False for r in records)
    assert any(s.text.startswith("![Plot](") for s in result.segments if not s.artifact)
    assert original.read_bytes() == text.encode()


def test_markdown_ordinary_pipe_is_not_a_table(tmp_path):
    original, derived = source(tmp_path, "An ordinary a | b expression.\n")
    result = parse_text_source(original, "markdown", derived)
    assert len(result.segments) == 1 and result.segments[0].kind == "text"


@pytest.mark.parametrize("source_format,text", [("text", " \n\t"), ("markdown", ""),
                                                ("html", "<script>hidden()</script>")])
def test_empty_content_has_no_fabricated_element(tmp_path, source_format, text):
    original, derived = source(tmp_path, text)
    assert parse_text_source(original, source_format, derived).segments == []
    assert original.read_bytes() == text.encode() and list(derived.iterdir()) == []


@pytest.mark.parametrize("data,source_format,expected", [(b"\xff", "text", "UTF-8"),
    (b"hello\x00", "markdown", "NUL"), (b"hello", "pdf", "Unsupported")])
def test_invalid_source_encoding_and_format_fail_without_output(tmp_path, data, source_format, expected):
    original, derived = source(tmp_path, data)
    with pytest.raises(ValueError, match=expected):
        parse_text_source(original, source_format, derived)
    assert original.read_bytes() == data and list(derived.iterdir()) == []


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_nonregular_original_is_rejected_before_reading(tmp_path, kind):
    original, derived = source(tmp_path, "safe")
    candidate = tmp_path / "candidate"
    if kind == "symlink":
        candidate.symlink_to(original)
    elif kind == "directory":
        candidate.mkdir()
    else:
        os.mkfifo(candidate)
    with pytest.raises(PermissionError, match="regular"):
        parse_text_source(candidate, "text", derived)
    assert original.read_text() == "safe" and list(derived.iterdir()) == []


@pytest.mark.parametrize("case", ["bytes", "text", "segments", "artifacts"])
def test_parser_bounds_fail_before_artifact_publication(tmp_path, case):
    data = {"bytes": "x" * (1024 * 1024 + 1), "text": "x" * 32769,
            "segments": "x\n\n" * 4097,
            "artifacts": "\n".join(f"![{n}](https://example.invalid/{n})" for n in range(61))}[case]
    original, derived = source(tmp_path, data)
    with pytest.raises(ValueError):
        parse_text_source(original, "markdown" if case == "artifacts" else "text", derived)
    assert original.read_bytes() == data.encode() and list(derived.iterdir()) == []


def test_output_collision_rolls_back_only_this_call_files(tmp_path):
    original, derived = source(tmp_path, "![A](a.png) ![B](b.png)")
    existing = derived / "markdown-0001.json"
    existing.write_bytes(b"keep existing bytes")
    with pytest.raises(FileExistsError):
        parse_text_source(original, "markdown", derived)
    assert existing.read_bytes() == b"keep existing bytes"
    assert list(derived.iterdir()) == [existing]


def test_symlink_derived_directory_is_not_followed(tmp_path):
    original, derived = source(tmp_path, '<img src="https://example.invalid/a">')
    alias = tmp_path / "alias"
    alias.symlink_to(derived, target_is_directory=True)
    with pytest.raises(OSError):
        parse_text_source(original, "html", alias)
    assert list(derived.iterdir()) == []


@pytest.mark.parametrize("text", ["<td>orphan</td>", "<table><tr><td><table></table></td></tr></table>"])
def test_unlocatable_or_nested_html_tables_are_explicit_errors(tmp_path, text):
    original, derived = source(tmp_path, text)
    with pytest.raises(ValueError, match="table"):
        parse_text_source(original, "html", derived)
    assert list(derived.iterdir()) == []


def test_unclosed_html_retains_observed_text_without_layout_claim(tmp_path):
    original, derived = source(tmp_path, "<p>Observed <strong>text")
    result = parse_text_source(original, "html", derived)
    assert [s.text for s in result.segments] == ["Observed text"]
    assert any("leniently" in limitation for limitation in result.limitations)
    assert all(s.location.page is None and s.location.bbox is None for s in result.segments)
