"""Base types and common properties for Weaviate collection definitions.

PropertyDef, ReferenceDef, and CollectionDef are the building blocks for
every collection schema. _common_properties() provides fields shared by
all collections (created_at, updated_at, source_tool).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PropertyDef:
    """Single property in a Weaviate collection."""

    name: str
    data_type: list[str]
    description: str = ""
    skip_vectorization: bool = False
    index_filterable: bool = True
    index_range_filters: bool = False
    index_searchable: bool | None = None  # None = Weaviate default (True for text)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to Weaviate REST API property format.

        Returns:
            Dict with name, dataType, and optional description/moduleConfig.
        """
        result: dict[str, Any] = {
            "name": self.name,
            "dataType": self.data_type,
        }
        if self.description:
            result["description"] = self.description
        if self.skip_vectorization:
            result["moduleConfig"] = {
                "text2vec-openai": {"skip": True},
            }
        return result


@dataclass
class ReferenceDef:
    """Cross-reference from one collection to another."""

    name: str
    target_collection: str
    description: str = ""


@dataclass
class CollectionDef:
    """A Weaviate collection definition."""

    name: str
    description: str = ""
    properties: list[PropertyDef] = field(default_factory=list)
    references: list[ReferenceDef] = field(default_factory=list)

    def vectorized_properties(self) -> list[str]:
        """Return names of text properties included in vectorization.

        Only text/text[] properties with skip_vectorization=False are included.
        Used by build_vector_config() to set source_properties on the vectorizer.
        """
        text_types = {"text", "text[]"}
        return [
            p.name for p in self.properties
            if not p.skip_vectorization and p.data_type[0] in text_types
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to Weaviate REST API collection (class) format.

        Returns:
            Dict with class, description, and properties list.
        """
        return {
            "class": self.name,
            "description": self.description,
            "properties": [p.to_dict() for p in self.properties],
        }


def _common_properties() -> list[PropertyDef]:
    """Return properties shared by all collections (created_at, updated_at, source_tool)."""
    return [
        PropertyDef(
            "created_at", ["date"], "Timestamp of creation",
            skip_vectorization=True, index_range_filters=True,
        ),
        PropertyDef(
            "updated_at", ["date"], "Timestamp of last update",
            skip_vectorization=True, index_range_filters=True,
        ),
        PropertyDef(
            "source_tool", ["text"], "Tool that generated this data",
            skip_vectorization=True, index_searchable=False,
        ),
    ]
