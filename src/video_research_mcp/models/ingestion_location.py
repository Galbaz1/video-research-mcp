"""Shared measured document positions and source intervals for both MCP packages."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IngestionLocation(BaseModel):
    """Observed document positions or intervals; absent fields remain unknown."""

    model_config = ConfigDict(extra="forbid", strict=True)

    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=0)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    coordinate_origin: Literal["top_left", "bottom_left"] | None = None
    page_width: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    page_height: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    table: int | None = Field(default=None, ge=0)
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    image: str | None = Field(default=None, min_length=1, max_length=256)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_positions(self):
        """Require paired finite coordinates and ordered source ranges."""
        import math

        for start, end in [(self.start_char, self.end_char), (self.start_ms, self.end_ms)]:
            if (start is None) != (end is None) or (start is not None and end <= start):
                raise ValueError("Location range requires two ordered endpoints")
        if self.bbox is None and any(value is not None for value in (
            self.coordinate_origin, self.page_width, self.page_height,
        )):
            raise ValueError("Page geometry requires an observed bounding box")
        if not any(value is not None for value in (
            self.page, self.paragraph, self.start_char, self.table, self.image, self.start_ms,
        )):
            raise ValueError("Location requires an observed source position or interval")
        if self.bbox is not None:
            if self.page is None or self.coordinate_origin is None:
                raise ValueError("Bounding box requires page and coordinate origin")
            x0, y0, x1, y1 = self.bbox
            if not all(math.isfinite(v) for v in self.bbox) or not (0 <= x0 < x1 and 0 <= y0 < y1):
                raise ValueError("Bounding box must contain finite ordered XY coordinates")
            if self.page_width is None or self.page_height is None:
                raise ValueError("Bounding box requires measured page dimensions")
            if x1 > self.page_width or y1 > self.page_height:
                raise ValueError("Bounding box exceeds page dimensions")
        if self.row is not None or self.column is not None:
            if self.table is None or self.row is None or self.column is None:
                raise ValueError("Table cell requires table, row and column")
        return self

