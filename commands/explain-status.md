---
description: Check status of explainer video projects
argument-hint: "[project-id]"
allowed-tools: mcp__video-explainer__explainer_status, mcp__video-explainer__explainer_list
model: sonnet
---

# Explainer Status: $ARGUMENTS

## Behavior

If `$ARGUMENTS` is empty or missing:
- Call `explainer_list()` to show all projects
- Display a summary table with project ID, steps completed, and render status

If `$ARGUMENTS` is a project ID:
- Call `explainer_status(project_id="$ARGUMENTS")`
- Show detailed step-by-step completion status

## Output Format

### Project List (no arguments)

| Project | Progress | Rendered |
|---------|----------|----------|
| my-video | 3/5 steps | No |

### Single Project

**Project: `<id>`**
- [x] Script
- [x] Narration
- [x] Scenes
- [ ] Voiceover
- [ ] Storyboard
- Render: Not started

Next step: Run `explainer_step("<id>", "voiceover")` or `/ve:explainer <id>`
