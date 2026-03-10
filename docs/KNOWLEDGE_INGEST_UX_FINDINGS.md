# Knowledge Ingest UX: Findings & Recommendations

Last updated: 2026-03-05 20:12 CET

> Date: 2026-03-05
> Context: Real-world usage session — GPT-5.4 video analysis with cross-platform sentiment research via 4 parallel researcher agents. Manual `knowledge_ingest` calls after automated pipeline.

## Problem

When manually calling `knowledge_ingest`, Claude (and human users of the MCP tools) must **guess property names** for each collection. The tool description says "Properties are validated against the collection schema" but never reveals what that schema is. This leads to a trial-and-error loop:

```
1. Call knowledge_ingest with intuitive property names
2. Get "Unknown properties" error
3. Search an existing object in the collection to reverse-engineer the schema
4. Retry with correct names
```

In this session, it took **3 round-trips** to discover that:
- `ResearchFindings` uses `claim` (not `finding`), `supporting` (not `sources`)
- `ConceptKnowledge` uses `concept_name` (not `name`), has no `category` or `related_concepts`
- `CommunityReactions` has no `platform`, `reaction_summary`, or `source_url` — uses `consensus`, `themes_positive`, `themes_critical`, `notable_opinions_json`
- `VideoMetadata` has no `channel`, `local_filepath`, `source_url`, `screenshot_dir` — uses `channel_title`

## Root Cause

The schema is defined in `weaviate_schema/*.py` as `CollectionDef` objects. The `ALLOWED_PROPERTIES` dict in `tools/knowledge/helpers.py` validates against these at runtime. But this information is **never exposed to the LLM or user**.

The tool's `properties` parameter is typed as `dict` with no further hints — the LLM has to infer property names from context, which fails when names are non-obvious (`claim` vs `finding`).

## Impact

- **Token waste**: Each failed ingest + retry costs ~500-1000 tokens per attempt
- **Session friction**: 3 extra round-trips in a workflow that should be seamless
- **Agent failures**: Background agents calling `knowledge_ingest` can't self-correct without this discovery loop
- **Adoption barrier**: New users will hit this on first manual ingest and may give up

## Recommendations

### 1. Add `knowledge_schema` tool (recommended, low effort)

New read-only tool that returns the schema for one or all collections:

```python
@knowledge_server.tool()
async def knowledge_schema(
    collection: KnowledgeCollection | None = None,
) -> dict:
    """Show the Weaviate schema for a collection.

    Returns property names, types, and descriptions for one or all
    collections. Use this before knowledge_ingest to see what
    properties are expected.
    """
    targets = [c for c in SCHEMA_COLLECTIONS if collection is None or c.name == collection]
    return {
        "collections": [
            {
                "name": c.name,
                "description": c.description,
                "properties": [
                    {"name": p.name, "type": p.data_type, "description": p.description}
                    for p in c.properties
                ],
            }
            for c in targets
        ]
    }
```

**Effort**: ~30 lines. No schema changes. No migration.

### 2. Enrich `knowledge_ingest` error message (quick win)

When validation fails, include the allowed properties in the error:

```python
# Current (unhelpful):
f"Unknown properties for {collection}: {sorted(unknown)}"

# Proposed (self-documenting):
f"Unknown properties for {collection}: {sorted(unknown)}. "
f"Allowed: {sorted(allowed)}"
```

**Effort**: 1 line change in `tools/knowledge/ingest.py:54`.

### 3. Add property hints to tool description (no code change)

Extend the `knowledge_ingest` docstring with a compact schema reference:

```python
"""Manually insert data into a knowledge collection.

Properties are validated against the collection schema — unknown keys
are rejected.

Key properties per collection:
- ResearchFindings: claim, evidence_tier, confidence, supporting[], topic, reasoning
- VideoAnalyses: video_id, title, summary, key_points[], topics[], sentiment, source_url
- CommunityReactions: video_id, video_title, sentiment_positive, themes_positive[], consensus
- ConceptKnowledge: concept_name, description, state, source_tool
- RelationshipEdges: from_concept, to_concept, relationship_type
"""
```

**Effort**: Docstring update only. But fragile — must be updated when schema changes.

### Priority

| # | Fix | Effort | Impact | Recommendation |
|---|-----|--------|--------|----------------|
| 2 | Better error message | 1 line | Medium | Do now |
| 1 | `knowledge_schema` tool | 30 lines | High | Do next release |
| 3 | Docstring hints | 10 lines | Medium | Optional (fragile) |

## Session Evidence

### Successful ingests (after discovery)
- `VideoAnalyses`: 1 object (video analysis with key_points as text[])
- `CommunityReactions`: 1 object (cross-platform sentiment with themes)
- `ResearchFindings`: 3 objects (developer sentiment, Claude vs GPT-5.4, #QuitGPT)
- `ConceptKnowledge`: 3 objects (GPT-5.4, Extreme Reasoning, #QuitGPT movement)

### Failed attempts before discovery
- `VideoMetadata`: rejected `channel`, `local_filepath`, `source_url`, `screenshot_dir`
- `VideoAnalyses`: rejected `key_points` as string (must be text[])
- `CommunityReactions`: rejected `platform`, `reaction_summary`, `sentiment_score`, `source_url`
- `ResearchFindings`: rejected `finding`, `sources` (3 objects failed)
- `ConceptKnowledge`: rejected `category`, `name`, `related_concepts` (3 objects failed)

Total: **8 failed calls** before successful ingestion pattern was established.
