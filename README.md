# video-research-mcp

Ask questions across recordings and documents, then inspect the source frames,
transcripts and clips behind the answer. The server exposes **90 MCP tools** for
video, audio and image operations, document analysis, web and academic research,
and saved knowledge. Agent workflows connect those tools into a research or
production task.

Use it in **Codex**, **Claude Code**, or any client that supports stdio
[Model Context Protocol](https://modelcontextprotocol.io/).
Gemini handles the main analysis and research routes; local tools inspect and
transform source files. Optional providers and runtimes extend that core.

[Release](https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.8.0-rc.1) ·
[npm](https://www.npmjs.com/package/video-research-mcp/v/0.8.0-rc.1) ·
[PyPI](https://pypi.org/project/video-research-mcp/0.8.0rc1/) ·
[Source](https://github.com/Galbaz1/video-research-mcp/tree/v0.8.0-rc.1)

**This guide targets the published release candidate `0.8.0-rc.1`.** Stable
`latest` is `0.7.1`, which predates the native Codex plugin and the expanded media
surface. Examples pin the candidate; reference links use its source tag.

## From source material to a useful result

| Work | Tools to start with | What to inspect |
| --- | --- | --- |
| Question a recording | `video_analyze`, `video_create_session`, `video_continue_session` | Source timestamps, the answer and supporting material |
| Analyze a long recording in stages | `media_info`, `video_analyze_windows`, `job_status` | Requested intervals, dry-run plan, execution limits and retained outcomes |
| Prepare audio or transcripts | `audio_transcribe`, `audio_clip_export`, `audio_dsp_analyze` | Caption or model provenance, source timing and exported audio |
| Inspect images or export media | `image_read`, `image_crop`, `image_ocr`, `video_frame`, `video_clip_export` | Source bytes, selected region or interval, output files and manifests |
| Compare documents or investigate a topic | `content_analyze`, `research_document`, `research_plan`, `research_web` | Citations, contradictions, missing evidence and job status |
| Search previous work | `knowledge_ingest`, `knowledge_search`, `knowledge_ask` | Stored records and retrieval provenance; requires Weaviate |

For example, ask your client:

```text
Compare ~/recordings/design-review.mp4 with ~/docs/requirements.pdf.
Identify decisions that change a requirement. Cite recording timestamps and
relevant document pages, distinguish explicit decisions from interpretation,
and flag anything the sources do not establish.
```

Workflows combine tools; individual MCP calls return their own results. Source
hashes identify bytes, and export manifests retain how an artifact was produced.
Model timestamps, citations and interpretations still need checking against the
original material. Sampling a recording does not establish complete coverage.

## Install

You need **Python 3.11+**, [uv](https://docs.astral.sh/uv/getting-started/installation/)
with `uvx` on your client's `PATH`, and a [Gemini API key](https://aistudio.google.com/apikey)
for Gemini requests. Plugin installation also needs **Node.js 22+** and npm.
Install **FFmpeg/FFprobe** for local media inspection, frame extraction and clip
exports. Other operations may need an optional dependency or configured backend.

By default, the server reads process environment variables first, then
`~/.config/video-research-mcp/.env`, then defaults. Project installations can select
a separate credential file. Add your key to the shared file for the routes below,
keeping any existing settings:

```dotenv
GEMINI_API_KEY=your-gemini-api-key
```

Keep the file private (`chmod 600 ~/.config/video-research-mcp/.env`). Codex plugin
servers receive a filtered environment, so this file is the reliable credential
route there. Provider analysis sends source material to the configured service
and can incur usage charges. A selected analysis interval does not necessarily
limit the uploaded file.

### Codex: native plugin

The plugin supplies **23 skills** and the version-pinned research server. The
native npm installation was checked on Codex **0.160.0**. You do not run the
Claude installer for this route.

For a new installation, save this catalog as
`~/.local/share/video-research-mcp/.agents/plugins/marketplace.json`, creating its
parent directories if needed:

```json
{
  "name": "video-research",
  "interface": { "displayName": "Video Research" },
  "plugins": [
    {
      "name": "video-research",
      "source": {
        "source": "npm",
        "package": "video-research-mcp",
        "version": "0.8.0-rc.1"
      },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
```

```bash
codex plugin marketplace add ~/.local/share/video-research-mcp
codex plugin add video-research@video-research
codex plugin list --json
```

Start a fresh Codex session. Check that `video-research@video-research` is enabled,
its source is npm at `0.8.0-rc.1`, and the server's tools are available.

For an existing installation, use the
[native plugin and migration guide](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/docs/PLUGIN_DISTRIBUTION.md#native-codex-plugin).
Back up local plugin edits before reinstalling: Codex replaces its managed cache.
A manual `mcp_servers.video-research` entry can hide the plugin server, including
when disabled on 0.160.0; the guide describes the specific configuration to remove.

### Claude Code: workflow installer

```bash
npx video-research-mcp@0.8.0-rc.1 --global
```

This installs slash commands, skills and agents into `~/.claude/`, registers the
research server in `~/.claude.json`, and creates a credential template if needed.
Set the key, restart Claude Code and inspect `/mcp`. Use `/gr:advisor` to select a
workflow, or `/gr:video`, `/gr:research` and `/gr:analyze` to start directly.

Use `--local` for project scope and set the key in
`./.config/video-research-mcp/.env`; this replaces the shared credential-file route.
Use `--global --check` to inspect the global installation. Updates preserve modified
workflow files and custom configuration. See
[installer options and recovery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/docs/integrations/ONBOARDING.md)
for scope, checkpoints and rollback.

### Other MCP clients: server only

Use your client's stdio registration format. A typical JSON entry is:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["video-research-mcp==0.8.0-rc.1"]
    }
  }
}
```

This connects the same tools; agent workflows are installed separately. Python
package filenames use the normalized spelling `0.8.0rc1`.

### Verify your first connection

Ask the client to call `infra_configure` with **no arguments**. It returns the
running configuration without making an analysis request. Then try a tool on
material you can inspect yourself. A successful connection verifies setup;
checking the returned evidence verifies the particular result.

## Configure only what the task needs

| Setting or addition | Use it for |
| --- | --- |
| `GEMINI_MODEL`, `GEMINI_FLASH_MODEL` | Select supported primary and auxiliary models |
| `YOUTUBE_API_KEY` | YouTube metadata, comments and playlists; otherwise uses the Gemini key |
| `GEMINI_SESSION_DB` | Persist video sessions in SQLite; unset means in-memory sessions |
| `WEAVIATE_URL`, `WEAVIATE_API_KEY` | Store and retrieve research across sessions |
| `MLFLOW_TRACKING_URI` and the `tracing` extra | Trace tool execution |
| `LOCAL_FILE_ACCESS_ROOT` | Restrict supported local-file operations to a directory |

Research works without Weaviate. When storage is configured, write-through errors
are non-fatal; verify the stored record when persistence matters. The
[knowledge-store guide](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/docs/tutorials/KNOWLEDGE_STORE.md)
covers embeddings, collections and optional query dependencies. For a manually
configured server, retain the version pin when adding extras, for example
`uvx 'video-research-mcp[tracing,agents]==0.8.0-rc.1'`. The full runtime configuration lives in
[`ServerConfig`](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/src/video_research_mcp/config.py).

Image edits, OCR, speech inference, Blender, FreeCAD and local model services have
additional runtime or backend requirements. Installing the plugin does not install
those runtimes, model weights or provider accounts. Inspect the relevant skill and
its prerequisites before using an optional integration.

For video production, the separate
[explainer companion](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/packages/video-explainer-mcp/README.md)
orchestrates an external rendering pipeline; the
[scene-agent companion](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/packages/video-agent-mcp/README.md)
handles scene-code generation. Neither is required for research. Production skills
also provide workflows for narration, image generation, clip generation and assembly.

## Inspect and extend

- [Tool implementations](https://github.com/Galbaz1/video-research-mcp/tree/v0.8.0-rc.1/src/video_research_mcp/tools): exact parameters and behavior. Your client's discovered MCP schemas describe the running version.
- [Windowed video analysis](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/docs/integrations/VIDEO_WINDOWS.md): dry-run budgets, continuation, upload limits and retained partial results.
- [Contributing](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/CONTRIBUTING.md): source setup and checks.
- [Security policy](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/SECURITY.md): local access, provider boundaries and reporting.
- [Changelog](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/CHANGELOG.md): changes in this candidate.

The candidate's packaged installation, local tool journeys and fresh-session
restart were verified. Live-provider quality and complete end-to-end comparative
acceptance remain open; this release makes no claim of superiority over other systems.

---

Created by **Fausto Albers** · [Wonder Why](https://wonderwhy.ai).
Built with [Google Gemini](https://ai.google.dev/),
[FastMCP](https://github.com/PrefectHQ/fastmcp) and
[Pydantic](https://docs.pydantic.dev/), with optional knowledge and tracing integrations.
Project code is [MIT licensed](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/LICENSE);
[third-party notices](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.1/THIRD_PARTY_NOTICES.md)
cover bundled components with their own terms.
