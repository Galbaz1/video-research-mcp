# Updating the Plugin

This guide selects core `0.8.0-rc.5` (Python `0.8.0rc5`). Pin the intended version:
`@latest` selects the stable npm channel, not this prerelease. Plugin assets and
the Python runtime have separate installation checks. Check PyPI and npm
availability for this RC5 candidate before using the pinned commands below:

```sh
npm view video-research-mcp@0.8.0-rc.5 version
```

If npm RC5 is unavailable, keep the existing plugin installation or use the
[server-only Python route](tutorials/GETTING_STARTED.md#other-mcp-clients).

## Codex native plugin

Back up edits and unowned files outside the managed plugin cache. Update the
marketplace's npm version, then repeat `codex plugin add` for that catalog entry.
Codex replaces managed cache contents, including same-version local edits.
Follow the [native plugin guide](PLUGIN_DISTRIBUTION.md#native-codex-plugin) for
portable catalog examples and migration from a manual server entry.

Start a fresh session, inspect the enabled plugin and runtime version, and call
`infra_configure()` without arguments. Record fresh network acquisition separately
from reuse of an existing same-version cache. Neither proves provider quality.

<a id="user-upgrade"></a>

## Claude Code workflows

1. Inspect the scope you use:

   ```sh
   npx video-research-mcp@0.8.0-rc.5 --global --check
   # Or, from the project root:
   npx video-research-mcp@0.8.0-rc.5 --local --check
   ```

2. Back up custom workflows, client configuration, and the ownership manifest.
   Upgrade that scope:

   ```sh
   npx video-research-mcp@0.8.0-rc.5 --global
   # Or, from the project root:
   npx video-research-mcp@0.8.0-rc.5 --local
   ```

3. Inspect skipped files. Ordinary upgrades preserve modified or unowned workflows.
   `--force` can replace them and delete modified obsolete files. The selected
   credential template retains existing values.
4. Inspect registration. Only unchanged, installer-owned entries are updated;
   customized and unmanaged entries remain. Malformed configuration stops
   installation before writes; repair it before rerunning.
5. Restart Claude Code, inspect the active runtime version and call
   `infra_configure()` without arguments. `/gr:doctor quick` checks setup and
   optional integrations.

Keep credentials in the process environment or the selected user/project `.env`,
and omit values from diagnostics. Analysis sends content to configured providers.
The [explainer](../packages/video-explainer-mcp/README.md),
[scene-agent](../packages/video-agent-mcp/README.md) and external renderer require
separate upgrades. Later source fixes do not change already published archives.

For rollback, restore backed-up workflows and pin the runtime to the previously
verified version. Recheck the registration after any installer run.

## Maintainer verification

Use [Publishing](PUBLISHING.md) and the [Release Checklist](RELEASE_CHECKLIST.md).
Verify final source, locked environments, mocked tests, lint, installer journeys,
packaged resources, registrations, and built archives. Source and registry
publication remain separate outcomes.

For a model update, verify the official ID, lifecycle, thinking/sampling
constraints, and required features before editing `ServerConfig`. Update affected
examples and mock assertions for the actual API request. Configuration changes
and unit tests establish local behavior; record omitted provider smoke explicitly.

See [Distribution](PLUGIN_DISTRIBUTION.md) for paths and preservation behavior.
Keep proposed work in the project tracker; this page describes the upgrade
procedure users can perform now.
