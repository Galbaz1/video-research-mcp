# Contributing to video-research-mcp

Contribute a focused change that another maintainer can review and reproduce.
The project is MIT licensed. Use GitHub issues to discuss bugs and proposals;
for larger changes, agree on the approach before implementation.

## Development Setup

Requirements are Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and
Node.js 22 or newer for installer work. CI uses Node.js 24. Dependency ranges
live in each package's `pyproject.toml`; committed lockfiles define the tested
Python environments.

```sh
git clone https://github.com/Galbaz1/video-research-mcp
cd video-research-mcp
uv sync --locked --extra dev
```

Read [AGENTS.md](AGENTS.md) for repository guidance, plus
[src/AGENTS.md](src/AGENTS.md) or [tests/AGENTS.md](tests/AGENTS.md) for the files
you change. The two companion packages have independent environments and tests:

- [video-explainer-mcp](packages/video-explainer-mcp/README.md)
- [video-agent-mcp](packages/video-agent-mcp/README.md)

For workflow/installer changes, use the isolated Node tests. They exercise
installation without writing to your active global Claude Code configuration.

## Running Tests

From the repository root:

```sh
uv run --locked pytest tests/ -q
uv run --locked ruff check src/ tests/
node --test tests/installer.test.js
```

For a focused change, run the affected file while developing, for example:

```sh
uv run --locked pytest tests/test_video_tools.py -q
```

Tests mock provider clients and require no real API key. Never make live Gemini,
Anthropic, or other provider requests in the automated suite. See
[Writing Tests](docs/tutorials/WRITING_TESTS.md) for fixtures and patterns.
Run a companion's checks from that package directory using its locked environment.

## Code Style

- Use Google-style docstrings and explicit, typed code. Ruff targets Python 3.11
  with a line length of 100.
- Tool parameters use `Annotated[type, Field(...)]`; decorators include
  `ToolAnnotations` describing effects accurately.
- Use Pydantic models for structured domain output and shared aliases in `types.py`.
- Tools return error dictionaries through `make_tool_error()` rather than exposing
  unhandled exceptions.
- Aim for about 300 executable lines per production module. Explain a concrete
  reason when a smaller change requires exceeding that guideline.
- Keep credentials outside source and preserve local files, custom client
  environment, and unrelated working-tree changes.

## Making Changes

### Before You Start

Check [existing issues](https://github.com/Galbaz1/video-research-mcp/issues) and
[ROADMAP.md](ROADMAP.md). The roadmap distinguishes source capabilities from
proposals; a proposal is not an approved implementation assignment. Comment on
an issue when you intend to take it on.

### Pull Request Process

1. Fork the repository and create a branch from `main`.
2. Make a single-purpose change in clear, atomic commits. Keep unrelated changes
   out of the patch.
3. Add or update tests for changed behavior and failure cases.
4. Run the affected checks and the relevant final suite. If dependencies change,
   refresh the owning lockfile and run that package's full tests.
5. Update affected docs, tool inventories, and changelog entries. For shipped
   workflows, verify `FILE_MAP`, referenced resources, and `npm pack --dry-run`.
6. Open a PR against `main` using the repository template. Describe the trigger,
   resulting behavior, validation, and unresolved limitations.

Automated CI and hosted AI review are separate results. Report checks that were
skipped, failed, or unavailable explicitly. For a review request, use
`scripts/detect_review_scope.py --json` and review one scope according to its
priority: uncommitted changes, then PR, then commits. See
[review scope protocol](AGENTS.md#code-review-trigger-protocol).

### Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/), for example:

```text
feat(video): add batch analysis for directories
fix(content): handle timeout on large PDFs
docs(readme): clarify runtime installation
test(research): cover evidence assessment failures
refactor(client): extract retry logic
```

## Architecture Overview

The core mounts seven FastMCP sub-servers: video, research, content, search,
infra, YouTube, and knowledge. Tools accept instructions and return structured
results; Gemini output is validated against the relevant schema. Optional
Weaviate persistence, tracing, and reranking have their own configuration and
failure boundaries.

Read [Architecture](docs/ARCHITECTURE.md) for code responsibilities and
[Distribution](docs/PLUGIN_DISTRIBUTION.md) for installer ownership/configuration.
The companion servers wrap separate scene-generation and rendering workflows.

## Adding a New Tool

Follow [Adding a Tool](docs/tutorials/ADDING_A_TOOL.md) for the complete procedure.
Add the function to the appropriate sub-server, include annotations and constrained
parameters, define structured output, register it, and test success and failure
without provider calls. Update the actual tool manifest and affected workflows.
Do not copy a historical tool count into new documentation.

## Questions?

Open an issue for development questions or contact
[Fausto Albers](https://wonderwhy.ai). Report vulnerabilities privately through
[Security](SECURITY.md); community participation follows the
[Code of Conduct](CODE_OF_CONDUCT.md).
