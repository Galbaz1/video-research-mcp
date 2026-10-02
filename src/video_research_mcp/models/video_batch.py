"""Batch video analysis models — output schemas for video_batch_analyze.

BatchVideoResult aggregates per-file results from scanning a directory.
Each file is analysed individually via video_analyze, and the result
(or error) is captured in a BatchVideoItem.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BatchVideoItem(BaseModel):
    """Result for a single file in a batch analysis.

    Wraps either a successful analysis dict or an error message for one file.
    """

    file_name: str
    file_path: str
    result: dict = Field(default_factory=dict)
    error: str = ""
    status: str = "completed"


class BatchVideoResult(BaseModel):
    """Output schema for video_batch_analyze.

    Returned directly by the tool — not used with generate_structured since
    each file is analysed individually and results are aggregated locally.
    """

    directory: str
    total_files: int
    successful: int
    failed: int
    canceled: int = 0
    partial: int = 0
    items: list[BatchVideoItem] = Field(default_factory=list)
