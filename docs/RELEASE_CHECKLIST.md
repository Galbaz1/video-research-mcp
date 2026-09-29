# Release Checklist

Use the applicable publication stages for the authorized release. GitHub source releases, npm installer publication, and PyPI runtime publication are separate outcomes; record each explicitly.

## Pre-release

- [ ] Root tests pass: `uv run pytest tests/ -q`
- [ ] Both companion package test suites pass in their declared environments
- [ ] Installer tests pass: `node --test bin/__tests__/*.test.js`
- [ ] Lint clean: `uv run ruff check src/ tests/`
- [ ] Security smoke suite passes: `./scripts/run_security_smoke.sh`
- [ ] Live tool security checks pass (offline): `PYTHONPATH=src uv run python scripts/run_live_tool_security_checks.py`
- [ ] Tool inventory matches actual registrations: `uv run python scripts/export_tool_contract_manifest.py --output /tmp/video-research-tools.json`
- [ ] Packaged commands/skills/agents and references match `FILE_MAP`; `npm pack --dry-run` includes all required assets
- [ ] CHANGELOG.md has a section for the new version
- [ ] Version bumped in `pyproject.toml`
- [ ] Version bumped in `package.json` and `.claude-plugin/plugin.json` (must match pyproject.toml)
- [ ] `uv run python scripts/check_release.py` passes
- [ ] Both companion packages: locked tests, lint, and builds pass
- [ ] Installer journeys pass: `node --test tests/installer.test.js`
- [ ] Built core wheel completes stdio tool discovery and read-only configuration smoke
- [ ] `uv build` succeeds without errors

## Registry publish (only when authorized)

- [ ] `twine check dist/*` passes
- [ ] Upload to TestPyPI: `twine upload --repository testpypi dist/*`
- [ ] Verify TestPyPI install: `uvx --index-url https://test.pypi.org/simple/ video-research-mcp --help`
- [ ] Upload to PyPI: `twine upload dist/*`
- [ ] Publish to npm: `npm publish`

## Source release and post-publication verification

- [ ] Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`
- [ ] Create GitHub release from tag with CHANGELOG section as body
- [ ] Confirm the published PyPI version and connect that exact version through an MCP client; check `infra_configure()`
- [ ] Run a bounded provider smoke only when authorized, or mark live inference unverified
- [ ] Smoke test npm: `npx video-research-mcp@latest --check`
