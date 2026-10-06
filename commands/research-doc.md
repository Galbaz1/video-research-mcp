---
description: Deep document research with evidence tiers and cross-referencing
argument-hint: <file-path(s) or directory>
allowed-tools: mcp__video-research__research_document, mcp__video-research__content_batch_analyze, Write, Glob, Read, Bash
---

# Document Research: $ARGUMENTS

Run multi-phase document analysis with progressive memory saving. Retain document/page pointers and check decisive claims against the originals; generated citations and tiers are proposals.

## Phase 1: Identify Documents

1. Determine the input from "$ARGUMENTS":
   - If it's a single file path: use `research_document` with `file_paths=["<path>"]`
   - If it's multiple paths (comma or space separated): split and pass as `file_paths` list
   - If it's a directory: use `Glob` to find all PDFs/text files, then pass as `file_paths`
   - If it starts with `http://` or `https://`: pass as `urls` list
   - If arguments include both local files and URLs: pass both `file_paths` and `urls`

2. Determine scope from context:
   - Single document, quick question → `scope="quick"`
   - 1-2 documents, standard analysis → `scope="moderate"` (default)
   - 2+ documents, comparative analysis → `scope="deep"`
   - Comprehensive review with methodology critique → `scope="comprehensive"`

3. Call `research_document` with:
   - `instruction`: Use $ARGUMENTS context or default to "Analyze these documents comprehensively — extract key findings, assess methodology, identify agreements and contradictions."
   - `scope`: As determined above
   - `thinking_level`: "high"

## Phase 2: Present & Save Results

1. Present findings organized by evidence tier:
   - **CONFIRMED** — Checked against the cited original passage/data; distinguish what the document states from independently established truth
   - **STRONG INDICATOR** — Strongly implied by document evidence
   - **INFERENCE** — Reasonable conclusion from document context
   - **SPECULATION** — Extrapolation beyond what documents support
   - **UNKNOWN** — Documents do not address this

2. For multi-document results, highlight:
   - **Cross-references**: Where documents agree or contradict
   - **Evidence chains**: How findings flow across documents
   - **Methodology critique**: Per-document reliability assessment

3. **Save results to memory**:
   a. Find memory directory via `Glob` on `~/.claude/projects/*/memory/`
   b. Generate slug from instruction or first document name (lowercase, hyphens, max 50 chars)
   c. Use `Write` to save at `<memory-dir>/gr/doc-research/<slug>/analysis.md`:

```markdown
---
source: document research
instruction: "<instruction>"
analyzed: <ISO 8601 timestamp>
updated: <ISO 8601 timestamp>
scope: <scope>
documents:
  - <filename 1>
  - <filename 2>
findings_count: <number>
evidence_tiers:
  confirmed: <count>
  strong_indicator: <count>
  inference: <count>
  speculation: <count>
  unknown: <count>
---

# <Instruction or Research Question>

> Analyzed on <YYYY-MM-DD HH:MM>
> Scope: <scope>
> Documents: <comma-separated filenames>

## Executive Summary  <!-- <YYYY-MM-DD HH:MM> -->

<3-5 sentence grounded summary>

## Findings  <!-- <YYYY-MM-DD HH:MM> -->

### CONFIRMED
1. **<Claim>** — <citation: document, page, section>

### STRONG INDICATOR
2. **<Claim>** — <citation>

### INFERENCE
3. **<Claim>** — <citation>

## Cross-References  <!-- <YYYY-MM-DD HH:MM> -->

### Agreements
- <Claim> — supported by <Doc A, p.X> and <Doc B, p.Y>

### Contradictions
- <Claim> — <Doc A> says X (p.N), <Doc B> says Y (p.M)

## Methodology Critique  <!-- <YYYY-MM-DD HH:MM> -->

<Per-document methodology assessment>

## Open Questions  <!-- <YYYY-MM-DD HH:MM> -->

<What the documents leave unanswered>

## Recommendations  <!-- <YYYY-MM-DD HH:MM> -->

<Next steps based on evidence>
```

   d. Tell the user: **Saved document research to `gr/doc-research/<slug>/`**

## Phase 3: Deeper Analysis

Offer follow-up options:
- **Quick comparison**: Use `content_batch_analyze` with `mode="compare"` for a lighter cross-document view
- **Re-run deeper**: Call `research_document` again with `scope="deep"` or `"comprehensive"`
- **Assess a claim**: In a separately available workflow, use `research_assess_evidence` for a model proposal, then inspect primary material
- **Individual deep-dive**: Use an available content-analysis workflow for a targeted document question

Any follow-up appends timestamped sections to the existing `analysis.md`.
