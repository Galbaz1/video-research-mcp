"""Conservative rectangular inference from measured Poppler word geometry."""

from __future__ import annotations

import hashlib
from xml.etree import ElementTree

from .models.ingestion import IngestionLocation

NS = "{http://www.w3.org/1999/xhtml}"


def _cells(words):
    """Split a row only at the frozen 24-point gap; abstain on overlapping prose."""
    cells = []
    for word in sorted(words, key=lambda w: w["bbox"][0]):
        gap = word["bbox"][0] - cells[-1][-1]["bbox"][2] if cells else 24
        if gap < 0:
            return []
        if gap >= 24:
            cells.append([])
        cells[-1].append(word)
    if any(len(c) > 5 or any(w["text"].endswith((".", "?", "!", ";")) for w in c) for c in cells):
        return []
    return cells if 2 <= len(cells) <= 8 else []


def _runs(words):
    """Require repeated column starts and regular, nonoverlapping row spacing."""
    rows = []
    for word in sorted(words, key=lambda w: (w["bbox"][1], w["bbox"][0])):
        if not rows or word["bbox"][1] - rows[-1][0]["bbox"][1] > 2:
            rows.append([])
        rows[-1].append(word)
    run, result = [], []
    for row in rows:
        cells = _cells(row)
        aligned = bool(run and cells and len(cells) == len(run[0]))
        if aligned:
            aligned = all(abs(c[0]["bbox"][0] - old[0]["bbox"][0]) <= 2
                          for c, old in zip(cells, run[0]))
            aligned = aligned and min(w["bbox"][1] for w in row) >= max(
                w["bbox"][3] for c in run[-1] for w in c)
        if aligned and len(run) >= 2:
            spacing = run[1][0][0]["bbox"][1] - run[0][0][0]["bbox"][1]
            aligned = abs(cells[0][0]["bbox"][1] - run[-1][0][0]["bbox"][1] - spacing) <= 2
        if not aligned:
            if len(run) >= 3:
                result.append(run)
            run = []
        if cells:
            run.append(cells)
    if len(run) >= 3:
        result.append(run)
    return result


def _bounds(words):
    """Union word content, without inferring ruling lines or cell borders."""
    return [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
            max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]


def rectangular_tables(data: bytes, source_sha256: str) -> list[dict]:
    """Infer unit-span grids; retain native word ordinals and explicit uncertainty."""
    if b"<!ENTITY" in data:
        raise ValueError("PDF parser emitted an unsupported XML entity declaration")
    tables = []
    total = 0
    for number, page in enumerate(ElementTree.fromstring(data).iter(NS + "page"), 1):
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        words = []
        for ordinal, word in enumerate(page.iter(NS + "word")):
            text = "".join(word.itertext()).strip()
            if not text:
                continue
            total += 1
            if total > 4096:
                raise ValueError("PDF extraction exceeds 4096 elements")
            box = [float(word.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax")]
            try:
                IngestionLocation(page=number, bbox=box, coordinate_origin="top_left",
                                  page_width=width, page_height=height)
            except ValueError:
                words = []
                break
            words.append({"ordinal": ordinal, "text": text, "bbox": box})
        for run in _runs(words):
            cells = []
            for r, row in enumerate(run):
                for c, cell in enumerate(row):
                    cells.append({"row": r, "column": c, "row_span": 1, "column_span": 1,
                                  "text": " ".join(w["text"] for w in cell), "bbox": _bounds(cell),
                                  "source_word_ordinals": [w["ordinal"] for w in cell]})
            tables.append({"page": number, "table": len(tables), "rows": len(run),
                           "columns": len(run[0]), "cells": cells, "bbox": _bounds(
                               [w for row in run for cell in row for w in cell]),
                           "coordinate_origin": "top_left", "page_width": width, "page_height": height,
                           "source_pdf_sha256": source_sha256,
                           "raw_xml_sha256": hashlib.sha256(data).hexdigest(),
                           "method": "positioned-text-rectangular-inference-v1",
                           "limitations": "Content bounds are not ruling-line bounds; semantic accuracy unknown"})
    return tables
