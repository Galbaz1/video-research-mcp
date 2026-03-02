"""Document research models -- structured output schemas for research_document.

Defines output schemas for the 4-phase document research pipeline:
Phase 1 (DocumentMap), Phase 2 (DocumentFinding), Phase 3 (CrossReferenceMap),
Phase 4 (DocumentResearchReport). Used with GeminiClient.generate_structured().
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentSource(BaseModel):
    """Metadata for a single input document."""

    filename: str
    source_type: str = "file"  # "file" | "url"
    original_path: str
    page_count: int = 0
    file_uri: str = ""


class DocumentPreparationIssue(BaseModel):
    """Preparation-stage failure metadata for a single document source."""

    source: str
    phase: str = "download"  # "download" | "upload"
    error_type: str = ""
    error: str = ""


class DocumentMap(BaseModel):
    """Phase 1 output -- structure overview of a single document."""

    source_filename: str = ""
    title: str = ""
    sections: list[str] = Field(default_factory=list)
    figure_count: int = 0
    table_count: int = 0
    summary: str = ""


class DocumentCitation(BaseModel):
    """A reference back to a specific location in a source document."""

    document: str
    page: str = ""
    section: str = ""
    element: str = ""


class DocumentFinding(BaseModel):
    """Phase 2 output -- a single finding extracted from one document."""

    claim: str
    evidence_tier: str = "UNKNOWN"
    citations: list[DocumentCitation] = Field(default_factory=list)
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    reasoning: str = ""
    data_extracted: dict = Field(default_factory=dict)


class DocumentFindingsContainer(BaseModel):
    """Phase 2 structured output wrapper."""

    document: str = ""
    findings: list[DocumentFinding] = Field(default_factory=list)


class CrossReference(BaseModel):
    """A single cross-reference relationship between documents."""

    relationship: str = "agrees"
    claim: str = ""
    sources: list[DocumentCitation] = Field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""


class CrossReferenceMap(BaseModel):
    """Phase 3 output -- relationships across all documents."""

    agreements: list[CrossReference] = Field(default_factory=list)
    contradictions: list[CrossReference] = Field(default_factory=list)
    extensions: list[CrossReference] = Field(default_factory=list)
    evidence_chains: list[str] = Field(default_factory=list)


class DocumentResearchReport(BaseModel):
    """Phase 4 final output -- complete grounded research report."""

    instruction: str = ""
    scope: str = "moderate"
    document_sources: list[DocumentSource] = Field(default_factory=list)
    executive_summary: str = ""
    findings: list[DocumentFinding] = Field(default_factory=list)
    cross_references: CrossReferenceMap = Field(default_factory=CrossReferenceMap)
    preparation_issues: list[DocumentPreparationIssue] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    methodology_critique: str = ""
    recommendations: list[str] = Field(default_factory=list)
