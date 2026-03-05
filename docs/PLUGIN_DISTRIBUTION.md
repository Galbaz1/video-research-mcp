# Plugin Distribution — Two-Package Architecture

> How the Claude Code plugin is built, distributed, and discovered.

## Overview

`video-research-mcp` ships as **two packages with the same name** on different registries:

| Package | Registry | Purpose | Runs when |
|---------|----------|---------|-----------|
| `video-research-mcp` | **PyPI** | MCP server (Python runtime) | Claude Code starts a session — `uvx` downloads and runs it |
| `video-research-mcp` | **npm** | Plugin installer (Node.js script) | User runs `npx video-research-mcp@latest` once to install |

The npm package contains zero Python code. The PyPI package contains zero JavaScript. They share a name for brand consistency.

## npm Package — The Installer

### What it does

`bin/install.js` copies 31 markdown files into `~/.claude/` (global) or `.claude/` (local), then writes MCP server config to `.mcp.json`. That's it — no runtime, no daemon.

```
npx video-research-mcp@latest
        │
        ├── Copies 16 commands   → ~/.claude/commands/gr/ and commands/ve/
        ├── Copies 9 skill files → ~/.claude/skills/
        ├── Copies 6 agents    → ~/.claude/agents/
        ├── Writes .mcp.json   → MCP server registration (3 servers)
        └── Writes manifest    → for upgrades/uninstall
```

### Key files

| File | Role |
|------|------|
| `bin/install.js` | CLI entry point — parses flags, orchestrates install/uninstall |
| `bin/lib/copy.js` | `FILE_MAP` (source→dest mapping), `CLEANUP_DIRS`, copy/remove helpers |
| `bin/lib/manifest.js` | SHA-256 hashing, upgrade diffing, user-modification detection |
| `bin/lib/config.js` | `.mcp.json` merge — registers `video-research` + `playwright` + `mlflow-mcp` servers |
| `bin/lib/ui.js` | Terminal output formatting |
| `package.json` | npm metadata — `"bin"` points to `install.js`, `"files"` limits what gets published |

### FILE_MAP — the central registry

Every file distributed by the plugin must be listed in `bin/lib/copy.js`:

```js
const FILE_MAP = {
  // Commands → /gr:* slash commands (13)
  'commands/video.md':        'commands/gr/video.md',
  'commands/video-chat.md':   'commands/gr/video-chat.md',
  'commands/research.md':     'commands/gr/research.md',
  'commands/research-deep.md': 'commands/gr/research-deep.md',
  'commands/analyze.md':      'commands/gr/analyze.md',
  'commands/search.md':       'commands/gr/search.md',
  'commands/recall.md':       'commands/gr/recall.md',
  'commands/models.md':       'commands/gr/models.md',
  'commands/doctor.md':       'commands/gr/doctor.md',
  'commands/traces.md':       'commands/gr/traces.md',
  'commands/getting-started.md': 'commands/gr/getting-started.md',
  'commands/research-doc.md': 'commands/gr/research-doc.md',
  'commands/ingest.md':       'commands/gr/ingest.md',

  // Commands → /ve:* slash commands (3)
  'commands/explainer.md':      'commands/ve/explainer.md',
  'commands/explain-video.md':  'commands/ve/explain-video.md',
  'commands/explain-status.md': 'commands/ve/explain-status.md',

  // Skills → context injection (9 files across 6 skills)
  'skills/video-research/SKILL.md':                              'skills/video-research/SKILL.md',
  'skills/gemini-visualize/SKILL.md':                             'skills/gemini-visualize/SKILL.md',
  'skills/gemini-visualize/templates/video-concept-map.md':       'skills/gemini-visualize/templates/video-concept-map.md',
  'skills/gemini-visualize/templates/research-evidence-net.md':   'skills/gemini-visualize/templates/research-evidence-net.md',
  'skills/gemini-visualize/templates/content-knowledge-graph.md': 'skills/gemini-visualize/templates/content-knowledge-graph.md',
  'skills/video-explainer/SKILL.md':                             'skills/video-explainer/SKILL.md',
  'skills/weaviate-setup/SKILL.md':                               'skills/weaviate-setup/SKILL.md',
  'skills/mlflow-traces/SKILL.md':                                'skills/mlflow-traces/SKILL.md',
  'skills/research-brief-builder/SKILL.md':                       'skills/research-brief-builder/SKILL.md',

  // Agents → sub-agents (6)
  'agents/researcher.md':       'agents/researcher.md',
  'agents/video-analyst.md':    'agents/video-analyst.md',
  'agents/visualizer.md':       'agents/visualizer.md',
  'agents/comment-analyst.md':  'agents/comment-analyst.md',
  'agents/video-producer.md':   'agents/video-producer.md',
  'agents/content-to-video.md': 'agents/content-to-video.md',
};
```

**To add a new command/skill/agent:** create the markdown file, add its entry to `FILE_MAP`, add its parent directory to `CLEANUP_DIRS` if new, then run `node bin/install.js --global`.

### Manifest tracking

The installer writes `~/.claude/gr-file-manifest.json` containing SHA-256 hashes of every installed file. This enables:

- **Upgrade detection**: only overwrite files that haven't been user-modified
- **User modification protection**: if the user edited a skill, `--force` is required to overwrite
- **Clean uninstall**: only remove files whose hash matches the manifest
- **Obsolete file cleanup**: when a file is removed from FILE_MAP, it's deleted on upgrade

### MCP config merge

`bin/lib/config.js` writes three MCP server entries to `.mcp.json`:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["video-research-mcp[tracing]"]
    },
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@0.0.68", "--headless", "--caps=vision,pdf"]
    },
    "mlflow-mcp": {
      "command": "uvx",
      "args": ["--with", "mlflow[mcp]>=3.5.1", "mlflow", "mcp", "run"],
      "env": { "MLFLOW_TRACKING_URI": "${MLFLOW_TRACKING_URI}" }
    }
  }
}
```

Config location: `~/.claude/.mcp.json` (global) or `./.mcp.json` (local, project root).

---

## PyPI Package — The Server

The Python package (defined in `pyproject.toml`) is the actual MCP server. Users never install it manually — `uvx` handles it when Claude Code reads `.mcp.json`.

The server exposes 28 tools across 7 sub-servers. See the Architecture section in the root `CLAUDE.md`.

---

## How Claude Code Discovers Plugin Assets

Claude Code scans two directory trees at session start:

```
~/.claude/                        ← global (all projects)
  commands/<namespace>/<name>.md  ← slash commands
  skills/<name>/SKILL.md          ← skills
  agents/<name>.md                ← sub-agents

.claude/                          ← local (current project only)
  commands/...
  skills/...
  agents/...
```

### Commands → Slash Commands

A file at `commands/gr/video.md` becomes the slash command `/gr:video`.

Structure:
```markdown
---
description: "Short description shown in autocomplete"
argument-hint: "<url or path>"
allowed-tools: [video_analyze, video_metadata, Write, Read]
model: sonnet
---

Your prompt template here. Use $ARGUMENTS for user input.
```

| Frontmatter | Purpose |
|-------------|---------|
| `description` | Shown in command picker / autocomplete |
| `argument-hint` | Placeholder text after the command name |
| `allowed-tools` | Restricts which MCP tools + built-in tools the command can use |
| `model` | Which Claude model runs the command (sonnet, haiku, opus) |

When a user types `/gr:video https://youtube.com/...`:
1. Claude Code loads `commands/gr/video.md`
2. Replaces `$ARGUMENTS` with the user's input
3. Restricts tool usage to `allowed-tools`
4. Executes with the specified `model`

### Skills → Context Injection

A `skills/<name>/SKILL.md` provides domain knowledge that Claude loads when relevant. This is the **anti-hallucination mechanism** — it overrides the model's training knowledge with correct, project-specific API syntax.

```markdown
---
name: video-research
description: "Teaches Claude how to use the 28 video-research-mcp tools"
---

## Tool Signatures
- `video_analyze(url, instruction, thinking_level)` ...

## Workflow Patterns
1. Start with research_plan for complex topics ...

## Anti-patterns
- Never set alpha=1.0 for exact keyword matches ...
```

Claude Code loads the skill when its `description` matches the user's intent. The full SKILL.md content is injected into the system prompt before Claude responds.

Skills can have sub-files (like `skills/gemini-visualize/templates/*.md`) that are referenced from the main SKILL.md.

### Agents → Sub-agents

An `agents/<name>.md` defines a specialized agent that can be launched via the `Task` tool:

```markdown
---
name: researcher
color: blue
model: sonnet
tools: [research_plan, web_search, research_deep, Write, Read]
---

You are a multi-phase research specialist...
```

These run as background or foreground processes with their own tool restrictions and system prompts.

---

## Current Plugin Inventory

### Commands (16)

| File | Slash Command | Tools | Model |
|------|---------------|-------|-------|
| `commands/video.md` | `/gr:video` | video_analyze, video_batch, video_session, video_metadata, video_playlist | sonnet |
| `commands/video-chat.md` | `/gr:video-chat` | video_create_session, video_continue_session | sonnet |
| `commands/research.md` | `/gr:research` | web_search, research_deep, research_plan, research_assess_evidence | sonnet |
| `commands/research-deep.md` | `/gr:research-deep` | research_web, research_web_status, research_web_followup, research_web_cancel, web_search, knowledge_search | opus |
| `commands/analyze.md` | `/gr:analyze` | content_analyze, content_extract | sonnet |
| `commands/search.md` | `/gr:search` | web_search | sonnet |
| `commands/recall.md` | `/gr:recall` | Glob, Grep, Read (filesystem only) | sonnet |
| `commands/models.md` | `/gr:models` | infra_configure | haiku |
| `commands/getting-started.md` | `/gr:getting-started` | doctor + baseline setup checks | sonnet |
| `commands/traces.md` | `/gr:traces` | mlflow-mcp search_traces, get_trace, set_trace_tag, log_feedback, evaluate_traces | sonnet |
| `commands/doctor.md` | `/gr:doctor` (`quick` compact, `full` detailed) | infra_configure, video_metadata, knowledge_stats, mlflow-mcp search_traces, Read/Glob/Bash | haiku |
| `commands/research-doc.md` | `/gr:research-doc` | research_document, content_batch_analyze, Write/Glob/Read/Bash | sonnet |
| `commands/ingest.md` | `/gr:ingest` | knowledge_ingest, knowledge_stats, knowledge_search, Read | sonnet |
| `commands/explainer.md` | `/ve:explainer` | All 15 explainer tools, Read/Write/Glob | sonnet |
| `commands/explain-video.md` | `/ve:explain-video` | video_analyze, research_deep, content_analyze, web_search + explainer tools | sonnet |
| `commands/explain-status.md` | `/ve:explain-status` | explainer_status, explainer_list | haiku |

### Skills (6)

| Skill | Purpose |
|-------|---------|
| `video-research` | Tool signatures, workflows, caching for 28 tools |
| `gemini-visualize` | HTML visualization generation + 3 templates |
| `video-explainer` | Tool signatures and workflows for 15 explainer tools |
| `weaviate-setup` | Interactive onboarding wizard for Weaviate connection |
| `mlflow-traces` | MLflow trace debugging, field paths, `extract_fields` discipline |
| `research-brief-builder` | Interview framework for high-signal deep-research briefs |

### Agents (6)

| Agent | Model | Purpose |
|-------|-------|---------|
| `researcher` | sonnet | Multi-phase research with evidence tiers |
| `video-analyst` | sonnet | Video analysis and Q&A sessions |
| `visualizer` | sonnet | Background HTML visualization + screenshot |
| `comment-analyst` | haiku | Background YouTube comment analysis |
| `video-producer` | sonnet | Full pipeline orchestrator for explainer videos |
| `content-to-video` | sonnet | Bridge agent — research analysis to explainer video |

---

## Complete Flow

```
USER: npx video-research-mcp@latest
         │
         ▼
    bin/install.js (Node.js)
         │
         ├── Copy 31 markdown files to ~/.claude/
         ├── Write .mcp.json (register MCP servers)
         └── Write manifest (for future upgrades)

USER: starts Claude Code
         │
         ├── Read .mcp.json
         │    └── Start: uvx video-research-mcp  ← Python server from PyPI
         │
         ├── Scan ~/.claude/commands/
         │    └── Register /gr:video, /gr:research, etc.
         │
         ├── Scan ~/.claude/skills/
         │    └── Index skill descriptions for context matching
         │
         └── Scan ~/.claude/agents/
              └── Register researcher, video-analyst, etc.

USER: /gr:research "quantum computing"
         │
         ├── Load commands/gr/research.md (prompt template)
         ├── Load skills/video-research/SKILL.md (context)
         ├── Call research_plan → research_deep via MCP server
         ├── Server calls Gemini API
         ├── Server stores result in Weaviate (write-through)
         └── Claude returns structured response
```
