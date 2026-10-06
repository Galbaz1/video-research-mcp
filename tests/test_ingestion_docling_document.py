"""Docling wire observations never invent original-source or cell geometry."""

import threading
import time

import pytest
import base64
import io

from video_research_mcp.ingestion_docling_document import parse_document


def response():
    """Build a small explicit service document without loading Docling."""
    return {
        "status": "success",
        "errors": [],
        "document": {
            "filename": "original.pdf",
            "json_content": {
                "schema_name": "DoclingDocument",
                "version": "1.10.0",
                "pages": {"1": {"page_no": 1, "size": {"width": 100, "height": 100}}},
                "texts": [],
                "tables": [],
                "pictures": [],
            },
        },
    }


def provenance(charspan=(0, 0)):
    return {
        "page_no": 1,
        "charspan": list(charspan),
        "bbox": {"l": 1, "t": 2, "r": 90, "b": 90, "coord_origin": "TOPLEFT"},
    }


def table():
    return {
        "self_ref": "#/tables/0",
        "prov": [provenance()],
        "data": {
            "num_rows": 1,
            "num_cols": 1,
            "table_cells": [
                {
                    "text": "cell",
                    "start_row_offset_idx": 0,
                    "end_row_offset_idx": 1,
                    "start_col_offset_idx": 0,
                    "end_col_offset_idx": 1,
                    "row_span": 1,
                    "col_span": 1,
                    "bbox": None,
                }
            ],
        },
    }


def parse(value, tmp_path):
    return parse_document(value, tmp_path, threading.Event(), time.monotonic() + 10)


def test_table_box_does_not_become_a_cell_box(tmp_path):
    """GIVEN table provenance only THEN the normalized cell has unknown geometry."""
    value = response()
    value["document"]["json_content"]["tables"] = [table()]
    location = parse(value, tmp_path).segments[0].location
    assert (location.element, location.table, location.row, location.column) == (
        "#/tables/0",
        0,
        0,
        0,
    )
    assert location.bbox is None


def test_computed_grid_must_agree_with_actual_cells(tmp_path):
    value = response()
    item = table()
    item["data"]["grid"] = [[dict(item["data"]["table_cells"][0], text="different")]]
    value["document"]["json_content"]["tables"] = [item]
    with pytest.raises(ValueError):
        parse(value, tmp_path)


@pytest.mark.parametrize("coordinate", [True, "1", float("inf"), float("nan")])
def test_wire_geometry_rejects_coercion_and_nonfinite_values(tmp_path, coordinate):
    value = response()
    record = {
        "self_ref": "#/texts/0",
        "label": "text",
        "text": "hello",
        "prov": [provenance((0, 5))],
    }
    record["prov"][0]["bbox"]["l"] = coordinate
    value["document"]["json_content"]["texts"] = [record]
    with pytest.raises(ValueError):
        parse(value, tmp_path)


def test_partial_text_provenance_does_not_claim_whole_text_box(tmp_path):
    value = response()
    value["document"]["json_content"]["texts"] = [
        {"self_ref": "#/texts/0", "label": "text", "text": "hello", "prov": [provenance((0, 2))]}
    ]
    result = parse(value, tmp_path)
    assert result.segments[0].location.bbox is None
    assert result.segments[0].location.start_char is None


@pytest.mark.parametrize("change", ["row", "columns", "row_span", "end", "overlap", "grid"])
def test_table_grid_and_spans_are_strict(tmp_path, change):
    value = response()
    item = table()
    cell = item["data"]["table_cells"][0]
    if change == "row":
        cell["start_row_offset_idx"] = True
    if change == "columns":
        item["data"]["num_cols"] = "1"
    if change == "row_span":
        cell["row_span"] = 2
    if change == "end":
        cell["end_col_offset_idx"] = 2
    if change == "overlap":
        item["data"]["table_cells"].append(dict(cell))
    if change == "grid":
        item["data"].update(num_rows=4096, num_cols=4096)
    value["document"]["json_content"]["tables"] = [item]
    with pytest.raises(ValueError):
        parse(value, tmp_path)


def test_actual_single_page_cell_box_is_preserved(tmp_path):
    value = response()
    item = table()
    item["data"]["table_cells"][0]["bbox"] = {
        "l": 5,
        "t": 10,
        "r": 20,
        "b": 30,
        "coord_origin": "TOPLEFT",
    }
    value["document"]["json_content"]["tables"] = [item]
    location = parse(value, tmp_path).segments[0].location
    assert location.bbox == [5, 10, 20, 30]
    assert location.page == 1


def test_formula_stays_equation_and_multipage_provenance_stays_raw(tmp_path):
    value = response()
    document = value["document"]["json_content"]
    document["pages"]["2"] = {"page_no": 2, "size": {"width": 100, "height": 100}}
    other = provenance((0, 3))
    other["page_no"] = 2
    document["texts"] = [
        {
            "self_ref": "#/texts/0",
            "label": "formula",
            "text": "a=b",
            "prov": [provenance((0, 3)), other],
        }
    ]
    segment = parse(value, tmp_path).segments[0]
    assert segment.kind == "equation" and segment.text == "a=b"
    assert segment.location.bbox is None and segment.location.page is None


@pytest.mark.parametrize("change", ["ref", "dangling", "page", "population"])
def test_reference_and_population_errors_refuse_before_images(tmp_path, change):
    before = set(tmp_path.iterdir())
    value = response()
    document = value["document"]["json_content"]
    document["texts"] = [{"self_ref": "#/texts/0", "label": "text", "text": "hello", "prov": []}]
    if change == "ref":
        document["texts"][0]["self_ref"] = "#/texts/1"
    if change == "dangling":
        document["body"] = {"self_ref": "#/body", "children": [{"$ref": "#/texts/7"}]}
    if change == "page":
        document["pages"]["1"]["size"]["width"] = True
    if change == "population":
        document["texts"] *= 4097
    with pytest.raises(ValueError):
        parse(value, tmp_path)
    assert set(tmp_path.iterdir()) == before


def picture():
    from PIL import Image

    buffer = io.BytesIO()
    with Image.new("RGB", (2, 1), (64, 128, 192)) as image:
        image.save(buffer, format="PNG")
    return {
        "self_ref": "#/pictures/0",
        "prov": [provenance()],
        "image": {
            "uri": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
            "mimetype": "image/png",
            "size": {"width": 2, "height": 1},
            "dpi": 72,
        },
    }


def test_embedded_png_is_exact_parser_derivative(tmp_path):
    value = response()
    item = picture()
    value["document"]["json_content"]["pictures"] = [item]
    segment = parse(value, tmp_path).segments[0]
    assert segment.kind == "image" and segment.location.image == "#/pictures/0"
    assert segment.location.bbox == [1, 2, 90, 90]
    from pathlib import Path

    assert Path(segment.artifact).read_bytes() == base64.b64decode(
        item["image"]["uri"].split(",")[1]
    )


@pytest.mark.parametrize(
    "change", ["http", "file", "media", "size", "bool", "pixels", "base64", "bytes"]
)
def test_untrusted_image_boundary_never_fetches_external_images(tmp_path, monkeypatch, change):
    import socket

    monkeypatch.setattr(
        socket, "create_connection", lambda *args, **kwargs: pytest.fail("image SSRF")
    )
    before = set(tmp_path.iterdir())
    value = response()
    item = picture()
    if change == "http":
        item["image"]["uri"] = "http://127.0.0.1/private"
    if change == "file":
        item["image"]["uri"] = "file:///private/secret.png"
    if change == "media":
        item["image"]["mimetype"] = "image/jpeg"
    if change == "size":
        item["image"]["size"]["width"] = 3
    if change == "bool":
        item["image"]["size"]["height"] = True
    if change == "pixels":
        item["image"]["size"].update(width=10000, height=10000)
    if change == "base64":
        item["image"]["uri"] += "!"
    if change == "bytes":
        item["image"]["uri"] = "data:image/png;base64," + "A" * 350000
    value["document"]["json_content"]["pictures"] = [item]
    with pytest.raises((ValueError, OSError)):
        parse(value, tmp_path)
    assert set(tmp_path.iterdir()) == before


def test_repair_whitespace_text_skips_without_renumbering_refs(tmp_path):
    value = response()
    document = value["document"]["json_content"]
    document["texts"] = [
        {"self_ref": "#/texts/0", "label": "text", "text": " \n\t", "prov": []},
        {"self_ref": "#/texts/1", "label": "section_header", "text": "Heading", "prov": []},
        {"self_ref": "#/texts/2", "label": "formula", "text": "", "prov": []},
    ]
    document["body"] = {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]}
    parsed = parse(value, tmp_path)
    assert [segment.location.element for segment in parsed.segments] == ["#/texts/1"]
    assert parsed.segments[0].id == "docling-text-1"
    assert any("Skipped 2 whitespace-only" in line for line in parsed.limitations)
    assert document["texts"][0]["text"] == " \n\t"


@pytest.mark.parametrize("box", [
    {"l": 1, "t": 2, "r": 1, "b": 9},
    {"l": 1, "t": 2, "r": 9, "b": 2},
    {"l": -0.01, "t": 2, "r": 9, "b": 9},
    {"l": 1, "t": 2, "r": 100.01, "b": 9},
    {"l": 1, "t": 2, "r": 9, "b": 100.01},
])
@pytest.mark.parametrize("element", ["text", "cell", "picture"])
def test_repair_invalid_finite_bbox_is_unknown(tmp_path, box, element):
    value = response()
    document = value["document"]["json_content"]
    reported = {**box, "coord_origin": "TOPLEFT"}
    if element == "text":
        prov = provenance((0, 5))
        prov["bbox"] = reported
        document["texts"] = [{"self_ref": "#/texts/0", "label": "text", "text": "hello", "prov": [prov]}]
    elif element == "cell":
        item = table()
        item["data"]["table_cells"][0]["bbox"] = reported
        document["tables"] = [item]
    else:
        item = picture()
        item["prov"][0]["bbox"] = reported
        document["pictures"] = [item]
    location = parse(value, tmp_path).segments[0].location
    assert location.page == 1 and location.bbox is None
    assert location.page_width is None and location.coordinate_origin is None
    assert reported == {**box, "coord_origin": "TOPLEFT"}


def test_repair_bottomleft_bbox_keeps_origin_and_ordered_coordinates(tmp_path):
    value = response()
    prov = provenance((0, 5))
    prov["bbox"] = {"l": 5, "t": 80, "r": 90, "b": 20, "coord_origin": "BOTTOMLEFT"}
    value["document"]["json_content"]["texts"] = [{
        "self_ref": "#/texts/0", "label": "text", "text": "hello", "prov": [prov]}]
    location = parse(value, tmp_path).segments[0].location
    assert location.bbox == [5, 20, 90, 80]
    assert location.coordinate_origin == "bottom_left"
    assert (location.page_width, location.page_height) == (100, 100)
