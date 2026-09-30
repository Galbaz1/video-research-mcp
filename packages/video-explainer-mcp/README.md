# video-explainer-mcp

Expose the [video_explainer CLI](https://github.com/prajwal-y/video_explainer)
as MCP tools for project setup, pipeline steps, audio, quality checks, and video
rendering. This package is a wrapper: the upstream checkout owns model selection,
provider integrations, Remotion templates, and rendering dependencies.

## Install and configure

Python 3.11 or newer is required. From this directory:

```sh
uv sync --extra dev --frozen
uv run video-explainer-mcp
```

For an installed release, use `uvx video-explainer-mcp`. Before calling tools,
install the upstream CLI in its own virtual environment, following that checkout's
setup instructions. This server expects
`<EXPLAINER_PATH>/.venv/bin/video-explainer`, plus the Node.js version declared by
that checkout, FFmpeg, and upstream Remotion npm dependencies. It invokes the
console script directly without a shell.

Configuration is read from environment variables and
`~/.config/video-research-mcp/.env`. Existing environment values take precedence:

```dotenv
EXPLAINER_PATH=/absolute/path/to/video_explainer
# Optional: defaults to EXPLAINER_PATH/projects
EXPLAINER_PROJECTS_PATH=/absolute/path/to/projects
EXPLAINER_TTS_PROVIDER=mock
EXPLAINER_TIMEOUT=600
EXPLAINER_RENDER_TIMEOUT=1800
```

Supported wrapper TTS selectors are `mock`, `elevenlabs`, `openai`, `gemini`, and
`edge`. Real providers require credentials and compatible provider support in the
upstream CLI. The default `mock` avoids paid TTS; other pipeline steps may still
call model providers. Updating this wrapper does not update the external checkout
or add support for new provider models. Supply secrets through the environment or
your local untracked configuration file.

## First project and render

1. Call `explainer_create(project_id="my-video")`.
2. Call `explainer_inject(project_id="my-video", content="...", filename="research.md")`.
   The filename must remain within the project's `input/` directory.
3. Call `explainer_generate`, or use `explainer_step` for a bounded pipeline step.
4. Inspect `explainer_status`, then preview/typecheck generated scenes upstream.
5. Call `explainer_render_start` and poll its returned job ID with
   `explainer_render_poll`. Use blocking `explainer_render` for shorter renders.

Render completion requires exit code zero and a new or updated, nonempty `.mp4`
or `.webm` file in the project's `output/` directory. A retained video from an
older run does not prove the current render succeeded. Artifact detection verifies
file production; it does not decode video, prove visual quality, or fact-check its
contents.

Background jobs live in memory and are lost when the server restarts. Shutdown
cancels and joins active render tasks and stops their CLI subprocesses. Poll for
`completed` or `failed`, and inspect the recorded output path or error. Do not
start a second render while the same project's first render is still running.

`explainer_status` reports filesystem observations. A step file's presence alone
does not prove that it is valid or that the entire video is ready for publication.

## Development

```sh
uv run pytest tests/ -q
uv run ruff check src/ tests/
uv build
```

All tests use temporary projects and mocked CLI processes; no test calls paid
providers. The committed lockfile records the verified development environment,
and dependencies remain constrained to their supported major versions.
