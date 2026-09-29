# Updating the Plugin

The npm package installs workflow files and MCP configuration. The PyPI package supplies the running research server. Updating one does not prove the other is active.

## User upgrade

```bash
npx video-research-mcp@latest --check
npx video-research-mcp@latest
```

The installer preserves modified workflow files. Review the reported conflicts before using `--force`, which replaces those files. Restart the MCP client after upgrading, inspect its active server registration, and call `infra_configure()` without arguments to confirm the active models. `/gr:doctor quick` checks configuration and available optional integrations; inference is verified separately with a bounded, authorized analysis.

Credentials belong in the shared local configuration or process environment. Never include their values in diagnostics. Uploaded media and prompts are processed by configured providers; the local configuration file is not an offline-processing guarantee.

## Maintainer verification

Use the repository's release workflow and [release checklist](RELEASE_CHECKLIST.md). Verify the owned diff, dependency resolution, mocked Python tests, lint, installer tests, packaged file inventory, and tool contract manifest before publishing. Compare the manifest with registered tools; do not copy a historical tool count into new docs.

For a model update, verify the official model ID, lifecycle, thinking/sampling constraints, and feature compatibility before editing `ServerConfig`. Update matching examples and assert the API request shape with mocks. A changed model string or green unit tests prove local behavior only; label any omitted live provider smoke explicitly.

See [distribution](PLUGIN_DISTRIBUTION.md) for installed asset paths and [publishing](PUBLISHING.md) for registry/version coordination. Historical plans belong in dated audit evidence or the project tracker, not in this upgrade procedure.
