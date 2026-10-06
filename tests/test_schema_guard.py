"""Tests for schema complexity guard."""

from __future__ import annotations

import pytest

from video_research_mcp.schema_guard import SchemaComplexityError, check_schema_complexity


class TestSchemaComplexity:
    def test_simple_schema_passes(self):
        """Flat schema with few properties passes all checks."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        check_schema_complexity(schema)

    def test_depth_exceeded(self):
        """Deeply nested schema raises SchemaComplexityError."""
        schema = {"type": "object", "properties": {
            "a": {"type": "object", "properties": {
                "b": {"type": "object", "properties": {
                    "c": {"type": "object", "properties": {
                        "d": {"type": "object", "properties": {
                            "e": {"type": "object", "properties": {
                                "f": {"type": "string"},
                            }},
                        }},
                    }},
                }},
            }},
        }}
        with pytest.raises(SchemaComplexityError, match="depth"):
            check_schema_complexity(schema, max_depth=5)

    def test_property_count_exceeded(self):
        """Schema with too many properties raises SchemaComplexityError."""
        props = {f"prop_{i}": {"type": "string"} for i in range(60)}
        schema = {"type": "object", "properties": props}
        with pytest.raises(SchemaComplexityError, match="properties"):
            check_schema_complexity(schema, max_properties=50)

    def test_enum_size_exceeded(self):
        """Enum with too many values raises SchemaComplexityError."""
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": [f"val_{i}" for i in range(25)]},
            },
        }
        with pytest.raises(SchemaComplexityError, match="Enum"):
            check_schema_complexity(schema, max_enum_size=20)

    def test_array_items_depth(self):
        """Array items contribute to depth measurement."""
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {
                "nested": {"type": "object", "properties": {
                    "deep": {"type": "object", "properties": {
                        "deeper": {"type": "object", "properties": {
                            "deepest": {"type": "object", "properties": {
                                "leaf": {"type": "string"},
                            }},
                        }},
                    }},
                }},
            }},
        }
        with pytest.raises(SchemaComplexityError, match="depth"):
            check_schema_complexity(schema, max_depth=4)

    def test_custom_limits(self):
        """Custom limits override defaults."""
        schema = {
            "type": "object",
            "properties": {f"p{i}": {"type": "string"} for i in range(10)},
        }
        with pytest.raises(SchemaComplexityError, match="properties"):
            check_schema_complexity(schema, max_properties=5)
        # With higher limit, it passes
        check_schema_complexity(schema, max_properties=20)


_SCHEMA_CHILDREN = (
    "properties", "$defs", "definitions", "dependentSchemas",
    "items", "additionalProperties", "contains", "propertyNames", "not", "if",
    "then", "else", "unevaluatedItems", "unevaluatedProperties", "contentSchema",
    "allOf", "anyOf", "oneOf", "prefixItems",
)


def _under(keyword, child):
    """Construct a supported inline subschema at the requested keyword."""
    if keyword in {"properties", "$defs", "definitions", "dependentSchemas"}:
        return {keyword: {"value": child}}
    if keyword in {"allOf", "anyOf", "oneOf", "prefixItems"}:
        return {keyword: [child]}
    return {keyword: child}


@pytest.mark.parametrize("keyword", _SCHEMA_CHILDREN)
def test_supported_subschemas_enforce_enum_limit(keyword):
    """GIVEN an inline subschema WHEN its enum exceeds the cap THEN reject it."""
    schema = _under(keyword, {"type": "string", "enum": [f"v{i}" for i in range(21)]})
    with pytest.raises(SchemaComplexityError, match="Enum"):
        check_schema_complexity(schema)


@pytest.mark.parametrize("keyword", _SCHEMA_CHILDREN)
def test_supported_subschemas_count_nested_properties(keyword):
    """GIVEN nested properties at a supported keyword THEN the global cap applies."""
    schema = _under(keyword, {"properties": {str(i): {} for i in range(51)}})
    with pytest.raises(SchemaComplexityError, match="properties"):
        check_schema_complexity(schema)


def test_additional_properties_depth_is_bounded():
    """GIVEN six nested additionalProperties schemas THEN the depth cap applies."""
    schema = {"type": "string"}
    for _ in range(6):
        schema = {"type": "object", "additionalProperties": schema}
    with pytest.raises(SchemaComplexityError, match="depth"):
        check_schema_complexity(schema)


@pytest.mark.parametrize("value", [True, False])
def test_boolean_subschemas_require_no_recursive_work(value):
    """GIVEN boolean subschemas THEN complexity checks accept their finite leaves."""
    for keyword in _SCHEMA_CHILDREN:
        check_schema_complexity(_under(keyword, value))


def test_combinators_keep_existing_depth_and_enum_boundary():
    """GIVEN a combinator wrapper THEN its prior depth rule and enum cap remain."""
    schema = {"allOf": [{"properties": {"name": {"enum": list(range(20))}}}]}
    check_schema_complexity(schema, max_depth=1)


def test_text_request_rejects_additional_properties_enum_before_submission():
    """GIVEN a valid text request schema with 21 enum values THEN validation refuses it."""
    from pydantic import ValidationError
    from video_research_mcp.models.text_provider import TextRequest

    with pytest.raises(ValidationError, match="Enum"):
        TextRequest(backend="bounded", instruction="Extract data", output_schema={
            "type": "object", "additionalProperties": {"enum": list(range(21))},
        })
