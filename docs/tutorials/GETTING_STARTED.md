# Getting Started

A step-by-step guide to installing, configuring, and running the video-research-mcp server, then connecting it to Claude Code and making your first tool calls.

## Prerequisites

- **Python 3.11+** -- check with `python3 --version`
- **uv** -- the fast Python package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **Gemini API key** -- get one at [Google AI Studio](https://aistudio.google.com/apikey)
- **YouTube Data API v3** enabled for your GCP project -- required for `video_metadata`, `video_comments`, and `video_playlist` tools. See [YouTube API 403 errors](#youtube-api-403-errors) if you hit issues

## Installation

Clone the repo and install in development mode:

```bash
git clone https://github.com/Galbaz1/video-research-mcp.git
cd video-research-mcp
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

Verify the installation:

```bash
uv run python scripts/export_tool_contract_manifest.py --output /tmp/video-research-tools.json
```

## Environment Variables

Use the shared configuration file below or export directly. A checkout `.env` is not automatically loaded. Only `GEMINI_API_KEY` is required -- everything else has sensible defaults.

```bash
# Required
export GEMINI_API_KEY="your-gemini-api-key"

# Optional -- shown with defaults
export GEMINI_MODEL="gemini-3.8-flash"
export GEMINI_FLASH_MODEL="gemini-3.8-flash"
export GEMINI_THINKING_LEVEL="medium"        # low | medium | high for the default model
export GEMINI_TEMPERATURE="1.0"            # omitted from Gemini 3.6+ Flash API requests
export GEMINI_CACHE_DIR="$HOME/.cache/video-research-mcp/"
export GEMINI_CACHE_TTL_DAYS="30"
export GEMINI_MAX_SESSIONS="50"
export GEMINI_SESSION_TIMEOUT_HOURS="2"
export GEMINI_SESSION_MAX_TURNS="24"
export GEMINI_RETRY_MAX_ATTEMPTS="3"
export GEMINI_RETRY_BASE_DELAY="1.0"
export GEMINI_RETRY_MAX_DELAY="60.0"
export YOUTUBE_API_KEY=""                    # falls back to GEMINI_API_KEY
export GEMINI_SESSION_DB=""                  # empty = in-memory sessions only

# Knowledge store (optional -- requires Weaviate)
export WEAVIATE_URL=""                       # empty = knowledge tools disabled
export WEAVIATE_API_KEY=""
```

The full list lives in `src/video_research_mcp/config.py:ServerConfig.from_env()`.

### Shared config file

The server auto-loads `~/.config/video-research-mcp/.env` at startup, so keys are available in **any workspace** without direnv or shell profile changes.

**Loading order** (first wins):
1. Process environment variables (set by shell, direnv, or MCP `env` block)
2. `~/.config/video-research-mcp/.env` config file
3. Built-in defaults in `ServerConfig`

**Security**: The server reads the configuration file locally. Its credential values authenticate calls to configured providers; analysis prompts and uploaded media are processed remotely. Keep the file out of git, use `chmod 600`, and report only key-presence checks in diagnostics.

Create the file manually or let the npm installer generate a template:

```bash
# Manual
mkdir -p ~/.config/video-research-mcp
cat > ~/.config/video-research-mcp/.env << 'EOF'
GEMINI_API_KEY=your-key
# YOUTUBE_API_KEY=          # falls back to GEMINI_API_KEY
# WEAVIATE_URL=             # empty = knowledge tools disabled
# WEAVIATE_API_KEY=
EOF
chmod 600 ~/.config/video-research-mcp/.env

# Or via installer (creates a commented template with mode 600)
npx video-research-mcp@latest
```

## Running the Server

### Standalone (stdio transport)

```bash
GEMINI_API_KEY=your-key uv run video-research-mcp
```

The server starts on stdio (standard MCP transport). It does not open a port -- the MCP client connects via stdin/stdout.

### With direnv (recommended for development)

Create an `.envrc`:

```bash
source .venv/bin/activate
export GEMINI_API_KEY="your-key"
```

Then `direnv allow` and run:

```bash
video-research-mcp
```

## Connecting from Claude Code

Register the published runtime using Claude Code's supported CLI:

```bash
claude mcp add --scope user video-research -- uvx --refresh 'video-research-mcp[tracing]'
claude mcp list
```

User registrations live in `~/.claude.json`; project scope uses `.mcp.json`. The shared environment file supplies credentials without copying them into registration commands. For a source checkout, use `claude mcp add --scope local video-research -- uv --directory /absolute/path/to/video-research-mcp run video-research-mcp`.

Restart the client, inspect `/mcp`, and call `infra_configure()` without arguments. Confirm the actual model IDs and process connection before analysis. The registered runtime has 34 tools; see the generated [tool manifest](../metrics/tool-contract-manifest.json) for exact contracts. These counts do not imply the optional companion servers are installed.

### Other MCP clients, including Codex

The server uses standard stdio MCP. Configure `uvx` with arguments `--refresh`, `video-research-mcp[tracing]`, or use `uv --directory <checkout> run video-research-mcp` for an exact source revision. Follow the client's current configuration schema. The npm installer targets Claude Code; it does not install a Codex plugin manifest. Skills can be reused in clients supporting `SKILL.md`, but Claude slash commands/agent frontmatter are client-specific. See [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins) before claiming native Codex distribution.

### Optional companion servers from source

The explainer and scene-agent packages are not registered by the default installer. Install their declared development environments, configure the external `video_explainer` checkout and provider credentials, then register their local entry points:

```bash
claude mcp add --scope local video-explainer -- uv --directory /absolute/path/to/video-research-mcp/packages/video-explainer-mcp run video-explainer-mcp
claude mcp add --scope local video-agent -- uv --directory /absolute/path/to/video-research-mcp/packages/video-agent-mcp run video-agent-mcp
```

A successful registration is separate from an executable pipeline. Verify `EXPLAINER_PATH`, prerequisite binaries, writable project directories, and provider availability before generation. Default mock TTS produces a preview, not production narration.

## First Tool Calls

Once connected, try these from Claude Code:

### Analyze a YouTube video

```
Use video_analyze to summarize this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

Claude will call `video_analyze(url="...", instruction="summarize this video")` and return a structured `VideoResult` with title, summary, key_points, timestamps, topics, and sentiment.

### Analyze with a custom instruction

```
Use video_analyze to extract all CLI commands shown in https://www.youtube.com/watch?v=<id>
```

The `instruction` parameter accepts free text -- Gemini interprets it and returns structured JSON.

### Analyze content from a URL

```
Use content_analyze to extract the methodology from https://arxiv.org/abs/2301.00001
```

### Search the web

```
Use web_search to find recent papers on multimodal language models
```

### Get video metadata (no Gemini cost)

```
Use video_metadata on https://www.youtube.com/watch?v=<id>
```

Returns title, description, view/like/comment counts, duration, tags, and channel info. Uses the YouTube Data API directly (0 Gemini tokens).

### Custom output schemas

For structured extraction with a caller-defined shape:

```
Use video_analyze on <url> with instruction "List all recipes" and output_schema:
{"type": "object", "properties": {"recipes": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "ingredients": {"type": "array"}}}}}}
```

## Model Presets

Switch between quality/cost trade-offs at runtime:

```
Use infra_configure with preset "best"    # Gemini 3.1 Pro preview + Gemini 3.8 Flash
Use infra_configure with preset "stable"  # Gemini 3.8 Flash for both routes
Use infra_configure with preset "budget"  # Gemini 3.5 Flash-Lite for both routes
```

The change takes effect immediately for all subsequent tool calls.

## Understanding Tool Responses

All tools return dicts. On success, you get structured data matching the tool's Pydantic model. On failure, you get an error dict:

```json
{
  "error": "API key lacks permission...",
  "category": "API_PERMISSION_DENIED",
  "hint": "API key lacks permission OR video is restricted",
  "retryable": false
}
```

Error categories include `URL_INVALID`, `API_QUOTA_EXCEEDED`, `FILE_NOT_FOUND`, `WEAVIATE_CONNECTION`, and others. See `src/video_research_mcp/errors.py` for the full list.

The `retryable` flag indicates whether the error is transient (network timeout, rate limit). The server has built-in exponential backoff for transient Gemini API errors (configurable via `GEMINI_RETRY_*` env vars).

## Troubleshooting

### "No Gemini API key" error

Set `GEMINI_API_KEY` in your environment or MCP config's `env` block.

### "Could not extract video ID" error

The URL must be a real YouTube domain (`youtube.com`, `youtu.be`, `m.youtube.com`). The server rejects spoofed domains like `youtube.com.evil.test` to prevent URL injection.

### YouTube API 403 errors

All YouTube tools (`video_metadata`, `video_comments`, `video_playlist`) require YouTube Data API v3 access. A 403 error means your API key can't reach this API.

**Common causes:**

1. **AI Studio key restriction** -- Keys from [Google AI Studio](https://aistudio.google.com/apikey) are often restricted to `generativelanguage.googleapis.com` only. They work for Gemini but not YouTube Data API.
2. **YouTube Data API v3 not enabled** -- The API must be explicitly enabled in your GCP project.
3. **Different keys in different contexts** -- If you use direnv/dotenv, the key in your `.env` may differ from the one in your shell profile (`~/.zshrc`). The MCP server prioritizes process environment over the shared configuration; a project `.env` requires explicit loading.

**Fix:**

1. Visit [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) and click **Enable** for the GCP project that owns your API key
2. Or set a separate `YOUTUBE_API_KEY` env var pointing to a key with YouTube Data API v3 scope
3. Verify with: `video_metadata(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")` -- should return metadata, not an error

### Rate limit / quota errors

Inspect the error category and your provider quota first. If the task permits a lower-cost model, use:

```
Use infra_configure with preset "budget"
```

The server applies configured backoff for transient errors. Do not stack unbounded client retries on it: allow one controlled retry of an idempotent call, preserve the error, and stop when quota or infrastructure remains unavailable.

### Video analysis returns cached results

The file-based cache keys on `{content_id}_{tool}_{instruction_hash}_{model_hash}`. To force a fresh analysis:

```
Use video_analyze on <url> with use_cache=false
```

Or clear the cache:

```
Use infra_cache with action "clear"
```

### MCP server not appearing in Claude Code

1. Check that the path in `.mcp.json` points to the correct directory
2. Verify `uv run video-research-mcp` works from that directory
3. Restart Claude Code after editing `.mcp.json`
4. Check Claude Code logs for MCP connection errors

### Knowledge tools return empty results

Knowledge tools require a running Weaviate instance. Set `WEAVIATE_URL` to enable them. See [KNOWLEDGE_STORE.md](./KNOWLEDGE_STORE.md) for setup instructions.

## Next Steps

- [Adding a New Tool](./ADDING_A_TOOL.md) -- extend the server with your own tools
- [Writing Tests](./WRITING_TESTS.md) -- test conventions and fixtures
- [Knowledge Store](./KNOWLEDGE_STORE.md) -- persistent semantic storage with Weaviate
- [Architecture Guide](../ARCHITECTURE.md) -- deep dive into the server's design
