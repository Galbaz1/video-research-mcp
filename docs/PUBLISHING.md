# Publishing Guide

Publish the archives built from the verified release source, then verify each
destination separately. A GitHub source release, a PyPI upload, and an npm upload
are distinct outcomes. The release workflow creates GitHub releases; it does not
upload to PyPI or npm.

| Destination | Package | Contents |
| --- | --- | --- |
| npm | `video-research-mcp` | Claude Code installer, commands, skills, agents |
| PyPI | `video-research-mcp` | Research MCP runtime |
| PyPI | `video-explainer-mcp` | Wrapper for a separately installed upstream renderer |
| PyPI | `video-agent-mcp` | Claude Agent SDK scene generator |
| GitHub Releases | Tagged source release | Python wheels/sdists and npm installer archive |

Publishing requires explicit release authority and authenticated access to the
chosen destinations. Supply credentials through the environment or credential
store; keep tokens out of commands, notes, and logs. Identify the exact source
commit, versions, and destinations before building.

The explainer wrapper's installed `explainer_doctor` inspects the separately
configured renderer without installing dependencies or downloading a browser.
Archive/install tests must preserve the shared bounded media-process implementation.
Rendered MP4 qualification binds the exact current-request path, dimensions,
duration, SHA256 and full decode; it does not clear upstream/Remotion grants or
establish actual renderer/TTS provenance. Keep real renderer qualification separate
from an authored FFmpeg fixture and mocked controller tests. See
[renderer readiness](integrations/render-readiness.md) for the supported route.

## Version sync policy

The root [`pyproject.toml`](../pyproject.toml) is the core version authority.
Keep it identical to [`package.json`](../package.json) and
[`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json). Add a matching
section to [CHANGELOG.md](../CHANGELOG.md).

Companions have independent versions in their own `pyproject.toml` files. Check
core version agreement and installer mappings with:

```sh
uv run --locked python scripts/check_release.py
```

This verifies the core manifests, changelog heading, mapped source files, and
unique destinations. It does not verify registry state or replace tests/builds.

## Pre-publish checklist

Complete the [Release Checklist](RELEASE_CHECKLIST.md) on the final release
source. It covers locked environments, mocked tests, lint, isolated installer
journeys, offline security checks, tool discovery, and package contents.

Build into a fresh directory to exclude stale archives. Run these commands from
the repository root in one shell session:

```sh
release_dir="$(mktemp -d)"
uv build --out-dir "$release_dir"
uv build --project packages/video-explainer-mcp --out-dir "$release_dir"
uv build --project packages/video-agent-mcp --out-dir "$release_dir"
npm pack --pack-destination "$release_dir"
uvx --from twine twine check "$release_dir"/*.whl "$release_dir"/*.tar.gz
uv run --locked python scripts/smoke_built_mcp.py "$release_dir"/video_research_mcp-*.whl
```

Expect one wheel and one sdist per Python package, plus one npm `.tgz`.
The core wheel smoke discovers tools and reads configuration over stdio with a
dummy key; it sends no provider requests. Record archive hashes with the source
commit and package versions.

When publishing existing GitHub assets, download and verify those exact assets
instead of rebuilding changed source under the same version. Later source edits
are not part of an already published archive.

## GitHub source releases

The [release workflow](../.github/workflows/release.yml) runs reusable CI before
building assets. Its tag must match the core version and have matching changelog
notes. A tagged commit outside the ancestry of `origin/main` becomes a prerelease
and is not marked latest.

After reviewed source is committed and the branch is published under repository
policy, tag that exact verified commit. Replace `vX.Y.Z` and
`VERIFIED_COMMIT_SHA` with the approved version and full commit hash:

```sh
git tag vX.Y.Z VERIFIED_COMMIT_SHA
git push origin vX.Y.Z
```

Inspect the exact workflow run, tag target, release page, prerelease status, and
asset hashes. A tag push or running workflow is not a completed release. If
creation fails, preserve the failure and repair its cause. Manual recovery must
retain matching notes, assets, source identity, and prerelease status.

## Publishing to PyPI

An authorized TestPyPI upload can provide an optional staging check. TestPyPI may
lack dependency versions; resolution failure there does not itself prove a
packaging failure. A second package index changes dependency provenance and
should be selected deliberately.

Upload the verified Python archives:

```sh
uvx --from twine twine upload "$release_dir"/*.whl "$release_dir"/*.tar.gz
```

This uploads all three packages. For a narrower release, pass only the exact
approved wheel and sdist paths. Published version files cannot be replaced with
new content; corrections require a new version.

## Publishing to npm

Check package contents and authenticated ownership, then publish the verified
archive instead of repacking the current working tree:

```sh
npm publish "$release_dir"/video-research-mcp-*.tgz
```

Select a dist-tag explicitly if this version should not become `latest`. A GitHub
prerelease flag does not control npm tags or PyPI version semantics.

## Post-publish verification

Confirm the version and archive identity at each registry. For the core, also
verify the exact registry wheel through MCP. The console script starts a stdio
server; `--help` is not its runtime acceptance check.

Replace `X.Y.Z` with the published core version:

```sh
registry_dir="$(mktemp -d)"
uvx --from pip pip download --no-deps --only-binary=:all: \
  --dest "$registry_dir" "video-research-mcp==X.Y.Z"
uv run --locked python scripts/smoke_built_mcp.py "$registry_dir"/video_research_mcp-*.whl
npm view video-research-mcp@X.Y.Z version dist.integrity
npm view video-research-mcp dist-tags
npx --yes video-research-mcp@X.Y.Z --check
```

Compare the downloaded wheel's hash with the upload. `--check` confirms that the
registry installer executes and reports local state; isolated installer tests
cover file/configuration changes. Confirm expected tool discovery for each
published companion separately.

Restart the user's client, inspect the active runtime registration and package
version, and call `infra_configure()` without arguments. Record active settings
separately from the installed package version. Run a bounded provider smoke only
when authorized; otherwise report live inference as unverified. Builds and stdio
checks do not demonstrate provider authentication or result quality.

## Git tagging

The tag identifies the source release and may precede registry uploads. Do not
move it to include later edits. Publish its verified archives, or use a new
version and tag for changed content.

## Troubleshooting

| Problem | Next step |
| --- | --- |
| Version contract fails | Align core manifests and changelog before rebuilding. |
| Metadata check fails | Fix the owning `pyproject.toml`, rebuild, and recheck. |
| npm returns 403 | Verify login, ownership, and required registry authentication. |
| An old version resolves | Query the exact version/dist-tag, inspect registration, and restart the client. |
| One upload succeeds and another fails | Record completed destinations and hashes; retry only missing uploads with the same archives. |
| A published package needs correction | Release a new version; pin clients to a known working release while it is prepared. |

For client rollback, restore backed-up workflows and pin the runtime registration
to the known working package version. Installer upgrades replace managed server
commands and arguments, so recheck runtime pins afterward. Registry yanks,
deprecations, and dist-tag changes require their own publication authority.
