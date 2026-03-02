# Release Checklist

Copy this checklist into a GitHub issue or PR for each release.

## Pre-release

- [ ] All tests pass: `uv run pytest tests/ -v`
- [ ] Lint clean: `uv run ruff check src/ tests/`
- [ ] Security smoke suite passes: `./scripts/run_security_smoke.sh`
- [ ] Live tool security checks pass (offline): `PYTHONPATH=src uv run python scripts/run_live_tool_security_checks.py`
- [ ] Tool count in docs matches `grep -c "@server.tool" src/video_research_mcp/tools/*.py src/video_research_mcp/tools/knowledge/*.py`
- [ ] CHANGELOG.md has a section for the new version
- [ ] Version bumped in `pyproject.toml`
- [ ] Version bumped in `package.json` (must match pyproject.toml)
- [ ] `uv build` succeeds without errors

## Publish

- [ ] `twine check dist/*` passes
- [ ] Upload to TestPyPI: `twine upload --repository testpypi dist/*`
- [ ] Verify TestPyPI install: `uvx --index-url https://test.pypi.org/simple/ video-research-mcp --help`
- [ ] Upload to PyPI: `twine upload dist/*`
- [ ] Publish to npm: `npm publish`

## Post-publish

- [ ] Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] Create GitHub release from tag with CHANGELOG section as body
- [ ] Smoke test PyPI: `uvx video-research-mcp --help`
- [ ] Smoke test npm: `npx video-research-mcp@latest --check`
