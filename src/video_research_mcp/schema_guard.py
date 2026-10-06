"""Schema complexity guard — prevents Gemini structured output failures.

Gemini's structured output has undocumented limits on schema depth,
property count, and enum size. This module catches violations early
with clear error messages instead of opaque API failures.
"""

from __future__ import annotations


class SchemaComplexityError(ValueError):
    """Raised when a JSON schema exceeds Gemini's structured output limits."""


def check_schema_complexity(
    schema: dict,
    *,
    max_depth: int = 5,
    max_properties: int = 50,
    max_enum_size: int = 20,
) -> None:
    """Validate schema complexity against Gemini's structured output limits.

    Args:
        schema: JSON Schema dict to validate.
        max_depth: Maximum nesting depth allowed.
        max_properties: Maximum total properties across all levels.
        max_enum_size: Maximum number of values in any single enum.

    Raises:
        SchemaComplexityError: If any limit is exceeded.
    """
    depth = _measure_depth(schema)
    if depth > max_depth:
        raise SchemaComplexityError(
            f"Schema depth {depth} exceeds limit {max_depth}. "
            "Flatten nested objects or reduce nesting."
        )

    count = _count_properties(schema)
    if count > max_properties:
        raise SchemaComplexityError(
            f"Schema has {count} properties, exceeds limit {max_properties}. "
            "Simplify the schema or split into multiple calls."
        )

    _check_enums(schema, max_enum_size)


def _schema_children(schema: dict):
    """Visit the inline schema keywords supported by TextRequest, with depth steps."""
    for key in ("properties", "$defs", "definitions", "dependentSchemas"):
        for child in schema.get(key, {}).values():
            if isinstance(child, dict):
                yield child, 1
    for key in (
        "items", "additionalProperties", "contains", "propertyNames", "not", "if",
        "then", "else", "unevaluatedItems", "unevaluatedProperties", "contentSchema",
    ):
        child = schema.get(key)
        if isinstance(child, dict):
            yield child, 1
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        step = 1 if key == "prefixItems" else 0
        for child in schema.get(key, []):
            if isinstance(child, dict):
                yield child, step


def _measure_depth(schema: dict, current: int = 0) -> int:
    """Recursively measure the maximum nesting depth of a JSON schema."""
    maximum = current
    for child, step in _schema_children(schema):
        maximum = max(maximum, _measure_depth(child, current + step))
    return maximum


def _count_properties(schema: dict) -> int:
    """Count total properties across all supported inline subschemas."""
    count = len(schema.get("properties", {}))
    for child, _ in _schema_children(schema):
        count += _count_properties(child)
    return count


def _check_enums(schema: dict, max_size: int) -> None:
    """Raise SchemaComplexityError if any supported subschema enum exceeds max_size."""
    if "enum" in schema and len(schema["enum"]) > max_size:
        raise SchemaComplexityError(
            f"Enum has {len(schema['enum'])} values, exceeds limit {max_size}."
        )
    for child, _ in _schema_children(schema):
        _check_enums(child, max_size)
