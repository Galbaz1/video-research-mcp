"""Bounded first-party DOCX ZIP/XML extraction without rendering or linked access."""

from __future__ import annotations

import io
import json
import posixpath
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from .ingestion_text import MAX_ARTIFACT_BYTES, _canonical, _Extraction, _read_source
from .models.ingestion import IngestionLocation, ParsedSource

WORD = {"http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "http://purl.oclc.org/ooxml/wordprocessingml/main"}
RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_ATTRS = {"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
             "http://purl.oclc.org/ooxml/officeDocument/relationships"}
MATH = {"http://schemas.openxmlformats.org/officeDocument/2006/math",
        "http://purl.oclc.org/ooxml/officeDocument/math"}
DRAWING = {"http://schemas.openxmlformats.org/drawingml/2006/main",
           "http://purl.oclc.org/ooxml/drawingml/main"}


def _tag(node: ET.Element) -> tuple[str, str]:
    """Keep namespaces authoritative while selecting XML element names."""
    if node.tag.startswith("{"):
        return tuple(node.tag[1:].split("}", 1))
    return "", node.tag


def _package(data: bytes) -> dict[str, bytes]:
    """Reject unsafe ZIP members before bounded decompression and CRC verification."""
    members = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 128:
                raise ValueError("DOCX exceeds the 128-member ZIP limit")
            total = 0
            for info in infos:
                name, mode = info.orig_filename, info.external_attr >> 16
                parts = name.rstrip("/").split("/")
                if (not name or len(name) > 256 or name.startswith("/") or "\\" in name
                        or ":" in name or any(ord(c) < 32 for c in name)
                        or any(part in {"", ".", ".."} for part in parts)):
                    raise ValueError("DOCX contains an unsafe ZIP member name")
                if name in members:
                    raise ValueError("DOCX contains a duplicate ZIP member")
                if info.flag_bits & 1:
                    raise ValueError("Encrypted DOCX ZIP members are unsupported")
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ValueError("DOCX ZIP members must be regular files or directories")
                if (stat.S_IFMT(mode) == stat.S_IFDIR and not info.is_dir()) or (info.is_dir() and info.file_size):
                    raise ValueError("DOCX ZIP directory member is malformed")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError("DOCX ZIP compression must be stored or deflated")
                total += info.file_size
                if total > MAX_ARTIFACT_BYTES:
                    raise ValueError("DOCX exceeds the 8 MiB uncompressed ZIP limit")
                if info.file_size > max(1, info.compress_size) * 200:
                    raise ValueError("DOCX exceeds the 200:1 ZIP expansion limit")
                value = archive.read(info)
                if len(value) != info.file_size:
                    raise ValueError("DOCX member size differs from its ZIP commitment")
                members[name] = value
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ValueError("DOCX ZIP is malformed or unreadable") from exc
    return members


def _xml(data: bytes) -> ET.Element:
    """Parse UTF-8 XML without DTD/entities and bound node count and nesting."""
    try:
        text = data.decode("utf-8-sig")
        if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
            raise ValueError("DOCX XML DTD and entity declarations are unsupported")
        depth, count, root = 0, 0, None
        for event, element in ET.iterparse(io.StringIO(text), events=("start", "end")):
            if event == "start":
                root = element if root is None else root
                depth, count = depth + 1, count + 1
                if depth > 64 or count > 32768:
                    raise ValueError("DOCX XML exceeds its depth or element-count limit")
            else:
                depth -= 1
        if root is None:
            raise ValueError("DOCX XML has no root")
        return root
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise ValueError("DOCX requires well-formed UTF-8 XML") from exc


def _target(target: str) -> str:
    """Resolve an internal relationship inside the ZIP, never on the filesystem."""
    parsed = urlsplit(target)
    decoded = unquote(parsed.path)
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
            or decoded.startswith("/") or "\\" in decoded or ":" in decoded
            or any(ord(c) < 32 for c in decoded)):
        raise ValueError("DOCX internal relationship has an unsafe target")
    resolved = posixpath.normpath(posixpath.join("word", decoded))
    if resolved == ".." or resolved.startswith("../"):
        raise ValueError("DOCX relationship escapes its ZIP package")
    return resolved


def _relationships(members: dict[str, bytes]) -> dict[str, dict]:
    """Validate unique relationships, retaining external targets as unfetched data."""
    data = members.get("word/_rels/document.xml.rels")
    if data is None:
        return {}
    root, result = _xml(data), {}
    if root.tag != f"{{{RELATIONSHIPS}}}Relationships":
        raise ValueError("DOCX relationship XML has an unsupported root")
    for node in root:
        if node.tag != f"{{{RELATIONSHIPS}}}Relationship":
            raise ValueError("DOCX relationship XML has an unsupported element")
        identifier, target = node.get("Id", ""), node.get("Target", "")
        mode, relation_type = node.get("TargetMode", "Internal"), node.get("Type", "")
        if (not identifier or len(identifier) > 128 or identifier in result or not target
                or len(target) > 4096 or not relation_type or mode not in {"Internal", "External"}):
            raise ValueError("DOCX relationship requires a unique ID, type and bounded target")
        record = {"id": identifier, "target": target, "type": relation_type,
                  "external": mode == "External"}
        if not record["external"]:
            record["member"] = _target(target)
            if record["member"] not in members or record["member"].endswith("/"):
                raise ValueError("DOCX internal relationship points to a missing regular member")
        result[identifier] = record
    return result


def _text(paragraph: ET.Element) -> str:
    """Preserve explicit Word text, tabs and line breaks without computing fields."""
    values = []
    for node in paragraph.iter():
        namespace, local = _tag(node)
        if namespace in WORD:
            if local in {"t", "delText"}:
                values.append(node.text or "")
            elif local == "tab":
                values.append("\t")
            elif local in {"br", "cr"}:
                values.append("\n")
    return "".join(values)


class _DOCXExtraction:
    """Extract the main document's actual XML paragraphs, cells and references."""

    def __init__(self, members: dict[str, bytes], root: ET.Element, directory: Path):
        self.members, self.relationships = members, _relationships(members)
        self.output = _Extraction(directory, "docx")
        self.paragraphs = {id(node): index for index, node in enumerate(
            node for node in root.iter() if _tag(node)[0] in WORD and _tag(node)[1] == "p")}
        self.tables = {id(node): index for index, node in enumerate(
            node for node in root.iter() if _tag(node)[0] in WORD and _tag(node)[1] == "tbl")}
        self.images: dict[str, str] = {}

    def references(self, paragraph: ET.Element, location: IngestionLocation) -> None:
        """Retain image relationships, hyperlink descriptors and literal math XML."""
        for node in paragraph.iter():
            namespace, local = _tag(node)
            if namespace in MATH and local == "oMath":
                literal = "".join(n.text or "" for n in node.iter() if _tag(n) == (namespace, "t"))
                artifact = self.output.artifact(_canonical({"format": "docx-ooxml-math",
                    "xml": ET.tostring(node, encoding="unicode"), "rendered": False}))
                self.output.add("equation", literal or "OOXML equation", location,
                                "docx-ooxml-math", artifact)
            image = ((namespace in DRAWING and local == "blip")
                     or (namespace == "urn:schemas-microsoft-com:vml" and local == "imagedata"))
            if not image and not (namespace in WORD and local == "hyperlink"):
                continue
            self.relationship(node, location, image)

    def relationship(self, node: ET.Element, location: IngestionLocation, image: bool) -> None:
        """Bind a reference to exactly one typed relationship or a local bookmark."""
        identifiers = [node.get(f"{{{ns}}}{attribute}") for ns in REL_ATTRS
            for attribute in ("embed", "link", "id") if node.get(f"{{{ns}}}{attribute}")]
        if len(identifiers) > 1:
            raise ValueError("DOCX reference has ambiguous relationship attributes")
        identifier = identifiers[0] if identifiers else None
        if identifier is None:
            if image:
                raise ValueError("DOCX image reference has no relationship ID")
            anchor = node.get(f"{{{_tag(node)[0]}}}anchor")
            if anchor:
                self.output.reference(f"#{anchor}", location, image=False, label=_text(node),
                                      details={"format": "docx", "external": False})
            return
        if identifier not in self.relationships:
            raise ValueError("DOCX references a missing relationship")
        relation = self.relationships[identifier]
        if not relation["type"].endswith("/image" if image else "/hyperlink"):
            raise ValueError("DOCX reference has an incompatible relationship type")
        if relation["external"] or not image:
            self.output.reference(relation["target"], location, image=image,
                label=_text(node), details={"format": "docx", **relation})
        else:
            member = relation["member"]
            if member not in self.images:
                extension = PurePosixPath(member).suffix.lower().lstrip(".")
                extension = extension if extension in {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "svg"} else "bin"
                self.images[member] = self.output.artifact(self.members[member], extension)
            image_location = location.model_copy(update={"image": identifier})
            self.output.add("image", json.dumps(relation, sort_keys=True), image_location,
                            "docx-embedded-original-bytes", self.images[member])

    def paragraph(self, node: ET.Element, cell: dict | None = None) -> str:
        """Record a paragraph's references and its position in document XML order."""
        location = IngestionLocation(paragraph=self.paragraphs[id(node)], **(cell or {}))
        value = _text(node)
        if cell is None and value.strip():
            self.output.add("text", value, location, "docx-ooxml-text")
        self.references(node, location)
        return value

    def blocks(self, node: ET.Element, cell: dict | None = None) -> list[str]:
        """Walk document containers without treating nested tables as parent-cell text."""
        values = []
        for child in node:
            namespace, local = _tag(child)
            if namespace in WORD and local == "p":
                values.append(self.paragraph(child, cell))
            elif namespace in WORD and local == "tbl":
                self.table(child)
            else:
                values.extend(self.blocks(child, cell))
        return values

    def table(self, node: ET.Element) -> None:
        """Retain zero-based table/row/column positions, including nested tables."""
        rows = [child for child in node if _tag(child)[0] in WORD and _tag(child)[1] == "tr"]
        for row, tr in enumerate(rows):
            cells = [child for child in tr if _tag(child)[0] in WORD and _tag(child)[1] == "tc"]
            for column, tc in enumerate(cells):
                cell = {"table": self.tables[id(node)], "row": row, "column": column}
                value = "\n".join(self.blocks(tc, cell))
                if value.strip():
                    self.output.add("table_cell", value, IngestionLocation(**cell),
                                    "docx-ooxml-cell")


def parse_docx_source(path: Path, directory: Path) -> ParsedSource:
    """Extract bounded DOCX body content, preserving originals and inert references."""
    members = _package(_read_source(path, MAX_ARTIFACT_BYTES))
    if "word/document.xml" not in members:
        raise ValueError("DOCX has no word/document.xml")
    root = _xml(members["word/document.xml"])
    namespace, local = _tag(root)
    if namespace not in WORD or local != "document":
        raise ValueError("DOCX main XML is not a Word document")
    body = root.find(f"{{{namespace}}}body")
    if body is None:
        raise ValueError("DOCX main document has no body")
    parser = _DOCXExtraction(members, root, directory)
    parser.blocks(body)
    limitations = ["Rendered pages, bounding boxes and image dimensions are unknown; no DOCX rendering.",
        "Only main-document body XML is extracted; headers, footers, comments and footnotes are omitted.",
        "Fields, tracked changes and merged-cell layout are not evaluated; explicit XML text is retained.",
        "Equations retain literal math text and OOXML; visual mathematical interpretation is unverified.",
        "Embedded image bytes are preserved without decoding; linked resources remain unfetched descriptor data.",
        "ZIP input and expansion are bounded to 8 MiB, 128 members and 200:1; XML is UTF-8 only."]
    return parser.output.finish(limitations)
