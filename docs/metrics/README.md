# Metrics Artifacts

This directory stores baseline evidence artifacts for the plugin optimization program.

## Files

- `tool-contract-manifest.json`: Snapshot of mounted MCP tools, parameter schemas, output schemas, and annotations.
- `installer-state-matrix.json`: Installer scenario matrix plus `FILE_MAP` integrity checks.

## Regeneration

```bash
PYTHONPATH=src uv run python scripts/export_tool_contract_manifest.py
uv run python scripts/export_installer_state_matrix.py
```
