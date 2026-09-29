---
description: Analyze any content — URL, file, or pasted text
argument-hint: <url|file-path|text>
allowed-tools: mcp__video-research__content_analyze, mcp__video-research__content_extract, mcp__video-research__content_batch_analyze, Write, Glob, Read, Bash
---

# Content Analysis: $ARGUMENTS

Analyze the provided content with progressive memory saving and automatic knowledge-graph visualization.

## Phase 1: Analyze

1. Determine the input type from "$ARGUMENTS":
   - If it starts with `http://` or `https://`: use `content_analyze` with `url` parameter
   - If it looks like a file path (contains `/` or `.`extension): use `content_analyze` with `file_path` parameter
   - If it's a directory path (ends with `/` or is a known directory): use `content_batch_analyze` with `directory` parameter and `mode="compare"`
   - Otherwise: use `content_analyze` with `text` parameter
2. Use instruction="Provide a comprehensive analysis including title, summary, key points, important entities (people, organizations, concepts, technologies), document structure, and quality assessment."

## Phase 2: Present & Save Initial Results

1. Present results clearly:
   - **Title and Source**
   - **Summary** (2-3 sentences)
   - **Key Points** (bulleted)
   - **Entities** (people, organizations, concepts)
   - **Quality Assessment**

2. **Immediately save initial results**:
   a. Determine the memory directory: find the `.claude/` project memory path for the current working directory. Use `Glob` on `~/.claude/projects/*/memory/` to find the active project memory path if needed.
   b. Generate a slug from the content title or source: lowercase, hyphens, no special chars, max 50 chars (e.g., "Attention Is All You Need" → `attention-is-all-you-need`, a URL like `arxiv.org/abs/2401.12345` → `arxiv-2401-12345`)
   c. Use `Write` to save at `<memory-dir>/gr/analysis/<slug>/analysis.md`:

```markdown
---
source: <url, file path, or "pasted text">
analyzed: <ISO 8601 timestamp>
updated: <ISO 8601 timestamp>
entities:
  people: <count>
  organizations: <count>
  concepts: <count>
  technologies: <count>
---

# <Title>

> Source: <url, file path, or "pasted text">
> Analyzed on <YYYY-MM-DD HH:MM>

## Summary  <!-- <YYYY-MM-DD HH:MM> -->

<2-3 sentence summary>

## Key Points  <!-- <YYYY-MM-DD HH:MM> -->

<Bulleted key points>

## Entities  <!-- <YYYY-MM-DD HH:MM> -->

### People
- <Person 1> — <role/context>

### Organizations
- <Org 1> — <context>

### Concepts
- <Concept 1> — <brief definition>

### Technologies
- <Tech 1> — <context>

## Quality Assessment  <!-- <YYYY-MM-DD HH:MM> -->

<Assessment of content quality, reliability, completeness>
```

   d. Tell the user: **Saved initial analysis to `gr/analysis/<slug>/`**

## Phase 3: Enrich with Knowledge Graph

1. Map the content analysis into a knowledge graph structure:
   - The content itself is the central anchor node
   - Each entity becomes a node (typed by category)
   - Key points become larger rectangular nodes
   - Relationships between entities are inferred from the content

2. Append a Knowledge Graph section to `analysis.md`:

```markdown
## Knowledge Graph  <!-- <YYYY-MM-DD HH:MM> -->

### Entities
- **<Entity 1>** (Person) — <description>
- **<Entity 2>** (Concept) — <description>

### Relationships
- <Entity 1> → *authored* → <Entity 3>
- <Entity 2> → *implements* → <Entity 4>
- <Key Point 1> → *mentions* → <Entity 1>
```

3. Update the `updated` timestamp in frontmatter.

## Phase 4: Background Visualization (optional)

Ask the user with `AskUserQuestion`:
- Question: "Generate interactive knowledge graph visualization? (runs in background)"
- Option 1: "Yes (Recommended)" — description: "HTML visualization + screenshot + workspace copy, runs asynchronously"
- Option 2: "Skip" — description: "Finish now with analysis only"

**If yes**: Spawn the `visualizer` agent in the background with this prompt:
```
analysis_path: <memory-dir>/gr/analysis/<slug>/analysis.md
template_name: content-knowledge-graph
slug: <slug>
content_type: analysis
```

**Do NOT wait** for the visualizer. Continue immediately to Deeper Exploration below. The user will be notified when visualization is done.

**If skip**: Confirm: **Analysis complete — saved to `gr/analysis/<slug>/`**
- `analysis.md` — timestamped analysis with entity graph

## Deeper Exploration

Offer to extract specific structured data with `content_extract` if the user needs a particular schema. Any deeper analysis appends timestamped sections to the existing `analysis.md` and may trigger a visualization update.
