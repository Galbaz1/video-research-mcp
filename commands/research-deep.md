---
description: Launch Gemini Deep Research Agent with interview-driven brief
argument-hint: <topic>
allowed-tools: mcp__video-research__research_web, mcp__video-research__research_web_status, mcp__video-research__research_web_followup, mcp__video-research__web_search, mcp__video-research__knowledge_search, Write, Read, Glob, Bash, AskUserQuestion
model: opus
---

# Deep Research: $ARGUMENTS

Last updated: 2026-03-05 14:57 CET

Launch the Gemini Deep Research Agent for autonomous web-grounded research ($2-5/task, 10-20 min).

> For free, instant offline research, use `/gr:research` instead.

## Phase 0: Load Context

Before interviewing, gather intelligence:

1. **Prior research**: Call `knowledge_search(query="$ARGUMENTS", limit=5)` to find existing findings in Weaviate
2. **Check memory**: Read files under `<memory-dir>/gr/research/` for previous analyses on related topics

Present to the user:
- "I found X prior analyses related to this topic: [summaries]"
- "Here's what we already know: [key findings]"
- "Let me interview you to build a precise research brief."

If no prior context found, proceed directly to the interview.

## Phase 1: Research Brief Interview

This is a CHALLENGE-DRIVEN interview. The quality of the brief determines the quality of $2-5 worth of research.

### Interview Protocol (3-5 rounds via AskUserQuestion)

**Round 1 -- Question Sharpening**
Restate topic as a precise question. Challenge HARD:
- "This is too broad -- which specific aspect matters for your decision?"
- "What would the ACTIONABLE output look like? A decision memo? Competitive landscape?"
- "What's the actual decision this research needs to inform?"

**Round 2 -- Scope Boundaries**
- Time period (recent vs historical vs both)
- Domains (academic, industry, regulatory, all)
- Geographic scope if relevant
- What to EXCLUDE (common knowledge, things user already knows)
- Budget confirmation ($2-5 per run)

**Round 3 -- Hypotheses & Surprises**
- "What's your current hypothesis? I'll make sure the research tests it"
- "What finding would CHANGE your mind?"
- "What finding would be useless to you?"

**Round 4 (if needed) -- Format & Audience**
- Who reads this? (affects tone, depth, structure)
- Required sections? (executive summary, data tables, risk assessment)
- Compare-and-contrast structure vs narrative vs bullet points?

### Compile Brief

After interview, present the compiled brief for approval:

```
RESEARCH BRIEF
==============
Question: <precise, falsifiable research question>
Scope: <time, domains, geography, depth>
Hypotheses to test: <H1, H2, ...>
Known context: <what we already know -- don't rediscover>
Prior findings: <relevant Weaviate findings to build on>
Output format: <structure, audience, tone, required sections>
Exclusions: <what to skip>
Estimated cost: $2-5 | Time: 10-20 min
==============
```

Ask user: "Launch with this brief?"

## Phase 2: Launch & Parallel Work

1. Call `research_web(topic=<full compiled brief>, output_format=<format section>)`
2. Save brief to `<memory-dir>/gr/research/<slug>/brief.md`
3. Tell user: "Research launched (ID: xxx). Estimated 10-20 min."
4. **While waiting**, offer lightweight parallel work:
   - "While Gemini researches, I can: (a) draft an outline based on your brief, (b) search for specific sub-topics with web_search, (c) review prior findings in more detail, (d) work on something else"
5. Autonomous poll: call `research_web_status(interaction_id)` every ~60s

## Phase 3: Results & Cross-Model Critique

When research completes:

1. **Save raw report** to `<memory-dir>/gr/research/<slug>/report.md`
2. **Cross-model critique**: Critically analyze the Gemini research output:
   - What claims lack sufficient evidence?
   - What's missing that the brief requested?
   - Are there logical inconsistencies?
   - What follow-up questions would strengthen the weakest findings?
3. **Present to user** with both the report AND the critique
4. **Auto-follow-up**: For the top 2-3 weaknesses identified in critique, offer to call `research_web_followup` to get targeted answers

## Phase 4: Persist & Iterate

1. Weaviate storage is automatic (tool does it on completion)
2. Save enriched analysis to memory: `<slug>/analysis.md` with:
   - Full report
   - Critique annotations
   - Follow-up results appended
3. Update frontmatter with source count, duration, tags

```markdown
---
source: deep research agent
topic: "$ARGUMENTS"
analyzed: <ISO 8601>
interaction_id: <id>
source_count: <N>
duration_minutes: <N>
cost_estimate: "$2-5"
---

# $ARGUMENTS

> Deep Research completed on <YYYY-MM-DD HH:MM>

## Report

<full report from Gemini>

## Critique (Claude Opus)

<cross-model analysis>

## Follow-ups

<follow-up Q&A if any>
```

4. Offer deeper investigation:
   - Follow-up questions via `research_web_followup`
   - Cross-reference with offline analysis via `research_deep`
   - Interactive evidence network visualization
