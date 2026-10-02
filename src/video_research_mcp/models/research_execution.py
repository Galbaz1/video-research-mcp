"""Bounded source-preserving research requests and unverified model proposals."""

import json
import hashlib
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .evidence import EvidencePacket
from .image_edit import Number, StrictModel
from .vision import VisionLimits
from ..errors import ToolError


class ResearchLimits(VisionLimits):
    """One aggregate allowance for sources, required branches and revisions."""

    max_calls: Annotated[int, Field(strict=True, ge=1, le=24)] = 12
    concurrency: Annotated[int, Field(strict=True, ge=1, le=4)] = 2
    max_revisions: Annotated[int, Field(strict=True, ge=0, le=2)] = 1
    max_source_bytes: Annotated[int, Field(strict=True, ge=1, le=4 * 1024 * 1024)] = 1024 * 1024
    max_total_source_bytes: Annotated[int, Field(strict=True, ge=1, le=8 * 1024 * 1024)] = 4 * 1024 * 1024
    max_source_requests: Annotated[int, Field(strict=True, ge=0, le=48)] = 48
    timeout_seconds: Annotated[Number, Field(gt=0, le=180)] = 120
    max_cost_usd: Annotated[Number | None, Field(gt=0)] = None


class ResearchExecutionRequest(StrictModel):
    """Explicit source-free, supplied, checked-URL or hybrid research route."""

    topic: Annotated[str, Field(min_length=3, max_length=8192)]
    run_id: Annotated[str | None, Field(pattern=r"^[0-9a-f]{32}$")] = None
    mode: Literal["model_only", "supplied", "retrieval", "hybrid"] = "model_only"
    subquestions: Annotated[list[Annotated[str, Field(min_length=3, max_length=1024)]], Field(max_length=4)] = []
    supplied_packet: EvidencePacket | None = None
    source_root: Annotated[str | None, Field(min_length=1, max_length=4096)] = None
    urls: Annotated[list[Annotated[str, Field(min_length=1, max_length=2048)]], Field(max_length=8)] = []
    allowed_domains: Annotated[list[Annotated[str, Field(pattern=r"^[a-z0-9.-]{1,253}$")]], Field(max_length=8)] = []
    dry_run: Annotated[bool, Field(strict=True)] = True
    authorize_submission: Annotated[bool, Field(strict=True)] = False
    authorize_source_access: Annotated[bool, Field(strict=True)] = False
    thinking_level: Literal["low", "medium", "high"] = "medium"
    limits: ResearchLimits = ResearchLimits()

    @model_validator(mode="after")
    def source_route(self):
        """Reject ambiguous source authority and oversized packets before execution."""
        supplied = self.supplied_packet is not None
        if supplied != (self.source_root is not None):
            raise ValueError("Supplied packet and source_root are required together")
        expected = {"model_only": (False, False), "supplied": (True, False),
                    "retrieval": (False, True), "hybrid": (True, True)}
        if (supplied, bool(self.urls)) != expected[self.mode]:
            raise ValueError("mode must match the explicitly supplied packet and URLs")
        if len(self.urls) != len(set(self.urls)) or len(self.subquestions) != len(set(self.subquestions)):
            raise ValueError("URLs and subquestions must be unique")
        for url in self.urls:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 33 for c in url):
                raise ValueError("Research URLs require HTTPS without userinfo or control characters")
        count = len(self.supplied_packet.sources) if supplied else 0
        if count + len(self.urls) > 8:
            raise ValueError("Research source population exceeds eight sources")
        retrieved_ids = {"retrieved-" + hashlib.sha256(f"{i}\0{url}".encode()).hexdigest()
                         for i, url in enumerate(self.urls)}
        if supplied and any(source.id in retrieved_ids for source in self.supplied_packet.sources):
            raise ValueError("Supplied and retrieved source IDs must be distinct")
        if supplied and (len(self.supplied_packet.claims) > 64 or len(self.supplied_packet.lineage) > 256):
            raise ValueError("Supplied claim or lineage population exceeds research limits")
        if supplied:
            objects = self.supplied_packet.sources + self.supplied_packet.claims + self.supplied_packet.lineage
            objects += [p for source in self.supplied_packet.sources for p in source.passages]
            if any(len(obj.id) > 256 for obj in objects) or any(len(s.passages) > 256 for s in self.supplied_packet.sources):
                raise ValueError("Supplied IDs or passage population exceed research limits")
        if len(json.dumps(self.model_dump(mode="json"), allow_nan=False).encode()) > 4 * 1024 * 1024:
            raise ValueError("Research request exceeds four MiB of JSON")
        return self


class ResearchCitation(StrictModel):
    """Proposed source quote; its presence is never factual verification."""

    source_id: Annotated[str, Field(min_length=1, max_length=256)]
    passage_id: Annotated[str | None, Field(min_length=1, max_length=256)] = None
    quote: Annotated[str, Field(min_length=1, max_length=4096)]


class ResearchFinding(StrictModel):
    """Model wording, confidence and citations requiring independent support checks."""

    text: Annotated[str, Field(min_length=1, max_length=4096)]
    proposed_tier: Annotated[str, Field(max_length=64)] = "UNKNOWN"
    citations: Annotated[list[ResearchCitation], Field(max_length=8)] = []
    contradicting_citations: Annotated[list[ResearchCitation], Field(max_length=8)] = []
    reasoning: Annotated[str, Field(max_length=4096)] = ""
    confidence: Annotated[Number | None, Field(ge=0, le=1)] = None
    abstained: Annotated[bool, Field(strict=True)] = False


class ResearchBranchAnswer(StrictModel):
    """One subquestion round with retained gaps and contradictory evidence."""

    summary: Annotated[str, Field(max_length=8192)] = ""
    findings: Annotated[list[ResearchFinding], Field(max_length=16)] = []
    missing_evidence: Annotated[list[Annotated[str, Field(max_length=2048)]], Field(max_length=16)] = []
    contradictions: Annotated[list[Annotated[str, Field(max_length=2048)]], Field(max_length=16)] = []
    needs_revision: Annotated[bool, Field(strict=True)] = False


class ResearchExecutionResponse(StrictModel):
    """Inspectable execution outcome with factual and semantic acceptance separate."""

    status: Literal["planned", "complete", "partial"]
    run_id: str
    request_sha256: str
    mode: str
    plan: dict
    sources: list[dict]
    rejections: list[dict]
    branches: list[dict]
    findings: list[dict]
    execution: dict
    artifacts: dict
    factual_success: Literal[False] = False
    semantic_support: Literal["not_verified"] = "not_verified"
    source_content_role: Literal["data"] = "data"


class ResearchExecutionError(ToolError):
    """Retain the attempted run and its failed/pending population on refusal."""

    run_id: str | None = None
    request_sha256: str | None = None
    plan: dict
    branches: list[dict]
    execution: dict
    state_path: str | None = None
