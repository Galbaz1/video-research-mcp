# video-explainer-mcp

Create explainer projects, run pipeline steps, and render videos through MCP.
This server wraps the [video_explainer CLI](https://github.com/prajwal-y/video_explainer)
with 15 tools for projects, generation, rendering, audio, and quality checks.
The upstream checkout owns provider integrations, model selection, Remotion
code, and rendering dependencies.

Repository links point to the published source release. For the exact source
and bundled README of a registry version, use its source archive on
[PyPI](https://pypi.org/project/video-explainer-mcp/#files).

## Install and configure

The wrapper requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).
Before generation, install the upstream CLI in its own checkout and virtual
environment, following that checkout's instructions. The wrapper expects:

- `<EXPLAINER_PATH>/.venv/bin/video-explainer` as an executable console script.
- The Node.js version required by the upstream checkout, plus FFmpeg on `PATH`.
- Upstream Remotion npm dependencies under `remotion/node_modules/`.
- Credentials and compatible upstream support for each provider you intend to use.

From this package directory in a source checkout:

```sh
uv sync --locked --extra dev
uv run --locked video-explainer-mcp
```

The command starts a stdio server. Add this entry to your client's `mcpServers`
configuration, replacing the absolute checkout path:

```json
{
  "video-explainer": {
    "command": "uv",
    "args": [
      "run", "--locked", "--directory",
      "/absolute/path/to/video-research-mcp/packages/video-explainer-mcp",
      "video-explainer-mcp"
    ]
  }
}
```

For a registry release, register `uvx` with
`video-explainer-mcp==<published-version>` and confirm that version is published.
The core npm installer does not register this companion or install the upstream
renderer.

Configuration comes from the process environment and
`~/.config/video-research-mcp/.env`; nonempty process values take precedence:

```dotenv
EXPLAINER_PATH=/absolute/path/to/video_explainer
# Optional: defaults to EXPLAINER_PATH/projects
EXPLAINER_PROJECTS_PATH=/absolute/path/to/projects
EXPLAINER_TTS_PROVIDER=mock
EXPLAINER_TIMEOUT=600
EXPLAINER_RENDER_TIMEOUT=1800
```

Restart after changing configuration. `EXPLAINER_PATH` is the checkout root,
not the projects directory. The CLI runs directly without a shell, receives
`--projects-dir`, and inherits provider credentials while recursive Claude Code
guard variables are removed from its child environment.

Wrapper TTS selectors are `mock`, `elevenlabs`, and `edge`.
The default `mock` avoids paid TTS; other generation steps can still call paid
providers. A selector is usable only if the upstream CLI supports it and its
credentials are configured. Updating this wrapper does not update that checkout
or add upstream provider support.

The wrapper exposes `script` refinement and render presets `720p`, `1080p`, and
`4k`. These choices match the supported upstream CLI contract. Pipeline steps
remain `script`, `narration`, `scenes`, `voiceover`, and `storyboard`.

## First project and render

These are MCP calls, made through your client after registration:

1. Create a project:

   ```text
   explainer_create(project_id="my-video")
   ```

2. Add source material:

   ```text
   explainer_inject(project_id="my-video", content="...", filename="research.md")
   ```

   `filename` must be a single filename inside `input/`. Injection replaces an
   existing file with the same name; preserve the original when that matters.
3. Authorize generation, then run a bounded step such as
   `explainer_step(project_id="my-video", step="script")`, or use
   `explainer_generate` for the pipeline. Inspect returned errors and outputs
   before continuing. `force=True` reruns already completed generation steps.
4. Read `explainer_status` and inspect the actual generated files. Review and
   typecheck TSX upstream, then preview scenes before rendering.
5. Start a render with `explainer_render_start(project_id="my-video")`. Poll the
   returned `job_id` with `explainer_render_poll` until `completed` or `failed`.
   Use blocking `explainer_render` for a short render.

Render acceptance requires exit code zero and a new or updated, nonempty regular
`.mp4` or `.webm` file in the project's `output/`. An unchanged older video does
not satisfy the current render. Inspect the returned output path, decode/play
that file, and review picture, sound, timing, and claims before publication.
The wrapper's artifact check establishes file production, not those quality checks.

## Status and recovery

`explainer_status` reports filesystem observations. A step file's presence does
not establish its validity or publication readiness. Background jobs live in
memory, so their IDs are lost on restart. Shutdown cancels and joins active render
tasks and stops their CLI subprocesses.

The server prevents concurrent renders of the same project. After a failure,
inspect the job error and project output before retrying. Preserve project files
when upgrading the wrapper or renderer; they are separate from package installs.

## Development

From this package directory:

```sh
uv run --locked pytest tests/ -q
uv run --locked ruff check src/ tests/
uv build
```

Tests use temporary projects and mocked CLI processes; no paid provider calls
are made. The lockfile records the development environment; `pyproject.toml`
defines supported dependency ranges. See the root
[contribution guide](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/CONTRIBUTING.md) and
[publishing guide](https://github.com/Galbaz1/video-research-mcp/blob/96f11b8c7d70a1bc4d73bfa500482f9811e4141f/docs/PUBLISHING.md) for repository and release checks.
