# Plugin Distribution — Two-Package Architecture

The npm package installs Claude Code workflows and registers MCP servers. The
Python package runs the research server. Use this guide to understand what an
installation changes, how upgrades preserve local work, and which source files
control the distribution.

## Overview

The core ships under the same name on two registries:

| Package | Registry | Purpose | Used by |
| --- | --- | --- | --- |
| `video-research-mcp` | npm | Node.js installer and workflow Markdown | `npx video-research-mcp@latest` |
| `video-research-mcp` | PyPI | Python research MCP runtime | `uvx` when the MCP client starts the server |

Core versions must match across Python, npm, and the Claude plugin manifest.
Companion servers are separate Python packages with their own versions. A GitHub
release can contain all package archives; uploading those archives to PyPI and
npm is a separate step. See [Publishing](PUBLISHING.md).

## npm Package — The Installer

### What it does

The installer requires Node.js 22 or newer. The runtime requires Python 3.11 or
newer and [uv](https://docs.astral.sh/uv/). Missing `uv` or `python3` produces an
installer warning; it does not stop workflow files from being copied.

Choose the scope explicitly for a repeatable installation:

```sh
npx video-research-mcp@latest --global
# Or, from the project root:
npx video-research-mcp@latest --local
```

Without a scope flag, the installer prompts for global or local installation.

| Output | Global installation | Local installation |
| --- | --- | --- |
| Commands, skills, agents | `~/.claude/` | `./.claude/` |
| MCP registration | `~/.claude.json` | `./.mcp.json` |
| Ownership manifest | `~/.claude/gr-file-manifest.json` | `./.claude/gr-file-manifest.json` |
| Shared configuration template | `~/.config/video-research-mcp/.env` | Same user-level file |

The copy map contains 44 files: 17 commands, 20 skill files across 13 skills,
and 7 agents. They are prompts and workflow resources. The installer does not
install the upstream video renderer or start an MCP server.

Restart Claude Code after installation and use `/gr:getting-started` for setup.
`--check` reports installed manifests and modified tracked files; it does not
verify provider authentication or the active runtime version.

### Key files

| Source | Responsibility |
| --- | --- |
| [`bin/install.js`](../bin/install.js) | Scope selection, prerequisites, install, status, uninstall |
| [`bin/lib/copy.js`](../bin/lib/copy.js) | `FILE_MAP`, destination paths, empty-directory cleanup |
| [`bin/lib/manifest.js`](../bin/lib/manifest.js) | SHA-256 ownership evidence and upgrade decisions |
| [`bin/lib/config.js`](../bin/lib/config.js) | MCP registration merge and shared `.env` template |
| [`bin/lib/ui.js`](../bin/lib/ui.js) | Installer messages |
| [`package.json`](../package.json) | npm version, Node requirement, entry point, published assets |

### FILE_MAP — the central registry

`FILE_MAP` is the authoritative source-to-destination map. For example,
`commands/video.md` maps to `commands/gr/video.md`, which provides `/gr:video`.
Use the source map instead of maintaining another full copy in documentation.

To distribute a new workflow:

1. Create its command, skill, or agent file and referenced resources.
2. Add each shipped file to `FILE_MAP`. Destinations must remain under
   `commands/`, `skills/`, or `agents/`.
3. Add new directories to `CLEANUP_DIRS` when they need uninstall cleanup.
4. Check source mappings, isolated installer journeys, and package contents:

   ```sh
   uv run --locked python scripts/check_release.py
   node --test tests/installer.test.js
   npm pack --dry-run
   ```

The release check requires every mapped source to exist and every destination
to be unique. Installer tests use temporary installations and leave your active
`~/.claude/` tree alone.

### Manifest tracking

The manifest records the installed version, scope, timestamp, and SHA-256 hash
of each managed file. An ordinary upgrade replaces unchanged managed files and
skips differing files without matching ownership evidence. Obsolete files are
deleted only when they still match the recorded hash. Modified obsolete files
retain their ownership record.

`--force` permits overwriting differing workflow files and deleting modified
obsolete files during an upgrade. Inspect and back up customizations first.
Malformed manifests, unsafe paths, and symlinks in managed path components fail
validation before file actions; repair the state without discarding ownership
evidence.

To uninstall one scope:

```sh
npx video-research-mcp@latest --uninstall --global
# Or, from the affected project:
npx video-research-mcp@latest --uninstall --local
```

Uninstall removes tracked files whose hashes match, keeps modified files, and
removes empty managed directories. It retains a manifest for files kept. Without
a scope flag, it handles both the global and current project's local installation.
The shared `.env` file remains.

### MCP config merge

The installer registers these server command defaults:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["--refresh", "video-research-mcp[tracing]"]
    },
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@0.0.83", "--headless", "--caps=vision,pdf"]
    },
    "mlflow-mcp": {
      "command": "uvx",
      "args": ["--with", "mlflow[mcp]>=3.16.1,<4", "mlflow", "mcp", "run"]
    }
  }
}
```

An upgrade replaces the `command` and `args` of these three entries while
preserving custom environment and other fields. Unrelated servers remain.
Legacy companion entries matching the old single-argument `uvx` registration
are removed; manually configured local companion entries remain. The installer
does not register either companion. Follow
[onboarding](tutorials/GETTING_STARTED.md) to add them explicitly.

Uninstall removes a server entry only if its full configuration matches the
installer default. Customized entries remain for manual inspection. A malformed
client configuration produces a warning: files and their manifest may still
install, so check registration separately.

The shared `.env` template is created with owner-only permissions. Upgrades
append missing commented keys and preserve existing values. Nonempty process
environment values take precedence. Selected content and authentication
credentials are sent to their configured providers.

## PyPI Package — The Server

The runtime is defined in [`pyproject.toml`](../pyproject.toml). Its generated
registration uses `uvx --refresh video-research-mcp[tracing]` to resolve PyPI at
server launch. Source edits and npm workflow upgrades do not themselves change
that published package.

The core registers 34 tools across seven sub-servers. See
[Architecture](ARCHITECTURE.md) and the generated
[tool contract manifest](metrics/tool-contract-manifest.json) for the current
surface. Other clients can register the same stdio server in their own format.

## How Claude Code Discovers Plugin Assets

Installed files use the following user or project directories:

```text
~/.claude/ or ./.claude/
  commands/<namespace>/<name>.md
  skills/<name>/SKILL.md
  agents/<name>.md
```

### Commands → Slash Commands

Commands provide explicit workflows such as `/gr:video` and `/ve:explainer`.
Frontmatter describes the command, arguments, and allowed tools; the body uses
`$ARGUMENTS` for user input. Permissions do not install missing servers. Bundled
commands inherit the active session model.

### Skills → Context Injection

Skills provide reusable guidance. Their `name` and `description` support
discovery; `SKILL.md` links to extra resources when needed. Runtime tool schemas
remain authoritative for accepted arguments and capabilities.

### Agents → Sub-agents

Agent definitions supply a role, instructions, and tool restrictions for
delegated work. They inherit the configured orchestration model. Installing an
agent file does not grant access to an absent server.

## Current Plugin Inventory

### Commands (17)

| Command | Main use | Source |
| --- | --- | --- |
| `/gr:video` | Video analysis, batches, follow-up sessions | [video](../commands/video.md) |
| `/gr:video-chat` | Video Q&A | [video-chat](../commands/video-chat.md) |
| `/gr:research` | Research planning and analysis | [research](../commands/research.md) |
| `/gr:research-deep` | Background Deep Research | [research-deep](../commands/research-deep.md) |
| `/gr:analyze` | Content analysis and extraction | [analyze](../commands/analyze.md) |
| `/gr:search` | Web search | [search](../commands/search.md) |
| `/gr:recall` | Local research artifact discovery | [recall](../commands/recall.md) |
| `/gr:models` | Runtime model configuration | [models](../commands/models.md) |
| `/gr:doctor` | Setup and integration diagnostics | [doctor](../commands/doctor.md) |
| `/gr:traces` | MLflow trace inspection | [traces](../commands/traces.md) |
| `/gr:getting-started` | Installation setup | [getting-started](../commands/getting-started.md) |
| `/gr:research-doc` | Document-set research | [research-doc](../commands/research-doc.md) |
| `/gr:ingest` | Knowledge-store ingestion | [ingest](../commands/ingest.md) |
| `/gr:advisor` | Workflow selection | [advisor](../commands/advisor.md) |
| `/ve:explainer` | Explainer pipeline | [explainer](../commands/explainer.md) |
| `/ve:explain-video` | Analysis to explainer content | [explain-video](../commands/explain-video.md) |
| `/ve:explain-status` | Explainer project inspection | [explain-status](../commands/explain-status.md) |

### Skills (13)

| Skill | Purpose |
| --- | --- |
| `video-research` | Research tools, sessions, caching, evidence |
| `gemini-visualize` | HTML visualizations and three templates |
| `video-explainer` | Companion tools and pipeline workflows |
| `weaviate-setup` | Optional knowledge-store setup |
| `mlflow-traces` | Trace inspection and field guidance |
| `research-brief-builder` | Specific research briefs |
| `gr-advisor` | Research command selection |
| `tts-production` | Speech, alignment, audio QA |
| `ffmpeg-production` | Filters, encoding, export recipes |
| `video-generation` | Provider discovery and bounded clip generation |
| `video-production` | Continuity, shot QA, repair, assembly |
| `image-generation` | Reference prompts and inspected image edits |
| `plugin-maintenance` | Bounded audit and modernization workflow |

### Agents (7)

| Agent | Purpose |
| --- | --- |
| `researcher` | Research with evidence tiers |
| `video-analyst` | Video analysis and Q&A |
| `visualizer` | HTML visualization and screenshot |
| `comment-analyst` | YouTube comment analysis |
| `video-producer` | Explainer pipeline orchestration |
| `content-to-video` | Analyzed material to explainer content |
| `gr-advisor` | Workflow selection |

## Complete Flow

1. `npx` copies workflows, merges client registration, and records file ownership.
2. Claude Code loads those workflows and starts registered servers. `uvx` obtains
   the research runtime from PyPI.
3. A command supplies instructions to the agent, which calls available MCP tools.
4. Research tools call providers and attempt non-fatal Weaviate write-through
   when the knowledge store is enabled.
5. The client presents the result. Installation, a returned analysis, and
   verification of its evidence are separate checks.

## Client portability

The installer targets Claude Code. Other standard MCP clients can register the
stdio runtime. This repository does not ship native Codex plugin packaging.
Consult the current [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
and [OpenAI plugin packaging documentation](https://developers.openai.com/plugins/build/plugins)
before adding a platform-specific route.
