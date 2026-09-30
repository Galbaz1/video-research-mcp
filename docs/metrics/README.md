# Metrics Artifacts

These JSON files capture the tool contract and installer scenario inventory at
the time they were generated. They help compare changes, but neither file proves
that a provider request, installation or user journey passed.

| Artifact | What it records | Evidence limit |
| --- | --- | --- |
| [tool-contract-manifest.json](tool-contract-manifest.json) | Mounted root tool names, descriptions, parameter/output schemas and annotations | Static discovery from the imported server; no tool execution |
| [installer-state-matrix.json](installer-state-matrix.json) | Scenario descriptions and expected outcomes, plus source-file and destination integrity checks for `FILE_MAP` | Scenarios are inventory, not executed tests; integrity checks cover existence and duplicate destinations |

Each artifact includes `generated_at`. The September 29, 2026 snapshots contain
34 root tools and 22 installer scenarios with 44 mapped files. These counts
belong to those snapshots; use current generation or actual test output when
assessing a later revision. Some scenario descriptions retain earlier installer
assumptions, so compare them with the implementation before treating them as
requirements.

## Regeneration

Run from the repository root using the locked development environment:

```bash
PYTHONPATH=src uv run --locked python scripts/export_tool_contract_manifest.py
uv run --locked python scripts/export_installer_state_matrix.py
```

Both commands overwrite their default artifact paths. Use `--output` to write
an inspection copy elsewhere, for example:

```bash
PYTHONPATH=src uv run --locked python scripts/export_tool_contract_manifest.py --output /tmp/tool-contract-manifest.json
uv run --locked python scripts/export_installer_state_matrix.py --output /tmp/installer-state-matrix.json
```

The tool exporter imports the MCP server and lists tools without invoking them.
The installer exporter reads `FILE_MAP` through Node.js, checks its source files
and destination uniqueness, and writes the declared scenario list. It does not
run install, upgrade or uninstall operations.

For executed installer evidence, run `node --test tests/installer.test.js`.
For broader artifact acceptance, follow the [release checklist](../RELEASE_CHECKLIST.md)
and keep receipts tied to the tested revision. The
[modernization audit](../audits/2026-09-modernization.md) records the dated
September acceptance results.
