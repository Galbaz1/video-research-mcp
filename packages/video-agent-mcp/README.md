# video-agent-mcp

Generate Remotion scene components concurrently from an existing explainer
script. The server reads project files, sends scene prompts through the Claude
Agent SDK, and writes TSX plus a scene index. Use the explainer server and
upstream renderer to prepare inputs, preview scenes, and render the video.

Two tools are available: `agent_generate_scenes` and
`agent_generate_single_scene`.

Repository links below target the immutable `v0.8.0-rc.4` source tag.
This companion's version is `0.2.2rc2`. Verify registry availability before
installation. For the exact source and bundled README of a registry version,
use its source archive on
[PyPI](https://pypi.org/project/video-agent-mcp/#files).

## Install and configure

You need Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), an existing
explainer project, and supported Agent SDK authentication. The SDK bundles its
CLI; follow its [authentication guide](https://code.claude.com/docs/en/agent-sdk/overview)
for Anthropic API or supported cloud-provider credentials.

From this package directory in a source checkout:

```sh
uv sync --locked --extra dev
uv run --locked video-agent-mcp
```

The command starts a stdio MCP server. Register it in your client's configuration
rather than expecting a terminal UI. For Claude Code, add this entry to the
appropriate `mcpServers` object, replacing the absolute checkout path:

```json
{
  "video-agent": {
    "command": "uv",
    "args": [
      "run", "--locked", "--directory",
      "/absolute/path/to/video-research-mcp/packages/video-agent-mcp",
      "video-agent-mcp"
    ]
  }
}
```

After publication of this prepared candidate, register `uvx` with
`video-agent-mcp==0.2.2rc2`. Use the checkout command above until publication
and verify the exact registry archive separately. The core npm installer
does not register this companion.

Configuration comes from the process environment and
`~/.config/video-research-mcp/.env`; nonempty process values take precedence.
Use the same project location as the explainer server:

```dotenv
EXPLAINER_PATH=/absolute/path/to/video_explainer
# Optional: projects outside EXPLAINER_PATH/projects
EXPLAINER_PROJECTS_PATH=/absolute/path/to/projects
AGENT_CONCURRENCY=5
AGENT_TIMEOUT=300
AGENT_MAX_TURNS=1
```

`EXPLAINER_PATH` is the upstream checkout root. Projects default to its
`projects/` directory. If an older deployment used a projects-root value for
`EXPLAINER_PATH`, preserve that directory through `EXPLAINER_PROJECTS_PATH`.
The override also works when `EXPLAINER_PATH` is unset.

`AGENT_MODEL` overrides the default in
[`config.py`](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-agent-mcp/src/video_agent_mcp/config.py). Check the
[official model overview](https://platform.claude.com/docs/en/models/overview)
for a supported ID. Restart the server after configuration changes.

## First scene generation

1. Prepare a project with `script/script.json` containing a `scenes` list.
   The [explainer companion](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/packages/video-explainer-mcp/README.md) can create the
   project and run the script step. Scene titles must produce unique component
   filenames and registry keys.
2. If exact speech timing matters, generate voiceover first. Optional
   `voiceover/manifest.json` supplies per-scene word timestamps.
3. After authorizing provider usage, call the MCP tool:

   ```text
   agent_generate_scenes(project_id="my-video", concurrency=3)
   ```

4. Inspect both `scenes` and `errors`. Successful components appear in
   `scenes/` and `index.ts`; failed scenes remain in the result. Retry a specific
   failed scene with:

   ```text
   agent_generate_single_scene(project_id="my-video", scene_number=2)
   ```

5. Review the TSX, typecheck it, and preview it in the upstream Remotion project
   before rendering. A generated component is not proof of valid TypeScript,
   visual quality, or factual accuracy.

Batch generation refuses to overwrite existing top-level TSX unless `force=True`.
The single-scene tool regenerates its target without a force flag. Preserve a
copy before replacing a scene. A single-scene success rebuilds the index from
scene files present on disk, so inspect retained files as well as new output.

## Execution limits and failures

Queries run with bounded concurrency from 1 to 10, a per-query timeout, and a
turn limit. Pass `concurrency` explicitly for a batch; its tool default is 5.
`AGENT_TIMEOUT` defaults to 300 seconds and must be at least 30.

Child queries have no built-in tools or MCP servers and load no user/project
settings. They override the child `CLAUDECODE` guard without changing the parent
process environment. A terminal SDK success and extractable code are required
before a scene response is written as successful output. Shared styles and the
reference component are written before queries begin, so those files alone do
not establish scene completion.

On partial failure, keep the successful scenes and inspect the reported errors
before retrying only the affected scene. Each retry incurs provider usage.

## Development

From this package directory:

```sh
uv run --locked pytest tests/ -q
uv run --locked ruff check src/ tests/
uv build
```

Tests mock SDK queries and do not generate paid content. The lockfile records the
development environment; `pyproject.toml` defines supported dependency ranges.
See the root [contribution guide](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/CONTRIBUTING.md) for repository workflow
and [publishing guide](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/docs/PUBLISHING.md) for release verification.
