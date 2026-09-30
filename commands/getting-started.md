---
description: First-time setup guide — verify config, discover commands, and run your first tool
allowed-tools: Bash, Read, Glob, mcp__video-research__infra_configure, mcp__video-research__web_search
---

# Getting Started

Welcome the user to the video-research plugin and walk them through first-time setup.

## Step 1: Verify Configuration

Check the active client registration and use a local presence-only check for `GEMINI_API_KEY`; never print or read the full secret file into context. The shared configuration is `~/.config/video-research-mcp/.env`. If the key is absent, direct the user to https://aistudio.google.com/apikey and that file; restart the MCP client after editing.

Call `infra_configure()` without arguments. If it responds, report the active provider model and distinguish MCP connection from successful inference. If unavailable, inspect `/mcp` or use `/gr:doctor quick` before repeating setup.

## Step 2: First Authorized Analysis

Use the source/topic the user supplied. For an explicit onboarding smoke, request a short analysis with non-empty required fields and source attribution. Web search and analysis use provider quota/billing; do not promise they are free. If no source or inference authorization is supplied, complete the configuration check and show one concrete first-call example.

Completion requires the actual returned fields and sources, or a clearly recorded inference failure. Do not claim a config response proves video understanding, document coverage, or optional integrations.

## Step 3: Show What's Available

Present this reference. Use a compact format — no verbose descriptions.

### Commands (type these in Claude Code)

**Research & Analysis (`/gr:`)**
| Command | What it does |
|---------|-------------|
| `/gr:research "topic"` | Deep research with evidence tiers |
| `/gr:research-doc` | Research grounded in your documents (PDFs, URLs) |
| `/gr:search "query"` | Quick web search via Gemini |
| `/gr:analyze` | Analyze any content — URL, file, or text |
| `/gr:video <url>` | Analyze a YouTube video or local file |
| `/gr:video-chat` | Multi-turn Q&A about a video |
| `/gr:recall "topic"` | Search past analyses and research |
| `/gr:ingest` | Add knowledge to the store manually |
| `/gr:models` | View or change the Gemini model preset |
| `/gr:doctor quick` | Health check — verify all connections |

**Video Explainer (`/ve:`)**
| Command | What it does |
|---------|-------------|
| `/ve:explainer` | Full explainer video workflow |
| `/ve:explain-video` | Analyze content, then create explainer |
| `/ve:explain-status` | Check video project status |

### Optional Features

- **Knowledge Store** — persistent semantic search across all past results. Run the `weaviate-setup` skill to configure.
- **MLflow Tracing** — track and debug every Gemini call. Use `/gr:traces` after enabling.
- **Visualizations** — concept maps and evidence networks can be generated when useful; browser acceptance is checked separately.

## Step 4: Suggest First Actions

Based on the user's project context, suggest 2-3 concrete things they could try. Look at the current directory name and any README for clues about what the project is about. Examples:

- "Try `/gr:research "your project topic"` for a deep dive"
- "Have a PDF to analyze? Try `/gr:research-doc`"
- "Want to analyze a YouTube tutorial? Try `/gr:video <url>`"

End with: "Run `/gr:doctor quick` anytime to check your setup."
