"""Objective, bounded UTF-8 text extraction with unfetched reference descriptors."""

from __future__ import annotations

import html
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

from .media_local_io import _open_regular
from .models.ingestion import IngestionLocation, IngestionSegment, ParsedSource

MAX_TEXT_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACTS = 60


def _read_source(path: Path, limit: int) -> bytes:
    """Read bounded regular source bytes and reject a change during reading."""
    with _open_regular(path) as reader:
        before = os.fstat(reader.fileno())
        if before.st_size > limit:
            raise ValueError(f"Source exceeds the {limit}-byte parser limit")
        data = reader.read(limit + 1)
        after = os.fstat(reader.fileno())
    current = path.lstat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if len(data) > limit or len(data) != before.st_size:
        raise ValueError("Source exceeds its byte limit or changed while reading")
    if any(getattr(before, key) != getattr(value, key) for key in fields
           for value in (after, current)):
        raise ValueError("Source changed while reading")
    return data


def _canonical(value: dict) -> bytes:
    """Serialize a finite descriptor independently of external runtimes."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


class _Extraction:
    """Stage validated elements and artifacts before any exclusive filesystem write."""

    def __init__(self, directory: Path, prefix: str):
        self.directory, self.prefix = directory.absolute(), prefix
        self.segments: list[IngestionSegment] = []
        self.artifacts: dict[str, bytes] = {}

    def artifact(self, data: bytes, suffix: str = "json") -> str:
        """Stage one artifact within the shared count and aggregate byte limits."""
        if len(self.artifacts) >= MAX_ARTIFACTS:
            raise ValueError("Extraction exceeds the 60-artifact limit")
        if sum(map(len, self.artifacts.values())) + len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError("Extraction exceeds the 8 MiB artifact limit")
        name = f"{self.prefix}-{len(self.artifacts):04d}.{suffix}"
        self.artifacts[name] = data
        return str(self.directory / name)

    def add(self, kind: str, text: str, location: IngestionLocation,
            method: str, artifact: str | None = None) -> None:
        """Validate the public element bounds before accepting objective extraction."""
        if len(self.segments) >= 4096:
            raise ValueError("Extraction exceeds the 4096-segment limit")
        self.segments.append(IngestionSegment(id=f"{self.prefix}-{len(self.segments):04d}",
                                             kind=kind, text=text, location=location,
                                             method=method, artifact=artifact))

    def reference(self, target: str, location: IngestionLocation, *, image: bool,
                  label: str, details: dict) -> None:
        """Store a literal reference as data without resolving or fetching it."""
        record = {**details, "target": target, "fetched": False,
                  "location": location.model_dump(exclude_none=True)}
        artifact = self.artifact(_canonical(record))
        if image:
            location = location.model_copy(update={"image": f"reference-{len(self.segments)}"})
        self.add("image" if image else "text", label or f"Reference: {target}",
                 location, f"{self.prefix}-reference", artifact)

    def finish(self, limitations: list[str]) -> ParsedSource:
        """Publish validated artifacts privately, rolling back only this call's files."""
        parsed = ParsedSource(segments=self.segments, limitations=limitations)
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        fd, created = os.open(self.directory, flags), []
        try:
            for name, data in self.artifacts.items():
                output = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                 getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=fd)
                created.append(name)
                with os.fdopen(output, "wb") as writer:
                    os.fchmod(writer.fileno(), 0o600)
                    writer.write(data)
            return parsed
        except BaseException:
            for name in created:
                os.unlink(name, dir_fd=fd)
            raise
        finally:
            os.close(fd)


def _paragraphs(text: str, extraction: _Extraction, source_format: str) -> None:
    """Keep literal paragraphs and source-character intervals, including markup."""
    pattern = r"\S[\s\S]*?(?=\r?\n[ \t]*\r?\n|\Z)"
    for paragraph, match in enumerate(re.finditer(pattern, text)):
        end = match.end() - (len(match.group()) - len(match.group().rstrip()))
        extraction.add("text", text[match.start():end],
                       IngestionLocation(paragraph=paragraph, start_char=match.start(),
                                         end_char=end), f"{source_format}-literal")


def _markdown(text: str, extraction: _Extraction) -> None:
    """Extract simple pipe tables and inline or named Markdown references."""
    _paragraphs(text, extraction, "markdown")
    definitions = {m[1].strip().casefold(): m[2] for m in re.finditer(
        r"(?m)^[ \t]{0,3}\[([^\[\]\n]+)\]:[ \t]*<?([^\s>]+)>?", text)}
    inline = r"(!?)\[([^\[\]\n]*)\]\(([^()\n]*)\)"
    named = r"(!?)\[([^\[\]\n]+)\]\[([^\[\]\n]*)\]"
    for pattern, reference_style in ((inline, False), (named, True)):
        for match in re.finditer(pattern, text):
            raw = match[3].strip()
            target = (definitions.get((raw or match[2]).casefold(), raw or match[2])
                      if reference_style else (raw.split(maxsplit=1)[0].strip("<>") if raw else ""))
            extraction.reference(target, IngestionLocation(start_char=match.start(),
                                 end_char=match.end()), image=bool(match[1]), label=match[2],
                                 details={"format": "markdown", "reference_style": reference_style,
                                          "literal": match.group(), "resolved": target in definitions.values()
                                          if reference_style else True})
    _markdown_tables(text, extraction)


def _markdown_tables(text: str, extraction: _Extraction) -> None:
    """Measure simple pipe-cell coordinates only after an actual delimiter row."""
    table, row, offset, active = -1, 0, 0, False
    lines = text.splitlines(keepends=True)
    def is_delimiter(line):
        cells = line.strip().strip("|").split("|")
        return len(cells) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)
    for index, line in enumerate(lines):
        delimiter = is_delimiter(line)
        header = index + 1 < len(lines) and is_delimiter(lines[index + 1])
        if "|" in line and line.strip() and not delimiter and (active or header):
            if not active:
                table, row = table + 1, 0
            active = True
            left, right = 0, len(line.rstrip("\r\n"))
            if line[:right].lstrip().startswith("|"):
                left = line.index("|") + 1
            if line[:right].rstrip().endswith("|"):
                right = line.rfind("|", left, right)
            position = left
            for column, cell in enumerate(line[left:right].split("|")):
                value = cell.strip()
                if value:
                    start = offset + position + len(cell) - len(cell.lstrip())
                    extraction.add("table_cell", value, IngestionLocation(table=table, row=row,
                                   column=column, start_char=start, end_char=start + len(value)),
                                   "markdown-pipe-cell")
                position += len(cell) + 1
            row += 1
        elif not delimiter:
            active = False
        offset += len(line)


class _HTMLExtraction(HTMLParser):
    """Collect literal HTML body text, table cells and inert reference descriptors."""

    blocks = {"p", "div", "li", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
    hidden = {"script", "style", "template", "noscript", "head"}

    def __init__(self, text: str, extraction: _Extraction):
        super().__init__(convert_charrefs=False)
        self.text, self.extraction = text, extraction
        self.lines = [0] + [m.end() for m in re.finditer("\n", text)]
        self.parts, self.spans, self.suppressed = [], [], []
        self.paragraph, self.table, self.row, self.column = 0, -1, -1, -1
        self.in_table, self.cell = False, False

    def source_offset(self) -> int:
        """Map the HTML parser's measured line/column to source characters."""
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def flush(self) -> None:
        """Emit one paragraph or cell with its actual enclosing source interval."""
        value = "".join(self.parts).strip()
        if value:
            location = IngestionLocation(paragraph=self.paragraph, start_char=self.spans[0][0],
                                         end_char=self.spans[-1][1])
            if self.cell:
                location = location.model_copy(update={"table": self.table, "row": self.row,
                                                       "column": self.column})
            self.extraction.add("table_cell" if self.cell else "text", value,
                                location, "html-stdlib-text")
            self.paragraph += 1
        self.parts, self.spans = [], []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Observe references and structural positions without executing HTML."""
        attributes, start = dict(attrs), self.source_offset()
        for key in ("src", "href", "data", "srcset"):
            if attributes.get(key):
                self.extraction.reference(attributes[key], IngestionLocation(start_char=start,
                    end_char=start + len(self.get_starttag_text())), image=tag == "img",
                    label=attributes.get("alt") or "", details={"format": "html", "element": tag,
                                                               "attribute": key})
        if tag in self.hidden:
            self.suppressed.append(tag)
        if self.suppressed:
            return
        if tag in self.blocks and not self.cell:
            self.flush()
        if tag == "table":
            if self.in_table:
                raise ValueError("Nested HTML tables are unsupported")
            self.flush()
            self.in_table, self.table, self.row = True, self.table + 1, -1
        elif tag == "tr":
            self.row, self.column = self.row + 1, -1
        elif tag in {"td", "th"}:
            if not self.in_table or self.row < 0 or self.cell:
                raise ValueError("HTML table cell has no valid table row")
            self.flush()
            self.cell, self.column = True, self.column + 1
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """Finish observed cells or blocks; hidden elements produce no body text."""
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.pop()
            return
        if tag in {"td", "th"}:
            self.flush()
            self.cell = False
        elif tag == "table":
            self.flush()
            self.in_table = False
        elif tag in self.blocks and not self.cell:
            self.flush()

    def handle_data(self, data: str) -> None:
        """Keep actual character data outside explicitly non-body elements."""
        if not self.suppressed:
            start = self.source_offset()
            self.parts.append(data)
            self.spans.append((start, start + len(data)))

    def handle_entityref(self, name: str) -> None:
        """Decode a named entity while keeping its original source interval."""
        self._entity(name)

    def handle_charref(self, name: str) -> None:
        """Decode a numeric entity while keeping its original source interval."""
        self._entity(f"#{name}")

    def _entity(self, name: str) -> None:
        if not self.suppressed:
            start = self.source_offset()
            raw = f"&{name}" + (";" if self.text[start + len(name) + 1:start + len(name) + 2] == ";" else "")
            self.parts.append(html.unescape(raw))
            self.spans.append((start, start + len(raw)))


def parse_text_source(path: Path, source_format: str, directory: Path) -> ParsedSource:
    """Extract local Markdown, HTML or plain UTF-8 text with explicit limitations."""
    if source_format not in {"markdown", "html", "text"}:
        raise ValueError("Unsupported text source format")
    try:
        text = _read_source(path, MAX_TEXT_BYTES).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Text sources require valid UTF-8") from exc
    if "\x00" in text:
        raise ValueError("Text sources cannot contain NUL characters")
    extraction = _Extraction(directory, source_format)
    limitations = ["Rendered pages and bounding boxes are unknown; no layout or semantic verification."]
    if source_format == "html":
        parser = _HTMLExtraction(text, extraction)
        parser.feed(text)
        parser.close()
        parser.flush()
        limitations.append("HTML is parsed leniently; scripts, styles and hidden markup are not rendered.")
    elif source_format == "markdown":
        _markdown(text, extraction)
        limitations.append("Markdown retains literal markup; pipe tables and inline/named references only.")
    else:
        _paragraphs(text, extraction, "text")
    if extraction.artifacts:
        limitations.append("References are literal descriptor data; no linked resource was fetched or verified.")
    return extraction.finish(limitations)
