# video-research-mcp

Analyze recordings, compare documents, and research topics from your MCP client.
Gemini processes the supplied content; the server returns structured results,
timestamps, and source references where the selected tool provides them. Optional
Weaviate storage lets you search saved work across sessions.

[![CI](https://github.com/Galbaz1/video-research-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Galbaz1/video-research-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/video-research-mcp)](https://pypi.org/project/video-research-mcp/)
[![npm](https://img.shields.io/npm/v/video-research-mcp)](https://www.npmjs.com/package/video-research-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/LICENSE)

[Watch the demo](https://youtu.be/MQn7dMalTq4) ·
[Get started](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/tutorials/GETTING_STARTED.md) ·
[Browse the docs](https://github.com/Galbaz1/video-research-mcp/tree/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs)

Repository links point to the published source release. For the exact source
and bundled guides of an installed registry version, use its source archive on
[PyPI](https://pypi.org/project/video-research-mcp/#files).

## Choose how to use it

The repository contains a research server, a Claude Code workflow bundle, and two
optional video-production servers. Installing the workflow bundle connects the
research server; the companion servers need separate setup.

| Component | What you get | How to use it |
|---|---|---|
| Research server | 34 MCP tools for video, documents, web research, academic discovery, and saved knowledge | Any client that supports stdio MCP |
| Claude Code bundle | 17 slash commands, 13 skills, and 7 agents that organize work around those tools | npm installer or the repository's Claude plugin |
| Explainer companion | 15 tools that manage projects and run an external video pipeline | Install and configure [video-explainer-mcp](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/packages/video-explainer-mcp/README.md) |
| Scene-agent companion | 2 tools that generate scene code with Claude Agent SDK | Install and configure [video-agent-mcp](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/packages/video-agent-mcp/README.md) |

The research server's default model is `gemini-3.8-flash`. Claude workflows use
the active orchestration model. Installed registry packages, a source checkout,
and a running MCP process can be different versions; check the running process
before relying on a particular model or feature.

This implementation branch also provides bounded local acquisition, inspectable
source frames, durable window analysis, deterministic image/clip exports and
configurable model vision, image comparison, OCR inference and object crops.
See [native media](docs/integrations/NATIVE_MEDIA.md),
[window analysis](docs/integrations/VIDEO_WINDOWS.md) and
[image edits, OCR and export manifests](docs/integrations/IMAGE_EXPORTS.md) and
[configured vision](docs/integrations/IMAGE_VISION.md) for
their actual limits and optional runtime requirements. These source features have
separate acceptance evidence and have not been published as a new registry release.

## Install for Claude Code

You need **Node.js 22 or later**, **Python 3.11 or later**,
[uv](https://docs.astral.sh/uv/getting-started/installation/), and a
[Gemini API key](https://aistudio.google.com/apikey).

```bash
npx video-research-mcp@latest
```

The installer copies workflows into `~/.claude/`, registers MCP servers in
`~/.claude.json`, and creates a configuration template at
`~/.config/video-research-mcp/.env`. Open that file and set `GEMINI_API_KEY`.
Keep it private. Selected content is sent to the configured provider for analysis.

Restart Claude Code, inspect `/mcp`, and ask it to call `infra_configure()` without
arguments. This reads the running configuration without making a Gemini request.
Then use `/gr:doctor quick` to inspect the rest of the setup.

```bash
npx video-research-mcp@latest --check      # inspect installation
npx video-research-mcp@latest --local      # install in this project
npx video-research-mcp@latest --uninstall  # remove unchanged owned files and entries
```

Upgrades preserve custom settings and edited workflow files. The installer also
registers Playwright and MLflow MCP; it does not start an MLflow tracking server or
install the two video companions. See the [setup guide](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/tutorials/GETTING_STARTED.md)
for source installations, other clients, and troubleshooting.

## Start with the work you have

| Your material or question | Claude Code workflow | Direct MCP entry point |
|---|---|---|
| A video you want summarized | `/gr:video <YouTube URL or local file>` | `video_analyze` |
| A recording you want to keep questioning | `/gr:video-chat <source>` | `video_create_session`, then `video_continue_session` |
| A research question | `/gr:research <topic>` | `research_plan`, `research_deep`, `research_assess_evidence` |
| A longer background research job | `/gr:research-deep <topic>` | `research_web`, then `research_web_status` |
| PDFs, text, a URL, or a directory to compare | `/gr:analyze <content>` | `content_analyze` or `content_batch_analyze` |
| Documents that should ground a research answer | `/gr:research-doc <files>` | `research_document` |
| A web search | `/gr:search <query>` | `web_search` |
| Previously saved work | `/gr:recall [query]` | The knowledge tools, with Weaviate configured |

For example:

```text
/gr:video-chat ~/recordings/project-kickoff.mp4
Extract decisions and action items, with timestamps. Separate explicit decisions
from your interpretation, and identify anything the recording does not establish.
```

Commands can save notes, extract frames from local videos, and produce concept
maps or screenshots. These outputs depend on the workflow and its prerequisites;
`ffmpeg` is needed for local frame extraction. Direct MCP calls return tool data
and do not run the whole Claude workflow.

Model-generated summaries, citations, transcripts, and evidence labels need
checking against the original material when accuracy matters. A request for a
complete transcript or every shared screen does not prove that the output covers
all of them.

## Use the server without Claude Code

Configure a stdio MCP server in your client's supported format. The following is
a typical JSON registration; the shared environment file supplies credentials:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["--refresh", "video-research-mcp"]
    }
  }
}
```

The npm installer targets Claude Code. Other clients, including Codex, can use the
standard MCP server; their plugin, skill, and command installation formats differ.
See [other-client setup](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/tutorials/GETTING_STARTED.md).

## Add saved knowledge when you need it

Research works without Weaviate. To store and search analyses, configure a running
Weaviate instance and its embedding provider:

```dotenv
WEAVIATE_URL=https://your-cluster.weaviate.network
WEAVIATE_API_KEY=your-weaviate-key
```

Analysis tools attempt to store their results when the connection is configured.
Storage errors are non-fatal, so a successful analysis does not prove it was saved.
The knowledge tools support search, related items, retrieval, ingestion, schema
inspection, statistics, and optional QueryAgent answers. Graph extraction can make
an additional Gemini request even when Weaviate storage is disabled.

The [knowledge-store guide](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/tutorials/KNOWLEDGE_STORE.md) explains embeddings,
collections, optional dependencies, permissions, and how to verify a stored result.

## Configuration and costs

The server reads process environment variables first, then
`~/.config/video-research-mcp/.env`, then built-in defaults. A checkout `.env` is
not loaded automatically.

| Setting | Purpose |
|---|---|
| `GEMINI_API_KEY` | Required for Gemini analysis |
| `YOUTUBE_API_KEY` | YouTube Data API access for metadata, comments, and playlists; otherwise falls back to the Gemini key |
| `GEMINI_MODEL`, `GEMINI_FLASH_MODEL` | Override the primary and auxiliary models |
| `GEMINI_SESSION_DB` | Persist video sessions in SQLite; unset means in-memory sessions |
| `WEAVIATE_URL`, `WEAVIATE_API_KEY` | Connect optional saved-knowledge storage |
| `MLFLOW_TRACKING_URI` | Enable optional tracing when its dependency is installed |
| `INFRA_MUTATIONS_ENABLED` | Allow runtime model changes and cache clearing; disabled by default |

Provider usage, Deep Research jobs, optional embeddings, and media generation can
incur charges. The npm installer and MCP connection do not grant provider access
or establish the quality of generated results. See the
[configuration guide](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/tutorials/GETTING_STARTED.md) and
[security policy](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/SECURITY.md) before processing sensitive material.

## Explore or contribute

- [Documentation](https://github.com/Galbaz1/video-research-mcp/tree/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs): setup, reference, and maintainer guides.
- [Architecture](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/ARCHITECTURE.md): request flows and module responsibilities.
- [Tool contracts](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/metrics/tool-contract-manifest.json): exact names and schemas.
- [Contributing](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/CONTRIBUTING.md): development setup and verification.
- [Roadmap](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/ROADMAP.md) and [changelog](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/CHANGELOG.md): proposed work and release history.

The production skills cover image prompts, video generation, narration, and
assembly. They provide guidance; they do not install external providers. The
`plugin-maintenance` skill defines a bounded audit and repair workflow for this
repository.

## Author and credits

Created by **Fausto Albers**, Lead Gen AI Research & Development at the
[Industrial Digital Twins Lab](https://www.hva.nl), Amsterdam University of Applied
Sciences, in Jurjen Helmus's research group, and founder of
[Wonder Why](https://wonderwhy.ai).

Built with [Google Gemini](https://ai.google.dev/),
[FastMCP](https://github.com/PrefectHQ/fastmcp),
[Pydantic](https://docs.pydantic.dev/), and optional
[Weaviate](https://weaviate.io/), [MLflow](https://mlflow.org/), and
[Cohere](https://cohere.com/) integrations. Video companions use
[video_explainer](https://github.com/prajwal-y/video_explainer),
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python), and the
upstream pipeline's rendering and media providers.

Licensed under the [MIT License](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/LICENSE).
