---
description: Launch Gemini Deep Research Agent with interview-driven brief
argument-hint: <topic>
allowed-tools: mcp__video-research__research_web, mcp__video-research__research_web_status, mcp__video-research__research_web_followup, mcp__video-research__research_web_cancel, mcp__video-research__web_search, mcp__video-research__knowledge_search, Write, Read, Glob, Bash, AskUserQuestion
---

# Deep Research: $ARGUMENTS

Launch the Gemini Deep Research Agent for autonomous web-grounded research (long-running; provider billing applies).

> For a shorter model-driven analysis, use `/gr:research`. Consult current provider pricing before a paid run.

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

This is a CHALLENGE-DRIVEN interview. The quality of the brief determines the quality of the research.

### Brief Protocol

Use supplied goals, sources, and existing authorization first. If the user requested autonomous work, compile a reversible brief with stated assumptions and proceed within the authorized spend/scope. Ask one consolidated question only for a materially missing decision or required budget authority; do not require an interview or approval again when the session already supplies it.

For interactive brief building, select relevant questions below rather than forcing every round.

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
- Authorized budget and maximum launches/follow-ups

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
Budget: <authorized limit> | Runtime: <provider-dependent>
==============
```

Launch once the brief and spend are authorized; reuse existing session authority.

## Phase 2: Launch & Parallel Work

1. Call `research_web(topic=<full compiled brief>, output_format=<format section>)`
2. Save brief to `<memory-dir>/gr/research/<slug>/brief.md`
3. Report the operation ID and pending state. Poll this ID at bounded intervals; retain it across interruptions and do not duplicate a launch after a timeout.
4. Do only independent work within the same budget while it runs. Stop on terminal failure/refusal, cancellation, or exhausted launch budget; preserve the response.

## Phase 3: Results & Cross-Model Critique

When research completes:

1. **Save raw report** to `<memory-dir>/gr/research/<slug>/report.md`
2. **Cross-model critique**: Critically analyze the Gemini research output:
   - What claims lack sufficient evidence?
   - What's missing that the brief requested?
   - Are there logical inconsistencies?
   - What follow-up questions would strengthen the weakest findings?
3. **Present to user** with both the report AND the critique
4. **Auto-follow-up**: For the top 2-3 weaknesses identified in critique, use one focused `research_web_followup` if already within the authorized budget; otherwise record them as open questions

## Phase 4: Persist & Iterate

1. Completed-report storage is attempted by the tool and is non-fatal; verify persistence separately
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
budget: "<authorized limit>"
---

# $ARGUMENTS

> Deep Research completed on <YYYY-MM-DD HH:MM>

## Report

<full report from Gemini>

## Critique

<cross-model analysis>

## Follow-ups

<follow-up Q&A if any>
```

4. Return the exact saved report, source coverage, critique, and unresolved questions. Check primary sources for decisive claims and verify that requested sections are non-empty. A provider completion status alone does not prove the brief was satisfied. Do not launch another cohort after a terminal result without new measured uncertainty and budget authority.
