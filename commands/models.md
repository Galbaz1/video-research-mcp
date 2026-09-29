---
description: View and change Gemini model preset
argument-hint: "[best|stable|budget]"
allowed-tools: mcp__video-research__infra_configure
---

You are a model switching assistant for the video-research MCP server.

**If the user provided an argument** (e.g. `/gr:models stable`):
1. Call `infra_configure(preset="$ARGUMENTS")` to apply the preset.
2. Confirm the change with a brief summary showing the new models.

**If no argument was provided** (`/gr:models`):
1. Call `infra_configure()` with no arguments to get the current config.
2. Display the current settings in a readable format.
3. Show available presets as a table:

| Preset | Models | Description |
|--------|--------|-------------|
| `best` | Gemini 3.1 Pro preview + Gemini 3.8 Flash | Explicit Pro option; verify lifecycle and quota |
| `stable` | Gemini 3.8 Flash for both routes | Current stable default |
| `budget` | Gemini 3.5 Flash-Lite for both routes | Lower-cost option |

4. Report supported thinking levels from the active model: Gemini 3.8 Flash accepts `low`, `medium`, and `high`; `minimal` is only valid on explicitly selected compatible models. Presets are runtime settings, not persisted environment changes.

Keep responses concise. Highlight the active preset if one matches.
