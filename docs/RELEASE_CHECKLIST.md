# Release Checklist

Use this checklist on the final release source. Record its commit, versions,
artifact hashes, and intended destinations. GitHub, PyPI, and npm publication
have separate verified outcomes. Commands run from the repository root unless
a different directory is specified.

## Pre-release

- [ ] Scope is explicit: core, companions, installer, and intended registries.
- [ ] Root environment/tests pass: `uv sync --locked --extra dev`, then
  `uv run --locked pytest tests/ -q`.
- [ ] Root lint passes:
  `uv run --locked ruff check src/ tests/ scripts/check_release.py scripts/smoke_built_mcp.py`.
- [ ] In each companion directory, run `uv sync --locked --extra dev`,
  `uv run --locked pytest tests/ -q`, and `uv run --locked ruff check src/ tests/`.
- [ ] Installer journeys pass: `node --test tests/installer.test.js`.
- [ ] Native Codex package checks pass: `node --test tests/codex-plugin.test.js`.
- [ ] Complete packaged Claude workflows pass: `node --test tests/installer-packaged-skills.test.js`.
- [ ] Security smoke passes: `./scripts/run_security_smoke.sh`.
- [ ] Offline tool security checks pass:
  `PYTHONPATH=src uv run --locked python scripts/run_live_tool_security_checks.py`.
- [ ] Export actual core registrations with
  `uv run --locked python scripts/export_tool_contract_manifest.py --output /tmp/video-research-tools.json`
  and compare with the documented surface.
- [ ] Core versions match in `pyproject.toml`, `package.json`, and
  `.claude-plugin/plugin.json`, and `plugin.json`; `mcp.json` pins that exact runtime
  version and `CHANGELOG.md` has the matching release section.
- [ ] Companion versions match the releases being prepared.
- [ ] Release contract passes: `uv run --locked python scripts/check_release.py`.
- [ ] `npm pack --dry-run` includes mapped workflows and their referenced resources.
- [ ] Build approved packages into a fresh directory using
  [Publishing](PUBLISHING.md#pre-publish-checklist). Python metadata checks pass.
- [ ] The exact core wheel passes `scripts/smoke_built_mcp.py`: tool discovery and
  complete source tool contracts, read-only configuration and local image cropping
  work over stdio without provider requests.
- [ ] The exact npm archive installs from an isolated local Codex marketplace;
  installed bytes match and a fresh session loads skills and the exact candidate
  MCP runtime. Preserve unrelated configuration and verify removal.
- [ ] Archive hashes are recorded and no stale archive enters the release.

Hosted CI covers the root on Python 3.11–3.14 and both companions on 3.11 and 3.14.
Inspect its result for the exact release source. Hosted AI review is a separate
check; a green local suite does not establish that it ran.

## Registry publish (only when authorized)

- [ ] Registry ownership/authentication is verified without disclosing tokens.
- [ ] Optional TestPyPI staging is completed or explicitly omitted.
- [ ] Only approved Python archives are uploaded to PyPI.
- [ ] The exact npm archive is published with the intended dist-tag.
- [ ] Each version and archive identity is verified at its registry.
- [ ] Partial publication is recorded; retries use the same verified artifacts.

## Source release and post-publication verification

- [ ] The source tag points to the verified commit and matches the core version.
- [ ] The exact release workflow succeeds; notes, prerelease/latest status, and
  all approved assets/hashes are correct on the GitHub release.
- [ ] The exact registry core wheel passes stdio discovery/configuration smoke.
- [ ] Each published companion resolves and exposes its expected tools.
- [ ] The registry npm installer executes `--check`; isolated journeys cover
  install, upgrade, preservation, and uninstall behavior.
- [ ] Native Codex installation from the exact npm registry version passes fresh
  session skill/MCP discovery and a read-only configuration call. Record whether
  npm acquired fresh network bytes or reused an existing same-version cache;
  retain unknown acquisition when it cannot be distinguished.
- [ ] The client is restarted; active registration/version is inspected and
  `infra_configure()` is read without arguments.
- [ ] Authorized live provider smoke is recorded, or live inference remains
  explicitly unverified.

Retain failed gates and unresolved stages in the release record. Claim completion
only for destinations whose final artifacts and runtime checks are verified.
See [Publishing](PUBLISHING.md) for commands and recovery guidance.
