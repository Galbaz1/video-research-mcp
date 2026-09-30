# video-agent-mcp

Generate Remotion scene components concurrently from an existing explainer project.
This server exposes `agent_generate_scenes` and `agent_generate_single_scene`.
It calls the Claude Agent SDK for text generation, then writes returned TSX and a
scene index. It does not orchestrate research or build a finished video.

## Install and configure

Python 3.11 or newer is required. From this directory:

```sh
uv sync --extra dev --frozen
uv run video-agent-mcp
```

For an installed release, use `uvx video-agent-mcp`. The Claude Agent SDK bundles
its CLI; authentication must be configured through a supported Anthropic API or
cloud-provider credential environment. Follow the [SDK authentication guide](https://code.claude.com/docs/en/agent-sdk/overview).

Configuration is read from environment variables and
`~/.config/video-research-mcp/.env`. Existing environment values take precedence.
The explainer and agent servers use the same project location:

```dotenv
EXPLAINER_PATH=/absolute/path/to/video_explainer
# Optional: projects outside EXPLAINER_PATH/projects
EXPLAINER_PROJECTS_PATH=/absolute/path/to/projects
AGENT_CONCURRENCY=5
AGENT_TIMEOUT=300
AGENT_MAX_TURNS=1
```

`AGENT_MODEL` overrides the current default in
`src/video_agent_mcp/config.py`. Verify IDs against the
[official model overview](https://platform.claude.com/docs/en/models/overview)
before overriding it. The default is the current Sonnet model.

`EXPLAINER_PATH` points to the upstream checkout, **not its projects directory**.
For an existing deployment that used the old projects-root interpretation, set
`EXPLAINER_PROJECTS_PATH` to that old value. The override is also available when
`EXPLAINER_PATH` is unset.

## First scene generation

1. Create a project with the explainer server and generate its script.
   The project must contain `script/script.json` with a `scenes` list.
2. Generate voiceover if exact speech timing is needed. The optional
   `voiceover/manifest.json` provides per-scene word timestamps.
3. Call `agent_generate_scenes(project_id="my-video", concurrency=3)`.
   Scene titles must map to unique component filenames and registry keys.
4. Inspect the `scenes` and `errors` lists. Retry failed scenes with
   `agent_generate_single_scene(project_id="my-video", scene_number=2)`.
5. Typecheck and preview the returned TSX in the upstream Remotion project
   before rendering.

Scene generation incurs provider usage. Concurrency is bounded from 1 to 10,
queries have a timeout and turn limit, and failed scenes remain in the results.
A query requires a terminal SDK success message; partial or failed responses are
not written as successful scenes. Queries receive no built-in tools or MCP
servers, and do not load project or user settings. The server performs file writes
only after generation.

`force=True` allows existing scene files to be overwritten. Scene extraction
checks that a response contains code; it does not prove TypeScript compilation,
visual quality, or factual accuracy. Render validation belongs to the upstream
renderer and the explainer server.

## Development

```sh
uv run pytest tests/ -q
uv run ruff check src/ tests/
uv build
```

Tests mock SDK queries and never generate paid content. The committed lockfile
records the verified development environment; dependency constraints stay within
the supported SDK minor release and library major versions.
