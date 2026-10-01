"""Research tool models — structured output schemas for Gemini.

Defines output schemas for research_deep, research_plan, and
research_assess_evidence tools. Used with GeminiClient.generate_structured().
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Finding(BaseModel):
    """A single research finding with evidence tier."""

    claim: str
    evidence_tier: str = (
        "UNKNOWN"  # CONFIRMED | STRONG INDICATOR | INFERENCE | SPECULATION | UNKNOWN
    )
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    reasoning: str = ""
    proposed_evidence_tier: str | None = None
    evidence_authority: str = "model_proposal"
    support_status: str = "not_verified"


class FindingsContainer(BaseModel):
    """Intermediate schema for the evidence-collection phase of research_deep.

    Used with generate_structured() to extract findings from a single
    research pass. Findings are later merged into ResearchReport.
    """

    findings: list[Finding] = Field(default_factory=list)


class ResearchSynthesis(BaseModel):
    """Intermediate schema for the synthesis phase of research_deep.

    Used with generate_structured() in the final synthesis pass.
    Fields are merged into the top-level ResearchReport before returning.
    """

    executive_summary: str = ""
    open_questions: list[str] = Field(default_factory=list)
    methodology_critique: str = ""
    recommendations: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Output schema for research_deep.

    Assembled from FindingsContainer (evidence phase) and ResearchSynthesis
    (synthesis phase). Also persisted to Weaviate via store_research_finding().
    """

    topic: str
    scope: str = "moderate"
    executive_summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    methodology_critique: str = ""


class Phase(BaseModel):
    """A single phase in a research plan."""

    name: str
    description: str
    tasks: list[str] = Field(default_factory=list)
    recommended_model: str = "configured"


class ResearchPlan(BaseModel):
    """Output schema for research_plan.

    Returned by GeminiClient.generate_structured(). Describes a phased
    research execution plan with model-tier assignments per phase.
    Also persisted to Weaviate via store_research_plan().
    """

    topic: str
    scope: str
    phases: list[Phase] = Field(default_factory=list)
    recommended_models: dict[str, str] = Field(default_factory=dict)
    task_decomposition: list[str] = Field(default_factory=list)
    subquestions: list[str] = Field(default_factory=list)
    source_rules: dict = Field(default_factory=dict)
    stop_conditions: list[str] = Field(default_factory=list)
    execution_budget: dict = Field(default_factory=dict)


class EvidenceAssessment(BaseModel):
    """Output schema for research_assess_evidence.

    Returned by GeminiClient.generate_structured(). Assesses a single
    claim against provided sources with an evidence tier and confidence score.
    Also persisted to Weaviate via store_evidence_assessment().
    """

    claim: str
    tier: str = "UNKNOWN"
    confidence: float = 0.0
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    reasoning: str = ""
    proposed_tier: str | None = None
    evidence_authority: str = "model_proposal"
    source_access: str = "not_observed"
    factual_success: bool = False
