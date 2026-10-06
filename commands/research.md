---
description: Deep research on any topic with evidence-tier labeling
argument-hint: <topic>
allowed-tools: mcp__video-research__web_search, mcp__video-research__research_deep, mcp__video-research__research_plan, mcp__video-research__research_assess_evidence, Write, Glob, Read, Bash
---

# Research: $ARGUMENTS

> For hosted web-grounded research, use `/gr:research-deep`. Both workflows use provider quota/billing; check current pricing and the authorized budget.

Run a multi-phase deep research analysis with progressive memory saving and automatic evidence-network visualization.

## Phase 1: Research (run BOTH in parallel)

These calls are independent. Issue both in one turn within the authorized budget; configured model routes may coincide and share quota:

1. `web_search(query="$ARGUMENTS")` — uses the configured `flash_model` with Google Search grounding
2. `research_deep(topic="$ARGUMENTS", scope="moderate", thinking_level="high")` — uses the configured analysis model for three-phase model-only synthesis

Do NOT wait for one to finish before starting the other. The synthesis does not consume the parallel search response or retrieve sources. Keep its model proposals separate from inspected search evidence.

## Phase 2: Present & Save Initial Results

1. Present findings organized by evidence tier:
   - **CONFIRMED** — Inspected independent primary evidence supports the claim; model-written tiers alone do not qualify
   - **STRONG INDICATOR** — Credible evidence with minor gaps
   - **INFERENCE** — Reasonable conclusion from indirect evidence
   - **SPECULATION** — Plausible but unverified
   - **UNKNOWN** — Insufficient evidence
2. Highlight open questions and methodology critique

3. **Immediately save initial results**:
   a. Determine the memory directory: find the `.claude/` project memory path for the current working directory. Use `Glob` on `~/.claude/projects/*/memory/` to find the active project memory path if needed.
   b. Generate a slug from the topic: lowercase, hyphens, no special chars, max 50 chars (e.g., "impact of mcp on ai agents" → `impact-of-mcp-on-ai-agents`)
   c. Use `Write` to save at `<memory-dir>/gr/research/<slug>/analysis.md`:

```markdown
---
source: web research
topic: "$ARGUMENTS"
analyzed: <ISO 8601 timestamp>
updated: <ISO 8601 timestamp>
scope: moderate
findings_count: <number>
evidence_tiers:
  confirmed: <count>
  strong_indicator: <count>
  inference: <count>
  speculation: <count>
  unknown: <count>
---

# $ARGUMENTS

> Researched on <YYYY-MM-DD HH:MM>
> Scope: moderate

## Executive Summary  <!-- <YYYY-MM-DD HH:MM> -->

<2-3 sentence summary>

## Findings  <!-- <YYYY-MM-DD HH:MM> -->

### CONFIRMED
1. **<Finding>** — <evidence summary>

### STRONG INDICATOR
2. **<Finding>** — <evidence summary>

### INFERENCE
3. **<Finding>** — <evidence summary>

### SPECULATION
4. **<Finding>** — <evidence summary>

### UNKNOWN
5. **<Finding>** — <evidence summary>

## Sources  <!-- <YYYY-MM-DD HH:MM> -->

<Cited sources with URLs where available>

## Open Questions  <!-- <YYYY-MM-DD HH:MM> -->

<Unresolved questions for future investigation>

## Methodology Critique  <!-- <YYYY-MM-DD HH:MM> -->

<Assessment of research methodology limitations>
```

   d. Tell the user: **Saved initial research to `gr/research/<slug>/`**

## Phase 3: Enrich with Evidence Network

1. Map the research findings into a network structure:
   - Each finding becomes a node with its evidence tier
   - Open questions become nodes (distinct style)
   - Supporting/contradicting relationships between findings become edges
   - Shared sources create implicit "related to" edges between findings

2. Append an Evidence Network section to `analysis.md`:

```markdown
## Evidence Network  <!-- <YYYY-MM-DD HH:MM> -->

### Nodes
- **Finding 1** (CONFIRMED) — <claim summary>
- **Finding 2** (INFERENCE) — <claim summary>
- **Open Question 1** — <question>

### Relationships
- Finding 1 → *supports* → Finding 3
- Finding 2 → *contradicts* → Finding 4
- Open Question 1 → *challenges* → Finding 2
```

3. Update the `updated` timestamp in frontmatter.

## Phase 4: Background Visualization (optional)

Ask the user with `AskUserQuestion`:
- Question: "Generate interactive evidence network visualization? (runs in background)"
- Option 1: "Yes (Recommended)" — description: "HTML visualization + screenshot + workspace copy, runs asynchronously"
- Option 2: "Skip" — description: "Finish now with research only"

**If yes**: Spawn the `visualizer` agent in the background with this prompt:
```
analysis_path: <memory-dir>/gr/research/<slug>/analysis.md
template_name: research-evidence-net
slug: <slug>
content_type: research
```

**Do NOT wait** for the visualizer. Continue immediately to Deeper Analysis below. The user will be notified when visualization is done.

**If skip**: Confirm: **Research complete — saved to `gr/research/<slug>/`**
- `analysis.md` — timestamped findings with evidence tiers

## Deeper Analysis

If the user wants deeper analysis, offer:
- Re-run with scope="deep" or "comprehensive" — results append to existing analysis.md with new timestamps
- Verify specific claims with `research_assess_evidence` — append verification results
- Broader context with `web_search` for specific sub-topics

Any deeper analysis appends timestamped sections to the existing `analysis.md` and may trigger a visualization update.
