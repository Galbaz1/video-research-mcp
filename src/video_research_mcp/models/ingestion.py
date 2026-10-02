"""Bounded original-source ingestion and explicit extracted-element locations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ingestion_location import IngestionLocation


class IngestionSegment(BaseModel):
    """One objective extraction result, separate from original bytes and later notes."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=128)
    kind: Literal["text", "table_cell", "image", "audio", "equation"]
    text: str = Field(default="", max_length=32768)
    location: IngestionLocation
    method: str = Field(min_length=1, max_length=128)
    artifact: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def validate_content(self):
        """Reject empty text extraction and incomplete typed modality locations."""
        if self.kind in {"text", "table_cell", "equation"} and not self.text.strip():
            raise ValueError("Text extraction cannot be empty")
        if self.kind == "table_cell" and self.location.row is None:
            raise ValueError("Table extraction requires cell coordinates")
        if self.kind == "image" and (self.location.image is None or self.artifact is None):
            raise ValueError("Image extraction requires a located artifact")
        if self.kind == "audio" and self.location.start_ms is None:
            raise ValueError("Audio extraction requires the original source interval")
        return self


class SourceIngestRequest(BaseModel):
    """One explicitly selected source and format with preserved caller identity."""

    model_config = ConfigDict(extra="forbid", strict=True)

    source_id: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=256)
    source_format: Literal["pdf", "docx", "markdown", "html", "text", "audio"]
    file_path: str | None = Field(default=None, min_length=1, max_length=4096)
    url: str | None = Field(default=None, min_length=1, max_length=4096)
    expected_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def one_original(self):
        """Keep local access and checked URL acquisition as exclusive routes."""
        if (self.file_path is None) == (self.url is None):
            raise ValueError("Provide exactly one original file_path or url")
        return self


class ParsedSource(BaseModel):
    """Bounded objective elements and explicit unsupported extraction details."""

    model_config = ConfigDict(extra="forbid", strict=True)

    segments: list[IngestionSegment] = Field(max_length=4096)
    limitations: list[str] = Field(default_factory=list, max_length=32)
