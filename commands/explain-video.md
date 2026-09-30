---
description: Bridge workflow — analyze content with Gemini research tools, then synthesize an explainer video
argument-hint: "<url-or-topic> <project-id>"
allowed-tools: mcp__video-research__video_analyze, mcp__video-research__research_deep, mcp__video-research__content_analyze, mcp__video-research__web_search, mcp__video-explainer__explainer_create, mcp__video-explainer__explainer_inject, mcp__video-explainer__explainer_generate, mcp__video-explainer__explainer_status, mcp__video-explainer__explainer_render, mcp__video-explainer__explainer_render_start, mcp__video-explainer__explainer_render_poll, Read, Write, Glob
---

# Explain Video: $ARGUMENTS

Research a topic or analyze content, then synthesize it into an explainer video.

## Parse Arguments

`$ARGUMENTS` should contain:
1. A URL (YouTube, webpage) or topic to research
2. A project ID for the explainer video

If only one argument, use it as both the research subject and derive the project ID.

## Phase 1: Research & Analysis

Based on input type:

**YouTube URL**: Call `video_analyze(url, instruction="Extract key concepts, structure, and talking points for creating an educational explainer video")`

**Webpage URL**: Call `content_analyze(url=url, instruction="Extract main topics, key facts, and narrative structure")`

**Topic text**: Call `research_deep(topic="<topic text — include research context for an educational explainer video. Focus on: key concepts, common misconceptions, real-world examples, and logical narrative flow>", scope="moderate")`

## Phase 2: Content Preparation

1. Synthesize the research output into a structured markdown document:
   - Title and one-line summary
   - Key concepts (bulleted)
   - Narrative outline (numbered sections)
   - Facts and statistics with sources
   - Suggested visual metaphors

2. Create the explainer project: `explainer_create(project_id)`

3. Inject the content: `explainer_inject(project_id, content, "research.md")`

## Phase 3: Pipeline

Run the full pipeline: `explainer_generate(project_id)`

Check status with `explainer_status(project_id)` and report progress.

## Phase 4: Preview Render

Render a preview: `explainer_render(project_id, resolution="720p", fast=True)`

Report the output location to the user.

## Output

Summarize:
- Research findings (3-5 key points)
- Project location and status
- Render output path
- Suggestions for improvement (refine, sound, music)
