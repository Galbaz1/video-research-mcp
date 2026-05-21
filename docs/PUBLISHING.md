# Publishing Guide

This project ships as two packages on two registries under the same name:

| Registry | Package | What it contains | Install command |
|----------|---------|-----------------|----------------|
| **npm** | `video-research-mcp` | Installer — copies commands/skills/agents to `~/.claude/` | `npx video-research-mcp@latest` |
| **PyPI** | `video-research-mcp` | MCP server — runs via `uvx` | `uvx video-research-mcp` |

Both packages must always have the **same version number**.

## Version sync policy

`pyproject.toml` → `version` is the **source of truth**. Three files MUST be kept in lockstep:

1. Update `pyproject.toml` `version` (source of truth)
2. Update `package.json` `version` to match
3. Update `.claude-plugin/plugin.json` `version` to match
4. Verify all three:
   ```bash
   python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
   node -e "console.log(require('./package.json').version)"
   node -e "console.log(require('./.claude-plugin/plugin.json').version)"
   ```
   All three must return the same string. `.claude-plugin/plugin.json` was historically forgotten — keep it explicit.

## Pre-publish checklist

```bash
# Tests pass
uv run pytest tests/ -v

# Lint clean
uv run ruff check src/ tests/

# Versions match
python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
node -e "console.log(require('./package.json').version)"

# CHANGELOG.md updated with new version section

# Build succeeds
uv build
```

## Publishing to PyPI

```bash
# Build
uv build

# Verify package metadata
twine check dist/*

# Test on TestPyPI first (recommended)
twine upload --repository testpypi dist/*
uvx --index-url https://test.pypi.org/simple/ video-research-mcp --help

# Publish to production PyPI
twine upload dist/*
```

## Publishing to npm

```bash
# Dry-run to verify package contents
npm pack --dry-run

# Publish
npm publish
```

## Post-publish verification

```bash
# Verify PyPI install works
uvx video-research-mcp --help

# Verify npm install works
npx video-research-mcp@latest --check
```

## Git tagging

After both packages are published:

```bash
git tag v0.X.Y
git push origin v0.X.Y
```

Create a GitHub release from the tag with the CHANGELOG section as the body.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `twine check` fails | Ensure `pyproject.toml` has all required metadata (description, license, URLs) |
| TestPyPI install fails | Dependencies may not exist on TestPyPI — this is expected for integration deps |
| npm publish 403 | Run `npm login` first, verify package name isn't taken by another owner |
| Version mismatch after publish | Always bump both `pyproject.toml` and `package.json` before publishing |
| `uvx` picks old version | PyPI CDN can take a few minutes to propagate; retry after 5 minutes |
| Build fails | Run `uv pip install -e ".[dev]"` to ensure dev dependencies are current |
