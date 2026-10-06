---
description: View and change Gemini model preset
argument-hint: "[best|stable|budget]"
allowed-tools: mcp__video-research__infra_configure
---

You are a model switching assistant for the video-research MCP server.

**If the user provided an argument** (e.g. `/gr:models stable`):
1. Call `infra_configure(preset="$ARGUMENTS")` to apply the preset.
2. Check for an error before confirming the returned models. Mutations require operator-enabled `INFRA_MUTATIONS_ENABLED` and the configured `auth_token` when required. Do not enable policy or expose a token during model selection.

**If no argument was provided** (`/gr:models`):
1. Call `infra_configure()` with no arguments to get the current config.
2. Display the current settings in a readable format.
3. Show `available_presets` from the response. The source-defined presets are:

| Preset | Models | Description |
|--------|--------|-------------|
| `best` | Gemini 3.1 Pro preview + Gemini 3.8 Flash | Explicit Pro option; verify lifecycle and quota |
| `stable` | Gemini 3.8 Flash for both routes | Source default; provider availability is separate |
| `budget` | Gemini 3.5 Flash-Lite for both routes | Lower-cost option |

4. Report supported thinking levels from the active model: Gemini 3.8 Flash accepts `low`, `medium`, and `high`; `minimal` is only valid on explicitly selected compatible models. Presets are runtime settings, not persisted environment changes.

Keep responses concise. Highlight the active preset if one matches.
