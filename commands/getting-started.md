---
description: First-time setup guide — verify config, discover commands, and run your first tool
allowed-tools: Bash, Read, Glob, mcp__video-research__infra_configure, mcp__video-research__web_search
model: haiku
---

# Getting Started

Welcome the user to the video-research plugin and walk them through first-time setup.

## Step 1: Verify Configuration

Read `~/.config/video-research-mcp/.env` and check:
- Is `GEMINI_API_KEY` set (uncommented, non-empty)?
- If not: tell them to get a free key at https://aistudio.google.com/apikey, paste it in that file, and restart Claude Code. Stop here.

If the key exists, call `infra_configure()` with no arguments to confirm the server is responding.
- If it responds: report the active model and move to Step 2.
- If it fails: tell them to restart Claude Code and try again.

## Step 2: Quick Smoke Test

Run a simple web search to prove everything works:
```
web_search(query="latest AI research news", num_results=3)
```

If it succeeds, briefly confirm with: "Your setup is working. Here's what you can do."
If it fails, report the error and suggest `/gr:doctor quick` for diagnostics.

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
- **Visualizations** — concept maps and evidence networks auto-generate after analysis.

## Step 4: Suggest First Actions

Based on the user's project context, suggest 2-3 concrete things they could try. Look at the current directory name and any README for clues about what the project is about. Examples:

- "Try `/gr:research "your project topic"` for a deep dive"
- "Have a PDF to analyze? Try `/gr:research-doc`"
- "Want to analyze a YouTube tutorial? Try `/gr:video <url>`"

End with: "Run `/gr:doctor quick` anytime to check your setup."
