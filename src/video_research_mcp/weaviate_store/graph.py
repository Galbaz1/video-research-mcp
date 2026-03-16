"""Auto-extract knowledge graph (concepts + edges) from analysis results.

Called by tools after their primary store function. Fire-and-forget:
failures log a warning but never propagate to the caller.

Uses a low-cost Gemini call (thinking=low) on the already-available
result dict — no extra content fetching needed.
"""

from __future__ import annotations

import json
import logging

from ..client import GeminiClient
from ..prompts.content import GRAPH_EXTRACT_SYSTEM
from .concepts import store_concept_knowledge, store_relationship_edges

logger = logging.getLogger(__name__)

GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "state": {"type": "string", "enum": ["know", "fuzzy", "unknown"]},
                },
                "required": ["name", "description", "state"],
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_concept": {"type": "string"},
                    "to_concept": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "enables",
                            "example_of",
                            "builds_on",
                            "contradicts",
                            "related_to",
                        ],
                    },
                },
                "required": ["from_concept", "to_concept", "type"],
            },
        },
    },
    "required": ["concepts", "relationships"],
}


async def extract_and_store_graph(
    result: dict,
    source: str,
    source_tool: str = "content_analyze",
    source_category: str = "analysis",
) -> None:
    """Extract concepts and relationships from an analysis result, store in Weaviate.

    Adapts to different result shapes:
    - ContentResult: title, summary, key_points, entities
    - VideoResult: title, summary, key_points, topics
    - ResearchReport: topic, executive_summary, findings
    - DeepResearchResult: topic, report_text

    Args:
        result: Serialised analysis result dict.
        source: URL, file path, or identifier for provenance.
        source_tool: Tool name for source_tool field.
        source_category: One of video, video-chat, research, analysis.
    """
    try:
        # Adapt to different result shapes
        title = result.get("title", result.get("topic", ""))
        summary = result.get("summary", result.get("executive_summary", ""))
        key_points = result.get("key_points", [])
        entities = result.get("entities", result.get("topics", []))

        # For deep research reports, use the report text as summary
        if not summary and result.get("report_text"):
            summary = result["report_text"][:2000]

        # For research findings, extract from findings list
        if not key_points and result.get("findings"):
            findings = result["findings"]
            if isinstance(findings, list):
                key_points = [
                    f.get("claim", str(f)) if isinstance(f, dict) else str(f)
                    for f in findings[:10]
                ]

        if not summary and not key_points:
            return  # Nothing substantive to extract from

        prompt = (
            f"Title: {title}\n"
            f"Summary: {summary[:2000]}\n"
            f"Key points: {json.dumps(key_points[:15])}\n"
            f"Entities/topics: {json.dumps(entities[:20])}\n\n"
            "Extract the knowledge graph from this analysis."
        )
        raw = await GeminiClient.generate(
            prompt,
            thinking_level="low",
            system_instruction=GRAPH_EXTRACT_SYSTEM,
            response_schema=GRAPH_SCHEMA,
        )
        graph = json.loads(raw)

        for concept in graph.get("concepts", []):
            await store_concept_knowledge({
                "concept_name": concept["name"],
                "state": concept.get("state", "unknown"),
                "source_url": source,
                "source_title": title,
                "source_category": source_category,
                "source_tool": source_tool,
                "description": concept.get("description", ""),
            })

        edges = [
            {
                "from_concept": rel["from_concept"],
                "to_concept": rel["to_concept"],
                "relationship_type": rel["type"],
                "source_url": source,
                "source_category": source_category,
                "source_tool": source_tool,
            }
            for rel in graph.get("relationships", [])
        ]
        if edges:
            await store_relationship_edges(edges)

        n_concepts = len(graph.get("concepts", []))
        n_edges = len(edges)
        logger.info(
            "Graph extracted: %d concepts, %d edges from %s (%s)",
            n_concepts,
            n_edges,
            source,
            source_tool,
        )

    except Exception as exc:
        logger.warning("Graph extraction failed (non-fatal): %s", exc)
