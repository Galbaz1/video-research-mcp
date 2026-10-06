# Getting started

Install the RC5 prerelease, connect your client, then check the running
configuration before sending material for analysis. Examples pin core
`0.8.0-rc.5` (Python `0.8.0rc5`); stable `0.7.1` predates the native Codex plugin.
Check PyPI and npm availability before installing this candidate. The server-only
route below works without the workflow bundle once the Python runtime is published.
The video companions are optional, separate installations.

For a route matched to your task or setup problem, use the
[user documentation](../README.md#choose-a-task). You can describe your problem
in your MCP client; `/gr:*` commands below are specific to Claude Code.

This guide follows source main. RC5 includes the lesson error/cleanup and
audio-DSP helper-drift fixes that followed RC3. Use the
[source checkout route](#a-source-checkout) to inspect the implementation.

## Before you install

You need Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/)
with `uvx` on the client's `PATH`, a stdio MCP client, and a
[Gemini API key](https://aistudio.google.com/apikey) for analysis. Plugin routes
also need Node.js 22+ and npm. Install FFmpeg/FFprobe for local media inspection,
frame extraction and clip exports. Weaviate, tracing and production providers
are optional.

Gemini processes selected content remotely and can incur usage charges. A selected
analysis interval does not necessarily limit the uploaded file.

## Choose an installation route

### Codex: native plugin

Follow the [README's pinned npm marketplace setup](../../README.md#codex-native-plugin),
then start a fresh Codex session. It supplies skills and the research server.
The selected RC5 local-source baseline and restart were checked on Codex
0.160.1 on 2026-10-06. The earlier RC3 check used an npm source. Provider quality
and fresh npm network acquisition versus cache reuse remain unverified. See [Distribution](../PLUGIN_DISTRIBUTION.md#native-codex-plugin)
for migration and cache preservation.

<a id="install-the-claude-code-workflows"></a>

### Claude Code: workflow bundle

Choose the scope explicitly:

```bash
npx video-research-mcp@0.8.0-rc.5 --global
# Or, from the project directory:
npx video-research-mcp@0.8.0-rc.5 --local
```

Global workflows go into `~/.claude/` and core registration into `~/.claude.json`.
Local workflows go into `.claude/`, registration into `.mcp.json`, and credentials
into `./.config/video-research-mcp/.env`. The installer registers only the core;
Playwright, MLflow MCP and video companions require separate registration.

Set the key in the selected template, restart Claude Code and inspect `/mcp`.
`npx video-research-mcp@0.8.0-rc.5 --global --check` inspects the global installation;
use `--local --check` for the project. This checks files and configuration hashes,
not a provider request.

### Server-only clients

Use the [server-only registration](#other-mcp-clients) below. It connects the
same tools without the workflow bundle.

## Configuration

The research server loads configuration in this order:

1. Process environment variables, including those supplied by the MCP client.
2. The file selected by `VIDEO_RESEARCH_ENV_FILE`, otherwise
   `~/.config/video-research-mcp/.env`.
3. Built-in defaults.

A `.env` in the source checkout is not loaded automatically. Shell exports reach
clients launched from that shell; a GUI client may have a different environment.
The shared file is useful when the same configuration should work in several
projects or clients.

After installation, edit the selected template and set `GEMINI_API_KEY`. A local
install selects the project file and does not fall back to home credentials when
that file is missing. For Codex or a manual server registration, create the shared
file if needed:

```bash
mkdir -p ~/.config/video-research-mcp
${EDITOR:-vi} ~/.config/video-research-mcp/.env
chmod 600 ~/.config/video-research-mcp/.env
```

A minimal file contains:

```dotenv
GEMINI_API_KEY=your-gemini-api-key
```

Keep credentials outside the repository. The shared file is read locally;
authentication and selected analysis content are sent to configured services.

### Add only the options you need

| Option | Default or behavior | When to set it |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.8-flash` | Choose a different supported primary model |
| `GEMINI_FLASH_MODEL` | `gemini-3.8-flash` | Choose the auxiliary summary model |
| `GEMINI_THINKING_LEVEL` | `medium` | Use `low`, `medium`, or `high` with the default model |
| `DEEP_RESEARCH_AGENT` | `deep-research-preview-04-2026` | Select another supported Deep Research agent |
| `YOUTUBE_API_KEY` | Falls back to `GEMINI_API_KEY` | Use a key with YouTube Data API v3 access |
| `GEMINI_SESSION_DB` | In-memory sessions when unset | Give SQLite a writable path to persist sessions |
| `WEAVIATE_URL`, `WEAVIATE_API_KEY` | Storage disabled when the URL is empty | Connect the optional knowledge store |
| `MLFLOW_TRACKING_URI` | Tracing disabled without a URI | Connect a tracking server and install the tracing extra |
| `S2_API_KEY` | Optional | Authenticate Semantic Scholar requests |
| `LOCAL_FILE_ACCESS_ROOT` | No configured root restriction | Limit supported local-file operations to a directory |
| `INFRA_MUTATIONS_ENABLED` | `false` | Allow model changes and cache clearing through tools |
| `INFRA_ADMIN_TOKEN` | Optional | Require a token for permitted infrastructure mutations |

The full configuration contract is
[`ServerConfig.from_env()`](../../src/video_research_mcp/config.py).
Cache lifetimes, retry limits, document limits, and storage behavior are explained
in the [architecture](../ARCHITECTURE.md) and
[knowledge-store](KNOWLEDGE_STORE.md) guides.

The default model rejects `minimal` thinking and explicit sampling overrides.
Do not set temperature merely because another Gemini model accepts it.

## Connect the research server

### Claude Code

The npm installer registers the server for you. To register only the published
Python runtime, use:

```bash
claude mcp add --transport stdio --scope user video-research -- uvx video-research-mcp==0.8.0rc5
claude mcp list
```

For tracing, use `'video-research-mcp[tracing]==0.8.0rc5'` and configure a tracking
URI. See the [official MCP registration guide](https://code.claude.com/docs/en/mcp)
for client scope and command syntax.

Restart the client, inspect its MCP connection status, and ask it to call
`infra_configure()` with no arguments. Check `current_config.default_model` and
`current_config.flash_model`. This is a read-only configuration check, with no
Gemini request. `/gr:doctor quick` adds a workflow-level environment inspection.

### Other MCP clients

Use your client's supported stdio registration format. A typical JSON entry is:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["video-research-mcp==0.8.0rc5"]
    }
  }
}
```

Ensure the client can find `uvx` and the shared configuration file. Avoid assuming
that a client substitutes shell variables inside JSON strings.

Codex can use this manual server route or the native plugin above. Choose one
registration for `video-research`; a manual entry can hide the plugin server.
Claude slash commands and agent frontmatter need a compatible workflow client.

### A source checkout

A registry installation runs the version published to PyPI. To develop or inspect
an exact source revision, clone the repository, select the revision you intend to
use, and install its lockfile:

```bash
git clone https://github.com/Galbaz1/video-research-mcp.git
cd video-research-mcp
uv sync --locked --extra dev
```

Register that checkout using its absolute path:

```bash
claude mcp add --scope local video-research -- uv --directory /absolute/path/to/video-research-mcp run --locked video-research-mcp
```

`uv run --locked video-research-mcp` also starts the server from the checkout.
It waits for MCP messages on stdin/stdout and does not open a web port. Running
that command alone is not a provider acceptance test.

To copy the source checkout's Claude workflows, run `node bin/install.js`. Its
research registration still uses the published Python runtime; replace that
registration with the source command above when you want the client to use your
checkout.

## Make a first useful call

After the configuration check, start with a small public source or a file you are
authorized to submit. These analysis calls use external services and may incur
charges.

```text
Use video_analyze to summarize <public YouTube URL>. Include timestamps for the
main claims and distinguish the speaker's claims from your assessment.
```

Or begin with a document or a web question:

```text
Use content_analyze on <document path or URL> to extract its method and limitations.
Use web_search to find primary sources about <topic> and retain the source links.
```

For reusable page-level extraction rather than a model answer, follow
[original-source ingestion](../integrations/source-ingestion.md). Builtin PDF
extraction needs Poppler; Docling is an optional, separately qualified service.
For a background report, launch `research_web` and retrieve it with
`research_web_status`; see [research status and recovery](../integrations/DURABLE_JOBS.md#research-operations).

Tool arguments are defined by the connected server's schema. The
[tool manifest](../metrics/tool-contract-manifest.json) is a dated source snapshot,
not a version guarantee for your running package. Claude Code commands such as
`/gr:video` add a workflow around a tool call;
they may save notes, extract frames, or use additional providers.

### Inspect a local frame

With FFmpeg/FFprobe and the required image dependencies installed, ask your client
to call `video_frame` with an accessible local video:

```json
{
  "file_path": "/absolute/allowed/path/recording.mp4",
  "time_seconds": 12.5,
  "include_image": false
}
```

This returns source metadata for the selected frame without an image block. Set
`include_image` to `true` for a native image preview. Inspect the actual decoded
time; the first frame at or after the request can differ from the requested time.
The [source-export guide](../integrations/IMAGE_EXPORTS.md) covers image edits and
finite clip exports. See the [task selector](../README.md#choose-a-task) for audio,
knowledge and optional production routes.

### Responses and errors

Success responses contain the tool's structured result. Custom output schemas
allow a caller-defined shape on supported tools. On failure, tools generally
return an error dictionary with a category, hint, and retryable flag:

```json
{
  "error": "The requested operation is unavailable",
  "category": "PERMISSION_DENIED",
  "hint": "Check the operation's access requirements",
  "retryable": false
}
```

This is an illustrative shape, not a promised error for every operation.
Use the actual category and hint. Gemini calls already use bounded backoff for
transient failures; avoid adding an unbounded client retry loop.

### Model presets

`infra_configure()` reports available presets without changing anything. Changing
a preset through `/gr:models` or the tool requires
`INFRA_MUTATIONS_ENABLED=true` and, if configured, the matching admin token.
Restart the server after changing those environment settings.

| Preset | Primary model | Auxiliary model |
|---|---|---|
| `best` | `gemini-3.1-pro-preview` | `gemini-3.8-flash` |
| `stable` | `gemini-3.8-flash` | `gemini-3.8-flash` |
| `budget` | `gemini-3.5-flash-lite` | `gemini-3.5-flash-lite` |

An allowed change affects later calls in that server process. Provider entitlement,
quota, and model availability still need verification.

## Optional companion servers

The [explainer](../../packages/video-explainer-mcp/README.md) and
[scene-agent](../../packages/video-agent-mcp/README.md) packages have their own
configuration and prerequisites. The explainer needs an external
`video_explainer` checkout; scene generation needs Claude access.

Register their local entry points only after installing the packages and setting
up the prerequisites in those guides. A connected companion server does not prove
that its provider or rendering pipeline is ready. The default mock narration is
for previews.

## Troubleshooting

| Symptom | Check |
|---|---|
| Server fails to start | Client logs, Python/uv availability, configured launch path, and `GEMINI_API_KEY` |
| API key works in a terminal but not the client | Process environment precedence and the shared configuration file |
| YouTube metadata returns 403 | YouTube Data API v3 enabled for the key's project, key restrictions, and `YOUTUBE_API_KEY` |
| Analysis returns quota or permission errors | Actual error category, provider account access, quota, and selected model |
| A download reports `Unsupported Content-Encoding` | The server compressed the response despite the identity request. Supply the original as a local file, or use a URL that honors the request. |
| A repeated video analysis returns an old result | Use `video_analyze` with `use_cache=false`; cache clearing requires mutation permission |
| Knowledge operation is unavailable | Weaviate connection, collection access, and optional dependencies |
| Local frames are missing | `ffmpeg`, local source access, and the frame-extraction workflow |
| A model change is denied | Infrastructure mutation policy and optional admin token |
| Source changes do not affect the client | The exact launch command and whether it runs PyPI or the checkout |

For YouTube metadata, comments, and playlists, enable
[YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
for the key's Google Cloud project. These tools call YouTube directly; Gemini video
analysis has a different provider path and access requirements.

When a request remains blocked after a controlled retry, retain the error and fix
the stated cause. A successful connection, local test, or generated summary proves
a different thing from a successful provider-backed analysis of your source.

## Continue from here

Read the [documentation index](../README.md) for the next task, or go directly to
[knowledge storage](KNOWLEDGE_STORE.md), [adding a tool](ADDING_A_TOOL.md),
[writing tests](WRITING_TESTS.md), or [architecture](../ARCHITECTURE.md).
