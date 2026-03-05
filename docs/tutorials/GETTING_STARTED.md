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
git clone https://github.com/<org>/video-research-mcp.git
cd video-research-mcp
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

Verify the installation:

```bash
video-research-mcp --help
```

## Environment Variables

Create a `.env` file or export directly. Only `GEMINI_API_KEY` is required -- everything else has sensible defaults.

```bash
# Required
export GEMINI_API_KEY="your-gemini-api-key"

# Optional -- shown with defaults
export GEMINI_MODEL="gemini-3.1-pro-preview"
export GEMINI_FLASH_MODEL="gemini-3-flash-preview"
export GEMINI_THINKING_LEVEL="high"          # minimal | low | medium | high
export GEMINI_TEMPERATURE="1.0"
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

**Security**: This file lives on your machine only. It is never uploaded, committed to git, or sent to any remote service. The server reads it locally at startup — that's it. We recommend `chmod 600` so only your user can read it.

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

Add the server to your MCP configuration. For global access across all projects, edit `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/video-research-mcp",
        "run", "video-research-mcp"
      ],
      "env": {
        "GEMINI_API_KEY": "your-key"
      }
    }
  }
}
```

For project-local configuration, create `.mcp.json` in the project root with the same structure.

After saving, restart Claude Code. All 28 tools will appear automatically in Claude's tool list.

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
Use infra_configure with preset "best"    # Gemini 3.1 Pro (highest quality)
Use infra_configure with preset "stable"  # Gemini 3 Pro (higher rate limits)
Use infra_configure with preset "budget"  # Gemini 3 Flash (fastest, cheapest)
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
3. **Different keys in different contexts** -- If you use direnv/dotenv, the key in your `.env` may differ from the one in your shell profile (`~/.zshrc`). The MCP server gets the key from Claude Code's process environment, not from `.env`.

**Fix:**

1. Visit [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) and click **Enable** for the GCP project that owns your API key
2. Or set a separate `YOUTUBE_API_KEY` env var pointing to a key with YouTube Data API v3 scope
3. Verify with: `video_metadata(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")` -- should return metadata, not an error

### Rate limit / quota errors

Switch to a cheaper model preset:

```
Use infra_configure with preset "budget"
```

Or wait and retry -- the server returns `retryable: true` with `retry_after_seconds: 60` for quota errors.

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
