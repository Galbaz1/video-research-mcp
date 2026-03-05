---
description: Manually add knowledge to the Weaviate store
argument-hint: "[collection] [text or file path]"
allowed-tools: mcp__video-research__knowledge_ingest, mcp__video-research__knowledge_schema, mcp__video-research__knowledge_stats, mcp__video-research__knowledge_search, Read
model: sonnet
---

# Ingest: $ARGUMENTS

Manually add entries to the Weaviate knowledge store.

## Phase 0: Determine Intent

If `$ARGUMENTS` is empty, ask the user:

```
AskUserQuestion:
  question: "What do you want to add to the knowledge store?"
  header: "Ingest"
  options:
    - label: "Add a finding or insight"
      description: "Store a research finding, insight, or fact with evidence tier"
    - label: "Add content analysis"
      description: "Store an analysis of a document, URL, or text"
    - label: "Add a concept"
      description: "Store a concept with its definition and relationships"
    - label: "Describe what to add"
      description: "Free-form description — I'll pick the right collection"
```

## Phase 1: Pick Collection

Map the user's intent to the right collection. Call `knowledge_stats()` first to verify Weaviate is available.

| Intent | Collection |
|--------|-----------|
| Finding/insight | `ResearchFindings` |
| Content analysis | `ContentAnalyses` |
| Video note | `VideoAnalyses` |
| Concept | `ConceptKnowledge` |
| Relationship | `RelationshipEdges` |
| Meeting/call note | `CallNotes` |

If `$ARGUMENTS` includes a collection name, use it directly.

**Always call `knowledge_schema(collection="<name>")` to get the exact property names and types.** Do not guess property names — the schema is the source of truth.

## Phase 2: Gather Properties

If the user provided text or a file path in `$ARGUMENTS`:
1. Read the content
2. Extract the relevant properties automatically
3. Show the user what will be ingested and ask for confirmation

If no content provided, ask the user for the required properties interactively.

## Phase 3: Ingest

Call `knowledge_ingest(collection="<name>", properties={...})`.

On success: report the object UUID and offer:
- "Search for it: `/gr:recall <topic>`"
- "Add another entry"
- "Add related concepts or relationships"

On error:
- **Schema validation error**: The error message lists allowed `name:type` pairs. Call `knowledge_schema(collection="<name>")` for full details, then retry with correct properties.
- **Weaviate not configured**: "Set up Weaviate first: `/skill weaviate-setup`"

## Bulk Ingestion

If the user provides a file with multiple entries (JSON, YAML, CSV, or markdown with clear structure):

1. Read and parse the file
2. Show a preview: "Found N entries for <collection>. Ingest all?"
3. On confirmation, call `knowledge_ingest` for each entry sequentially
4. Report: "Ingested N/M entries. X failed (show errors)."

## Smart Extraction

If the user pastes raw text or provides a URL/file without specifying a collection:

1. Read the content
2. Determine the best collection based on content type:
   - Academic/research → `ResearchFindings`
   - Video/media → `VideoAnalyses`
   - General document → `ContentAnalyses`
   - Definitions/terms → `ConceptKnowledge`
3. Extract properties using the content
4. Show preview and ask for confirmation before ingesting
