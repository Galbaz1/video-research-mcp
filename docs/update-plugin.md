# Updating the Plugin

An upgrade has two parts: npm updates Claude Code workflows and registration;
PyPI supplies the research runtime launched by that registration. Verify both
before treating the upgrade as active.

## User upgrade

1. Inspect the installation:

   ```sh
   npx video-research-mcp@latest --check
   ```

2. Back up custom workflows, the client configuration, and the ownership manifest.
   Upgrade the scope you use:

   ```sh
   npx video-research-mcp@latest --global
   # Or, from the project root:
   npx video-research-mcp@latest --local
   ```

3. Read the result. Ordinary upgrades preserve modified workflows and differing
   files without matching ownership evidence. Review skipped files before using
   `--force`: it replaces those files and may delete modified obsolete files.
   The shared `.env` retains existing values.
4. Inspect registration. The installer refreshes managed server commands and
   arguments while retaining custom environment and other fields. A malformed
   configuration may have produced a warning even when files installed.
5. Restart the MCP client. Confirm the active package version and call
   `infra_configure()` without arguments to inspect models/settings.
   `/gr:doctor quick` helps diagnose configuration and optional integrations.

The manifest reports workflow installation; `infra_configure()` reports runtime
configuration. Neither proves a live inference succeeded. Use a small authorized
analysis for that separate check and inspect its returned evidence.

Keep credentials in the process environment or
`~/.config/video-research-mcp/.env`, and omit their values from diagnostics.
Selected content is processed by configured providers. Companion servers and
the external renderer need separate upgrades; see the
[explainer](../packages/video-explainer-mcp/README.md) and
[scene-agent](../packages/video-agent-mcp/README.md) guides.

For rollback, restore backed-up custom workflows and pin the runtime registration
to the previously verified version. Recheck registration after an installer run,
because it replaces managed commands and arguments.

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
