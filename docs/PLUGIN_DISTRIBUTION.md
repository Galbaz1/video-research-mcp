# Plugin Distribution — Two-Package Architecture

The npm package installs Claude Code workflows and registers the core MCP
server. The same npm package root is also a native Codex plugin. The Python
package runs the research server. Use this guide to understand what an
installation changes, how upgrades preserve local work, and which source files
control the distribution.

## Overview

The core ships under the same name on two registries:

| Package | Registry | Purpose | Used by |
| --- | --- | --- | --- |
| `video-research-mcp` | npm | Claude installer, workflow Markdown and native Codex plugin root | `npx video-research-mcp@0.8.0-rc.3`; Codex npm marketplace source |
| `video-research-mcp` | PyPI | Python research MCP runtime | `uvx` when the MCP client starts the server |

Core versions must match across `pyproject.toml`, `package.json`,
`.claude-plugin/plugin.json` and the root Codex `plugin.json`. The root
`mcp.json` pins `video-research-mcp==<core version>`.
[`scripts/check_release.py`](../scripts/check_release.py) enforces both.
Companion servers are separate Python packages with their own versions. A GitHub
release can contain all package archives; uploading those archives to PyPI and
npm is a separate step. See [Publishing](PUBLISHING.md).

The examples select published prerelease `0.8.0-rc.3` (Python `0.8.0rc3`);
`@latest` selects the stable channel. Later source fixes require a checkout or
a new release.

## npm Package — The Installer

### What it does

The installer requires Node.js 22 or newer. The runtime requires Python 3.11 or
newer and [uv](https://docs.astral.sh/uv/). Workflow copying can succeed without
the runtime executables; use `--doctor` to inspect setup before starting a client.

Choose the scope explicitly for a repeatable installation:

```sh
npx video-research-mcp@0.8.0-rc.3 --global
# Or, from the project root:
npx video-research-mcp@0.8.0-rc.3 --local
```

Without a scope flag, the installer prompts for global or local installation.

| Output | Global installation | Local installation |
| --- | --- | --- |
| Commands, skills, agents | `~/.claude/` | `./.claude/` |
| MCP registration | `~/.claude.json` | `./.mcp.json` |
| Ownership manifest | `~/.claude/gr-file-manifest.json` | `./.claude/gr-file-manifest.json` |
| Private configuration template | `~/.config/video-research-mcp/.env` | `./.config/video-research-mcp/.env` |

Local MCP registration sets `VIDEO_RESEARCH_ENV_FILE` to the project template.
The candidate Python runtime reads that selected file without falling back to home
credentials when it is missing. This requires that candidate runtime or its
separately verified release; an older registry package may ignore the selection.
Nonempty process environment values still take precedence.
Local install, update, doctor and recovery use only the selected project template.
Legacy local checkpoints that contain a home `.env` snapshot cannot be restored
automatically; compare their before/after hashes and restore that home file separately.

The copy map defines commands, skills, agents and shared support files.
Contracts, descriptors, adjacent Python helpers and license texts live under
`skills/video-research-resources/`; this support directory is not another skill.
All files use the existing ownership, hash and checkpoint recovery rules. Installing them does not install optional
Python/native runtimes, activate external sources/providers or start an MCP server.

Restart Claude Code after installation and use `/gr:getting-started` for setup.
`--check` reports installed manifests and modified tracked files; it does not
verify provider authentication or the active runtime version.

### Key files

| Source | Responsibility |
| --- | --- |
| [`bin/install.js`](../bin/install.js) | Scope selection, prerequisites, install, status, uninstall |
| [`bin/lib/copy.js`](../bin/lib/copy.js) | `FILE_MAP`, destination paths, empty-directory cleanup |
| [`bin/lib/manifest.js`](../bin/lib/manifest.js) | SHA-256 ownership evidence and upgrade decisions |
| [`bin/lib/config.js`](../bin/lib/config.js) | MCP registration merge and scoped `.env` template |
| [`bin/lib/ui.js`](../bin/lib/ui.js) | Installer messages |
| [`package.json`](../package.json) | npm version, Node requirement, entry point, published assets |
| [`plugin.json`](../plugin.json) | Codex plugin identity and OpenAI presentation metadata |
| [`mcp.json`](../mcp.json) | Codex plugin's version-pinned stdio MCP server |

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
npx video-research-mcp@0.8.0-rc.3 --uninstall --global
# Or, from the affected project:
npx video-research-mcp@0.8.0-rc.3 --uninstall --local
```

Uninstall removes tracked files whose hashes match, keeps modified files, and
removes empty managed directories. It retains a manifest for files kept. Without
a scope flag, uninstall defaults to global; uninstall a project explicitly with
`--local`. Credential templates remain.

### MCP config merge

The installer registers only the core server, pinned to the npm package version:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["video-research-mcp==X.Y.Z"]
    }
  }
}
```

Local installation adds `env.VIDEO_RESEARCH_ENV_FILE` for the project template.
The entry is added when absent. An existing entry is replaced only when its hash
matches the receipt of the previous installation; customized or unmanaged
entries and unrelated servers remain. Optional Playwright and MLflow
declarations in [`config.js`](../bin/lib/config.js) and the companion servers are
not registered automatically. Follow [onboarding](tutorials/GETTING_STARTED.md)
to add them explicitly.

Uninstall removes a server entry only if it still matches the hash recorded at
installation. Customized entries remain for manual inspection. Malformed client
configuration is rejected before planned writes; repair it and check registration
separately.

The selected `.env` template is created with owner-only permissions. Upgrades
append missing commented keys and preserve existing values. Nonempty process
environment values take precedence. Selected content and authentication
credentials are sent to their configured providers.

## PyPI Package — The Server

The runtime is defined in [`pyproject.toml`](../pyproject.toml). Claude
registration and the Codex `mcp.json` both run `uvx video-research-mcp==X.Y.Z`,
which resolves that exact version at server launch. Source edits and npm
workflow upgrades do not themselves change that published package.

See [Architecture](ARCHITECTURE.md) and the generated
[tool contract manifest](metrics/tool-contract-manifest.json) for the source
surface. The running client's discovered schemas identify its actual version.
Other clients can register the same stdio server in their own format.

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

### Skills

| Work | Skills |
| --- | --- |
| Research and retrieval | `video-research`, `research-brief-builder`, `gr-advisor`, `weaviate-setup`, `mlflow-traces` |
| Visualization and spatial evidence | `gemini-visualize`, `research-visualization-blender`, `research-visualization-freecad`, `spatial-video-analysis` |
| Speech and images | `tts-production`, `image-generation`, `reverse-search-video-frame` |
| Video production and editing | `video-explainer`, `ffmpeg-production`, `video-generation`, `video-production`, `footage-edit`, `video-translation`, `movie-commentary` |
| Evidence and lessons | `hardware-evidence-capture`, `av-events`, `video-to-skill`, `educational-explainer` |
| Maintenance | `plugin-maintenance` |

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

The client loads workflows and starts the registered Python server through
`uvx`. Workflows guide MCP calls; provider results can be written to Weaviate
when configured. Check installation, the returned analysis and its source
material separately.

## Native Codex plugin

The npm package root is a portable Agent Plugins package as described in the
[OpenAI plugin packaging documentation](https://developers.openai.com/plugins/build/plugins):

| Path | Role in Codex |
| --- | --- |
| [`plugin.json`](../plugin.json) | Agent Plugins 1.0.0 manifest. `video-research` is the stable plugin identifier; `extensions.com.openai.interface` supplies presentation. |
| [`mcp.json`](../mcp.json) | One stdio server, `video-research`, launched as `uvx video-research-mcp==X.Y.Z`: the same name and command as the Claude registration. Keep `command` a bare executable name (or a contained `./` path); earlier Codex 0.160.0 checks ignored absolute stdio commands. |
| `skills/` | Discovered without a manifest field. Codex discovers the shipped skills directly. The Claude installer copies the same skills plus their managed support resources. |
| `commands/`, `agents/`, `bin/` | Claude assets; Codex does not load them. |

The package has no lifecycle hooks, `.app.json`, `.codex-plugin/` overlay or npm
lifecycle scripts. Codex downloads npm plugin sources without running lifecycle
scripts, so the plugin consists of static files only. `npx video-research-mcp`
copies Claude assets and `--client-config codex` prints a `config.toml` example;
neither installs the Codex plugin.

### Install a released version from npm

Create a marketplace root that selects the npm package, for example
`<root>/.agents/plugins/marketplace.json`:

```json
{
  "name": "video-research-npm",
  "interface": { "displayName": "Video Research" },
  "plugins": [
    {
      "name": "video-research",
      "source": { "source": "npm", "package": "video-research-mcp", "version": "X.Y.Z" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
```

```sh
codex plugin marketplace add <root>
codex plugin add video-research@video-research-npm
codex plugin list --json -m video-research-npm
```

Pin an exact release: its `mcp.json` pins the matching Python package, so the npm
version selects the whole runtime pair. Only releases that contain `plugin.json`
are native plugins; `0.7.1` is not. Codex needs the `npm` CLI (registry
authentication comes from its configuration) and `uvx` on the `PATH` it gives MCP
servers. Start a new Codex session after installing.

### Test an unreleased candidate

Install the exact packed bytes from a local marketplace:

```sh
CANDIDATE="$(mktemp -d)"
npm pack --ignore-scripts --pack-destination "$CANDIDATE"
mkdir -p "$CANDIDATE/marketplace/plugins/video-research" "$CANDIDATE/marketplace/.agents/plugins"
tar -xzf "$CANDIDATE/video-research-mcp-X.Y.Z.tgz" --strip-components 1 \
  -C "$CANDIDATE/marketplace/plugins/video-research"
```

Write `$CANDIDATE/marketplace/.agents/plugins/marketplace.json` like the npm
example, named `video-research-local`, with
`"source": { "source": "local", "path": "./plugins/video-research" }`. Then run
`codex plugin marketplace add "$CANDIDATE/marketplace"` and
`codex plugin add video-research@video-research-local`. Codex CLI 0.159.3 and 0.160.0 copy
local sources to `$CODEX_HOME/plugins/cache/video-research-local/video-research/<plugin.json version>/`;
compare that copy with the tarball. `codex plugin remove` deletes it again.
On 0.160.0, updating the local catalog to a new version and repeating `plugin add`
replaces the managed cache. Repeating `plugin add` at the same version also replaces
edited files and removes unowned cache files. Before an upgrade, reinstall or
removal, copy any local edits and unowned resources to a backup outside that cache;
Codex does not preserve them there. Keep credentials outside the package.
In an isolated install on that client, app-server `skills/list` loaded all shipped
skills from the cache, and a new thread started the `video-research` server with
plugin provenance, the installed copy as working directory and only `HOME`,
`PATH`, `USER`, `LOGNAME`, `TMPDIR`, `PLUGIN_ROOT` and `PLUGIN_DATA` (plus macOS
defaults) in its environment.

The exact version pin in `mcp.json` binds the runtime. A unique candidate version
cannot resolve to an older registry release, so launch fails instead of pairing
the candidate plugin with, for example, `0.7.1`. Make the candidate wheel available
to `uv` (a find-links directory with offline resolution, or a prepared uv cache)
and confirm which version the launched server runs. Codex filters the server
environment (in that install, `CODEX_HOME` set for Codex did not reach it), so do not
rely on `UV_*` variables set for Codex; bind the wheel through the launch context
instead. Do not add a test-only runtime override to `mcp.json`.

### Credentials and coexistence

The server reads `~/.config/video-research-mcp/.env` on start. Keep keys there:
Codex filters the environment it gives plugin servers. A `[mcp_servers.video-research]`
table in `~/.codex/config.toml`, for example from `--client-config codex`, declares
a second server with the same name. On Codex 0.160.0, that manual entry takes
precedence even when `enabled = false`, hiding the plugin server. When migrating
to the plugin, back up the configuration and remove only the identified manual
`mcp_servers.video-research` table (including its nested settings); preserve all
unrelated configuration and the shared credential file. Disabling that manual
table alone does not complete this migration. Plugin-scoped server policy, such as tool approval,
uses `plugins.<plugin>.mcp_servers.video-research` in Codex configuration.

The earlier isolated Codex 0.160.0 trial was verified with its packed candidate and built
wheel: all 22 skills came from the managed cache, all 90 MCP tools connected,
read-only configuration and local image-crop/error journeys passed, and a fresh
session repeated the runtime checks. The loaded Python modules and metadata
matched the selected wheel. These checks used offline resolution and a dummy key.
They do not establish registry installation, the running desktop app's `PATH`,
first-launch download timing or live-provider quality. The shared advisor selects
discovered MCP tools in Codex and registered `/gr:*` commands in Claude.

As of 2026-10-06, the selected RC3 npm-source installation and fresh-session
restart on Codex 0.160.1 covered 120 research tools, 24 skills and 124 cache files.
Fresh npm network acquisition versus same-version cache reuse remains unknown.
These checks do not qualify every provider or optional runtime. Earlier RC1 native
and RC2 source/archive checks remain results for their named candidates.

Consult the current [Claude Code skills documentation](https://code.claude.com/docs/en/skills)
before changing the Claude route.
