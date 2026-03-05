---
description: Search and browse past research, video notes, and analyses
argument-hint: "[topic|category|fuzzy|unknown|ask \"question\"]"
allowed-tools: mcp__video-research__knowledge_search, mcp__video-research__knowledge_stats, mcp__video-research__knowledge_related, mcp__video-research__knowledge_fetch, mcp__video-research__knowledge_ask, Glob, Grep, Read
note: knowledge_query is deprecated — use knowledge_search for all retrieval needs. knowledge_ask remains the preferred tool for AI-powered Q&A.
model: sonnet
---

# Recall: $ARGUMENTS

Browse saved results from previous `/gr:*` commands and search the knowledge store.

## Find the Memory Directory

Use `Glob` on `~/.claude/projects/*/memory/gr/` to find saved results. There may be results across multiple project directories — check all of them.

## Check Knowledge Store

Call `knowledge_stats()` first. If it returns collection counts, Weaviate is available — use semantic search for keyword queries. If it returns an error, use filesystem-only mode.

`knowledge_stats()` returns immediately when Weaviate is not configured (no network call). No performance impact for non-Weaviate users.

## Behavior

### If no arguments given (`$ARGUMENTS` is empty):

1. Call `knowledge_stats()` (reuse availability check result)
2. Use `Glob` with pattern `~/.claude/projects/*/memory/gr/**/analysis.md` to find all saved results
3. For each result, read the first 5 lines to get the title and check for visualization artifacts:
   - Check if `concept-map.html`, `evidence-net.html`, or `knowledge-graph.html` exists alongside `analysis.md`
   - Check if `screenshot.png` exists
4. Present unified overview:

   **Knowledge Store** (if available)
   X objects across 12 collections
   ResearchFindings: N | VideoAnalyses: N | ContentAnalyses: N | ...

   **Project Memory** (filesystem)
   Group by category with visualization indicators:

   **Research** (`gr/research/`)
   - `topic-slug` — <first heading> 📊 (has evidence network)

   **Video Notes** (`gr/video/`)
   - `video-slug` — <first heading> 📊 (has concept map)

   **Video Chats** (`gr/video-chat/`)
   - `chat-slug` — <first heading> 📊 (has concept map)

   **Analyses** (`gr/analysis/`)
   - `source-slug` — <first heading> 📊 (has knowledge graph)

   Legend: 📊 = interactive visualization available

5. Invite user to search, browse by category, filter by knowledge state, or ask a question

### If arguments match a category (`research`, `video`, `video-chat`, `analysis`):

Category-to-collection mapping:
- research → ResearchFindings, ResearchPlans
- video → VideoAnalyses, VideoMetadata
- video-chat → SessionTranscripts
- analysis → ContentAnalyses

**With Weaviate:** call `knowledge_stats(collection=<primary>)` for counts alongside filesystem listing.

1. Use `Glob` with pattern `~/.claude/projects/*/memory/gr/$ARGUMENTS/*/analysis.md`
2. List all results in that category with their titles and viz indicators
3. Read the first heading and YAML frontmatter of each file

If category + keyword (e.g., `/gr:recall research kubernetes`):
- Weaviate: `knowledge_search(query="kubernetes", collections=["ResearchFindings"], limit=5)`
- Filesystem: `Grep` in `gr/research/` directories

**Without Weaviate:** `Glob` on `gr/$CATEGORY/` only (unchanged).

### If arguments are "fuzzy" or "unknown":

**Knowledge state filtering** — shows concepts matching the requested state across ALL analyses. Always filesystem-only (YAML frontmatter lives on disk, not in Weaviate).

1. Use `Glob` to find all `gr/**/analysis.md` memory files
2. Read the YAML frontmatter of each file looking for `concepts:` with matching `state:`
3. Collect all matching concepts and present grouped by source:

   **Concepts you're fuzzy on:**

   From `gr/video/boris-cherny/`:
   - **Latent Demand** (timestamp: 12:15) — "the idea that making something easier increases total demand"
   - **Jevons Paradox** (timestamp: 30:26) — "economic principle where efficiency gains increase consumption"

   From `gr/research/ai-code-generation/`:
   - **Benchmark Saturation** — "when models plateau on existing benchmarks"

4. For each concept, show:
   - Name and brief description
   - Source analysis (with link to the full analysis)
   - Timestamp (for video sources)
   - Suggest: "Want to dive deeper into any of these? I can re-analyze the source."

5. If no concepts match the requested state, report that and suggest the user review their analyses to update knowledge states.

### If arguments start with "ask":

Extract the question (everything after "ask ").

1. Call `knowledge_ask(query="<question>")`
2. On success: present the AI-generated answer with source citations. Per source: collection + object_id.
   Offer: `knowledge_fetch` for full source content.
3. On error "weaviate-agents not installed":
   "AI Q&A requires weaviate-agents: `uv pip install 'video-research-mcp[agents]'`"
4. If Weaviate is not configured:
   "AI Q&A requires Weaviate. Run `/gr:doctor` to check setup."

### If arguments are a keyword:

**Collection scoping** — when the query contains known category keywords, pass the `collections` filter:
- Query contains "video" → `collections=["VideoAnalyses", "VideoMetadata"]`
- Query contains "research" → `collections=["ResearchFindings", "ResearchPlans"]`
- Query contains "content" or "analysis" → `collections=["ContentAnalyses"]`
- Query contains "session" or "chat" → `collections=["SessionTranscripts"]`
- Otherwise → search all collections (no filter)

**With Weaviate:**
1. Call `knowledge_search(query="$ARGUMENTS", search_type="hybrid", limit=5)` (with optional `collections` filter per scoping rules above)
2. In parallel, use `Glob` + `Grep` for filesystem matches (same as current behavior)
3. Present in two sections:

   **Semantic Results (Knowledge Store)**
   Per hit: collection, score, summary (if present from Flash processing, else first non-empty of title/topic/claim)
   If `rerank_score` is present, show alongside base score: `score: 0.85 (rerank: 0.92)`
   If `properties.local_filepath` exists and points to an existing file:
   - Show: `Video lokaal beschikbaar: <path>`
   - Offer: `Chat ermee: /gr:video-chat <path>`
   If `properties.screenshot_dir` exists and directory is present:
   - Show: `Screenshots beschikbaar in <path>`
   Offer: "Fetch full result?" → `knowledge_fetch`
   Offer: "Find related?" → `knowledge_related`

   **Filesystem Results (Project Memory)**
   Existing behavior: matching context with 2 lines around the match, viz indicators

4. If Weaviate has results but filesystem does not:
   "These findings were captured from direct tool calls, not via /gr: commands."

**Without Weaviate:**
1. Use `Glob` to find all `gr/**/analysis.md` memory files
2. Use `Grep` to search file contents for "$ARGUMENTS"
3. If matches found:
   - List them with the matching context (2 lines around the match)
   - Show viz indicators for each result
4. If a single match, read and present the full content directly

### Reading a result:

When the user picks a filesystem result (by name or number):

1. Use `Read` to show the full `analysis.md` content. Present it cleanly — it's already well-structured markdown.
2. Check for companion artifacts and report:
   - **Visualization**: If an HTML file exists, tell the user the path and offer: "Open the interactive visualization? I can serve it in a browser."
   - **Screenshot**: If `screenshot.png` exists, note it: "Screenshot available at `<path>/screenshot.png`"
3. If the result has YAML frontmatter with `concepts:`, show a brief knowledge state summary:
   - X concepts known, Y fuzzy, Z unknown
   - "Use `/gr:recall fuzzy` to see all fuzzy concepts across analyses"

## Fetching Knowledge Store Results

When the user picks a Weaviate result (by number or object_id):

1. Call `knowledge_fetch(object_id="<uuid>", collection="<collection>")`
2. Present all properties in a readable format.
3. If `local_filepath` is present:
   - Check existence and report either:
     - "Video is lokaal beschikbaar. Wil je ermee chatten?"
     - "Video was eerder gedownload maar bestand is niet meer aanwezig."
4. If `screenshot_dir` is present:
   - Show available frame files and timestamps (if manifest is present).
5. Offer: "Find related?" → `knowledge_related(object_id=..., collection=...)`

## Opening Visualizations

If the user asks to open/view a visualization:

1. Note: This recall command doesn't have Playwright tools. Suggest the user open the HTML file directly:
   - "Open `<path>/concept-map.html` in your browser"
   - Or suggest re-running the original analysis command which has Playwright access

## Management

If the user asks to delete a result, confirm first, then note the directory path so they can remove it manually: `rm -rf <path>`. Commands cannot delete memory files.

If the user wants to update a knowledge state manually, they can edit the YAML frontmatter in `analysis.md`, or use the interactive visualization to cycle states and paste the generated prompt.
