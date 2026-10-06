# video-explainer-mcp

Create explainer projects, run pipeline steps, and render videos through MCP.
This server wraps the [video_explainer CLI](https://github.com/prajwal-y/video_explainer)
with 32 tools for projects, editorial plans, generation, rendering, audio, commentary,
narration timing, revision-bound feedback, existing-material assembly, and quality
checks. Stock-media search/download tools are not mounted.
The upstream checkout owns provider integrations, model selection, Remotion
code, and rendering dependencies. The pinned upstream licence grant remains
unresolved: this package independently authors the plan contract and ships no
upstream code or runtime. Installation and rights for a separate CLI remain
operator responsibilities.

Repository links below target the immutable `v0.8.0-rc.4` source tag.
This companion's published PyPI version is `0.2.2rc2`. For the exact source and
bundled README of a registry version,
use its source archive on
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

The published wrapper can run directly from PyPI as a stdio MCP server. Add
this entry to your client's `mcpServers` configuration:

```json
{
  "video-explainer": {
    "command": "uvx",
    "args": ["video-explainer-mcp==0.2.2rc2"]
  }
}
```

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
5. Inspect `explainer_doctor(project_id="my-video")` before rendering. It reads
   local Node/FFmpeg/ffprobe versions, selected Remotion packages and cached browser,
   the reviewed external source and project paths. It makes no provider call and
   installs or downloads nothing. `all_ok` means technical prerequisites are present;
   real renderer execution, runtime grants and picture/sound quality remain unverified.
6. Start a render with `explainer_render_start(project_id="my-video")`. Poll the
   returned `job_id` with `explainer_render_poll` until `completed` or `failed`.
   Use blocking `explainer_render` for a short render.

Render acceptance requires a fresh regular H264 MP4 at the exact selected CLI output
path, requested dimensions, finite duration and a complete FFmpeg decode. The
maximum file size is 512 MiB; probe/decode limits are 10/60 seconds. An unchanged
older video or a different output path cannot satisfy the current request. The
canonical storyboard path must be `storyboard/storyboard.json`: the selected public
CLI's Node entry ignores configured alternatives. The 720p/4k output is
`output/final-720p.mp4`/`output/final-4k.mp4`; 1080p uses `paths.final_video`, which
must be a direct MP4 in `output/`; nested/traversal output paths are unsupported.

`playability_verified` reports full decoding of the exact output bytes. It does
not certify actual Remotion/TTS production or picture, sound, timing and factual
claims. `real_renderer_verified` remains false. Polling older completed jobs without
a byte-bound decode receipt reports `unknown` and withholds the output path.
Legacy full generation prepares through storyboard then uses this same render
gate; it bypasses upstream mock rendering and retained-output skipping. Managed
editorial generation still stops at storyboard and renders separately.

## Status and recovery

`explainer_status` reports filesystem observations. A step file's presence does
not establish its validity or publication readiness. Render jobs are durable in
the configured SQLite job store. Restart preserves IDs and receipts; unavailable
process ownership is reported as unknown rather than automatically rerun.
Shutdown cancels and joins active render tasks and stops their CLI subprocesses.

The server prevents concurrent renders of the same project. After a failure,
inspect the job error and project output before retrying. Preserve project files
when upgrading the wrapper or renderer; they are separate from package installs.

## Editorial plans

`explainer_plan(project_id, request)` works locally with `EXPLAINER_PROJECTS_PATH`
and an existing `input/evidence-packet.json`; plan review needs no CLI, stdin or
provider. Use `create`, `show`, `revise` and `approve` with compare-and-swap
`expected_revision`. A full replacement plan records audience, thesis, ordered
concepts/scenes, purpose, exact claim IDs, durations and explicit inclusion or
rejection of every source. Revision invalidates approval and output bindings.

The project stores this authority in `planning.sqlite3`. Approval is editorial;
unchanged source bytes and approved exact claim text are required. Managed script
production rejects different narration, scene order/purpose or duration budgets.
Accepted script and storyboard bytes receive `video_research_plan` provenance.
Use `show` to read actual binding hashes and `current` status before rendering.
Storyboard binding checks the exact script parent and observed scene IDs/titles/
timing; visual/audio semantics remain unverified. External model output that
paraphrases approved claims is retained as a failed output and cannot be accepted.

Managed generation uses supported individual stages and stops at storyboard;
render separately through durable render tools. The CLI reads
`config.json → paths.storyboard`: declare a relative confined JSON path. Plan
operations and managed generation/refinement/injection share a fail-fast SQLite
transaction; a concurrent operation returns busy instead of waiting on stdin.
Legacy projects without a managed plan retain their existing CLI arguments.
See the repository's `docs/integrations/video-planning.md` for complete examples,
output checks and the remaining provider/media acceptance boundaries.

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
[contribution guide](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/CONTRIBUTING.md) and
[publishing guide](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.4/docs/PUBLISHING.md) for repository and release checks.
