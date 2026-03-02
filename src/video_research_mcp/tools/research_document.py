"""Document research tool -- multi-phase evidence-tiered pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Awaitable, TypeVar

from google.genai import types
from mcp.types import ToolAnnotations
from pydantic import Field

from ..client import GeminiClient
from ..config import get_config
from ..errors import make_tool_error
from ..tracing import trace
from ..models.research_document import (
    CrossReferenceMap,
    DocumentFindingsContainer,
    DocumentMap,
    DocumentPreparationIssue,
    DocumentResearchReport,
    DocumentSource,
)
from ..prompts.research_document import (
    CROSS_REFERENCE,
    DOCUMENT_EVIDENCE,
    DOCUMENT_MAP,
    DOCUMENT_RESEARCH_SYSTEM,
    DOCUMENT_SYNTHESIS,
)
from ..types import Scope, ThinkingLevel, coerce_json_param
from ..weaviate_store import store_research_finding
from .research import research_server
from .research_document_file import _prepare_all_documents_with_issues

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def _gather_bounded(coros: list[Awaitable[T]], limit: int) -> list[T]:
    """Run awaitables with bounded concurrency while preserving order."""
    semaphore = asyncio.Semaphore(limit)

    async def _run(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    return list(await asyncio.gather(*[_run(coro) for coro in coros]))


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_document", span_type="TOOL")
async def research_document(
    instruction: Annotated[str, Field(
        description="Research question or analysis instruction for the documents"
    )],
    file_paths: Annotated[list[str] | None, Field(
        description="Local PDF/document file paths"
    )] = None,
    urls: Annotated[list[str] | None, Field(
        description="URLs to PDF documents (downloaded and uploaded to Gemini)"
    )] = None,
    scope: Scope = "moderate",
    thinking_level: ThinkingLevel = "high",
) -> dict:
    """Run multi-phase deep research grounded in source documents.

    Phases: Document Mapping -> Evidence Extraction -> Cross-Reference -> Synthesis.
    Every claim is labeled with evidence tiers and cited back to source documents.

    Args:
        instruction: Research question or what to analyze across documents.
        file_paths: Local paths to PDF or text files.
        urls: URLs to downloadable documents.
        scope: Research depth -- quick, moderate, deep, comprehensive.
        thinking_level: Gemini thinking depth.

    Returns:
        Dict with document_sources, executive_summary, findings, cross_references.
    """
    file_paths = coerce_json_param(file_paths, list)
    urls = coerce_json_param(urls, list)

    if not file_paths and not urls:
        return make_tool_error(ValueError("Provide at least one of: file_paths or urls"))
    cfg = get_config()
    total_sources = len(file_paths or []) + len(urls or [])
    if total_sources > cfg.research_document_max_sources:
        return make_tool_error(
            ValueError(
                "Too many document sources requested: "
                f"{total_sources} > configured limit {cfg.research_document_max_sources}. "
                "Split into smaller batches or raise RESEARCH_DOCUMENT_MAX_SOURCES."
            )
        )

    try:
        prepared, prep_issue_dicts = await _prepare_all_documents_with_issues(file_paths, urls)
        prep_issues = [DocumentPreparationIssue(**issue) for issue in prep_issue_dicts]
        if not prepared:
            total = len(file_paths or []) + len(urls or [])
            return make_tool_error(ValueError(
                f"No documents could be prepared from {total} source(s). "
                "Check that file paths exist and URLs are publicly accessible."
            ))

        sources = [
            DocumentSource(
                filename=orig.rsplit("/", 1)[-1],
                source_type="url" if orig.startswith("http") else "file",
                original_path=orig,
                file_uri=uri,
            )
            for uri, _cid, orig in prepared
        ]
        file_parts = [
            types.Part(file_data=types.FileData(file_uri=uri))
            for uri, _cid, _orig in prepared
        ]

        doc_maps = await _phase_document_map(file_parts, sources, instruction, thinking_level)

        if scope == "quick":
            return await _quick_synthesis(
                file_parts, sources, instruction, doc_maps, prep_issues, thinking_level,
            )

        all_findings = await _phase_evidence_extraction(
            file_parts, sources, instruction, doc_maps, thinking_level,
        )

        cross_refs = CrossReferenceMap()
        if len(prepared) > 1 or scope in ("deep", "comprehensive"):
            cross_refs = await _phase_cross_reference(
                file_parts, instruction, all_findings, thinking_level,
            )

        return await _phase_synthesis(
            file_parts, sources, instruction, doc_maps,
            all_findings, cross_refs, prep_issues, scope, thinking_level,
        )

    except Exception as exc:
        return make_tool_error(exc)


async def _phase_document_map(
    file_parts: list[types.Part],
    sources: list[DocumentSource],
    instruction: str,
    thinking_level: ThinkingLevel,
) -> list[DocumentMap]:
    """Phase 1: Extract structure overview from each document."""
    prompt = DOCUMENT_MAP.format(instruction=instruction)

    async def _map_one(part: types.Part, source: DocumentSource) -> DocumentMap:
        contents = types.Content(parts=[part, types.Part(text=prompt)])
        result = await GeminiClient.generate_structured(
            contents,
            schema=DocumentMap,
            system_instruction=DOCUMENT_RESEARCH_SYSTEM,
            thinking_level=thinking_level,
        )
        result.source_filename = source.filename
        return result

    tasks = [_map_one(p, s) for p, s in zip(file_parts, sources)]
    return await _gather_bounded(tasks, get_config().research_document_phase_concurrency)


async def _phase_evidence_extraction(
    file_parts: list[types.Part],
    sources: list[DocumentSource],
    instruction: str,
    doc_maps: list[DocumentMap],
    thinking_level: ThinkingLevel,
) -> list[DocumentFindingsContainer]:
    """Phase 2: Extract evidence-tiered findings from each document."""

    async def _extract_one(
        part: types.Part, source: DocumentSource, doc_map: DocumentMap,
    ) -> DocumentFindingsContainer:
        map_text = json.dumps(doc_map.model_dump(mode="json"), indent=2)
        prompt = DOCUMENT_EVIDENCE.format(instruction=instruction, document_map=map_text)
        contents = types.Content(parts=[part, types.Part(text=prompt)])
        result = await GeminiClient.generate_structured(
            contents,
            schema=DocumentFindingsContainer,
            system_instruction=DOCUMENT_RESEARCH_SYSTEM,
            thinking_level=thinking_level,
        )
        result.document = source.filename
        return result

    tasks = [
        _extract_one(p, s, m)
        for p, s, m in zip(file_parts, sources, doc_maps)
    ]
    return await _gather_bounded(tasks, get_config().research_document_phase_concurrency)


async def _phase_cross_reference(
    file_parts: list[types.Part],
    instruction: str,
    all_findings: list[DocumentFindingsContainer],
    thinking_level: ThinkingLevel,
) -> CrossReferenceMap:
    """Phase 3: Cross-reference findings across all documents."""
    findings_text = _format_findings(all_findings)
    prompt = CROSS_REFERENCE.format(instruction=instruction, all_findings_text=findings_text)
    parts = list(file_parts) + [types.Part(text=prompt)]
    contents = types.Content(parts=parts)
    return await GeminiClient.generate_structured(
        contents,
        schema=CrossReferenceMap,
        system_instruction=DOCUMENT_RESEARCH_SYSTEM,
        thinking_level=thinking_level,
    )


async def _phase_synthesis(
    file_parts: list[types.Part],
    sources: list[DocumentSource],
    instruction: str,
    doc_maps: list[DocumentMap],
    all_findings: list[DocumentFindingsContainer],
    cross_refs: CrossReferenceMap,
    preparation_issues: list[DocumentPreparationIssue],
    scope: str,
    thinking_level: ThinkingLevel,
) -> dict:
    """Phase 4: Produce grounded executive summary."""
    maps_text = json.dumps([m.model_dump(mode="json") for m in doc_maps], indent=2)
    findings_text = _format_findings(all_findings)
    cross_text = json.dumps(cross_refs.model_dump(mode="json"), indent=2)
    prompt = DOCUMENT_SYNTHESIS.format(
        instruction=instruction,
        document_maps=maps_text,
        all_findings_text=findings_text,
        cross_references_text=cross_text,
    )
    parts = list(file_parts) + [types.Part(text=prompt)]
    contents = types.Content(parts=parts)
    synthesis = await GeminiClient.generate_structured(
        contents,
        schema=DocumentResearchReport,
        system_instruction=DOCUMENT_RESEARCH_SYSTEM,
        thinking_level=thinking_level,
    )
    synthesis.instruction = instruction
    synthesis.scope = scope
    synthesis.document_sources = sources
    synthesis.preparation_issues = preparation_issues
    if not synthesis.findings:
        synthesis.findings = [f for fc in all_findings for f in fc.findings]
    synthesis.cross_references = cross_refs
    result = synthesis.model_dump(mode="json")

    await store_research_finding(result)

    return result


async def _quick_synthesis(
    file_parts: list[types.Part],
    sources: list[DocumentSource],
    instruction: str,
    doc_maps: list[DocumentMap],
    preparation_issues: list[DocumentPreparationIssue],
    thinking_level: ThinkingLevel,
) -> dict:
    """Quick scope: skip phases 2-4, produce lightweight report from maps only."""
    maps_text = json.dumps([m.model_dump(mode="json") for m in doc_maps], indent=2)
    prompt = DOCUMENT_SYNTHESIS.format(
        instruction=instruction,
        document_maps=maps_text,
        all_findings_text="(quick scope -- evidence extraction skipped)",
        cross_references_text="(quick scope -- cross-referencing skipped)",
    )
    parts = list(file_parts) + [types.Part(text=prompt)]
    contents = types.Content(parts=parts)
    report = await GeminiClient.generate_structured(
        contents,
        schema=DocumentResearchReport,
        system_instruction=DOCUMENT_RESEARCH_SYSTEM,
        thinking_level=thinking_level,
    )
    report.instruction = instruction
    report.scope = "quick"
    report.document_sources = sources
    report.preparation_issues = preparation_issues
    result = report.model_dump(mode="json")

    await store_research_finding(result)

    return result


def _format_findings(all_findings: list[DocumentFindingsContainer]) -> str:
    """Format all findings into a text block for cross-reference/synthesis prompts."""
    parts: list[str] = []
    for fc in all_findings:
        parts.append(f"\n--- {fc.document} ---")
        for f in fc.findings:
            parts.append(f"- [{f.evidence_tier}] {f.claim}")
            if f.citations:
                cites = ", ".join(
                    f"{c.document} {c.page} {c.section}".strip()
                    for c in f.citations
                )
                parts.append(f"  Citations: {cites}")
    return "\n".join(parts) or "(no findings extracted)"
