"""Original-source evidence and exact production lineage wire format, version one."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EvidenceModel(BaseModel):
    """Preserve extension fields across export/import without interpreting them."""

    model_config = ConfigDict(extra="allow", strict=True)


class EvidenceInterval(EvidenceModel):
    """Actually observed interval in the original source clock."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        """Reject empty or reversed spans."""
        if self.end_ms <= self.start_ms:
            raise ValueError("Interval end must follow start")
        return self


class SourceSnapshot(EvidenceModel):
    """Frozen UTF-8 source or media observation record; never an instruction."""

    text: str
    sha256: Digest


class SourcePassage(EvidenceModel):
    """Exact text in a frozen snapshot with an optional original media interval."""

    id: Identifier
    quote: Annotated[str, Field(min_length=1)]
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def ordered(self):
        """Require both interval endpoints together and in source order."""
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("Passage interval requires both endpoints")
        if self.start_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("Passage interval end must follow start")
        return self


class EvidenceSource(EvidenceModel):
    """Original source identity, byte commitment and separate observation record."""

    id: Identifier
    revision: Identifier
    sha256: Digest
    path: Identifier
    modality: Literal["text", "image", "video", "audio", "geometry", "tabular"]
    asset_kind: Literal["original", "extracted", "synthetic"]
    snapshot: SourceSnapshot
    passages: list[SourcePassage] = Field(default_factory=list)
    observed_intervals: list[EvidenceInterval] = Field(default_factory=list)
    duration_ms: int | None = Field(default=None, gt=0)


class EvidenceReference(EvidenceModel):
    """Binding to an original source passage rather than research prose."""

    source_id: Identifier
    passage_id: Identifier


class EvidenceClaim(EvidenceModel):
    """Editorial approval and confidence do not certify factual support."""

    id: Identifier
    text: Annotated[str, Field(min_length=1)]
    support: list[EvidenceReference] = Field(default_factory=list)
    editorial_approved: bool = False
    abstained: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)


class LineageNode(EvidenceModel):
    """Exact factual text and parent references for one production stage."""

    id: Identifier
    stage: Literal["script", "narration", "storyboard", "rendered_text"]
    channel: Literal["text", "caption", "voiceover"] = "text"
    text: Annotated[str, Field(min_length=1)]
    claim_ids: list[Identifier]
    parent_ids: list[Identifier]


class EvidencePacket(EvidenceModel):
    """Label-free research-to-production packet retaining original identities."""

    schema_version: Literal[1] = 1
    packet_id: Identifier
    sources: list[EvidenceSource]
    claims: list[EvidenceClaim]
    lineage: list[LineageNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        """Ensure references have one unambiguous target per namespace."""
        groups = [self.sources, self.claims + self.lineage]
        groups.extend(source.passages for source in self.sources)
        for group in groups:
            ids = [item.id for item in group]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate evidence ID")
        return self
