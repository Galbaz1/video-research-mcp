"""Explicit local tutorial requests with source-absolute step proposals."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .image_edit import Digest, Number, StrictModel
from .media_perception import AVPerceptionRequest


def winansi(value: str) -> str:
    """Refuse unsupported glyphs rather than silently substituting a cleared font."""
    try:
        value.encode("cp1252")
    except UnicodeEncodeError as error:
        raise ValueError("Tutorial PDF supports WinAnsi text only; unsupported glyph") from error
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError("Tutorial text contains unsupported control characters")
    return value


class VideoNoteStep(StrictModel):
    """A caller proposal or labeled inference; timestamps do not prove instruction truth."""

    title: Annotated[str, Field(min_length=1, max_length=160)]
    instruction: Annotated[str, Field(min_length=1, max_length=2048)]
    start_seconds: Annotated[Number, Field(ge=0, le=86400)]
    end_seconds: Annotated[Number, Field(gt=0, le=86400)]

    @model_validator(mode="after")
    def bounded_step(self):
        """Validate nonempty finite intervals and the selected base-font character set."""
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Tutorial step end must exceed start")
        winansi(self.title)
        winansi(self.instruction)
        return self


class VideoNoteRequest(StrictModel):
    """One exact original, supplied fallback steps and an optional explicit AV grant."""

    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest
    title: Annotated[str, Field(min_length=1, max_length=160)]
    output_path: Annotated[str, Field(min_length=1, max_length=4096)]
    steps: Annotated[list[VideoNoteStep], Field(min_length=1, max_length=16)]
    dry_run: Annotated[bool, Field(strict=True)] = True
    overwrite: Annotated[bool, Field(strict=True)] = False
    perception: AVPerceptionRequest | None = None

    @model_validator(mode="after")
    def ordered_plan(self):
        """Keep exact supplied text and reject reordered, overlapping or mismatched proposals."""
        winansi(self.title)
        if any(right.start_seconds < left.end_seconds for left, right in zip(self.steps, self.steps[1:])):
            raise ValueError("Tutorial steps must be ordered without overlap")
        if self.perception and self.perception.expected_source_sha256 != self.expected_source_sha256:
            raise ValueError("Perception must bind the same original source SHA256")
        return self


class VideoNoteResult(StrictModel):
    """Artifact creation and performed checks, independently of pending factual review."""

    status: Literal["dry_run", "complete"]
    operation: Literal["video_note_create"] = "video_note_create"
    source: dict
    supplied_steps: list[VideoNoteStep]
    steps: list[dict]
    output_path: str
    artifact_directory: str | None = None
    pdf: dict | None = None
    manifest: dict | None = None
    receipt: dict | None = None
    page_count: int = 0
    frames: list[dict] = []
    warnings: list[str] = []
    perception: dict
    verification: dict
    provenance: dict
    limits: dict
