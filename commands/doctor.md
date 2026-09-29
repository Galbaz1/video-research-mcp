---
description: Diagnose /gr plugin setup, active MCP wiring, and optional integrations
argument-hint: "[quick|full]"
allowed-tools: mcp__video-research__infra_configure, mcp__video-research__video_metadata, mcp__video-research__knowledge_stats, mcp__mlflow-mcp__search_traces, Glob, Read, Bash
---

# Doctor: $ARGUMENTS

Default to `quick`; use `full` for installed-file and manifest drift. Keep quick output compact. Never print credentials, raw environment/config files, tool payloads, or stack traces.

## 1. Active Registration

Inspect the client's active `/mcp` state first. Claude Code user registrations live in `~/.claude.json`; project registrations live in `./.mcp.json`. A file's presence alone does not prove which server/process is active. Use `claude mcp list` when available; retain config paths as candidates when runtime state cannot be inspected.

Check the shared `~/.config/video-research-mcp/.env` and process environment using a script that outputs only booleans for non-empty `GEMINI_API_KEY`, `YOUTUBE_API_KEY`, and `WEAVIATE_URL`. Parse values locally; do not read or print the entire file into model context. Determine command/args and whether a server `env` block exists without emitting its values. Environment substitutions are supported client features; validate resolution rather than recommending deletion of every placeholder.

Completion: active registration identified, or uncertainty stated with the exact client check needed.

## 2. Runtime Settings

Call `infra_configure()` without arguments. Report model IDs, thinking level, and whether optional integrations are enabled. This proves the MCP process responds; it does not prove inference or provider access. Do not mutate presets during diagnostics.

Completion: current runtime settings returned or the error category/hint recorded.

## 3. Independent Integration Checks

Call only tools actually available in the session. Omit optional checks when disabled:

- YouTube: `video_metadata(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")`. Pass requires a non-empty `video_id` and no `error`. A Gemini key fallback does not prove that YouTube Data API is enabled.
- Weaviate: `knowledge_stats()`. Disabled is informational; a configured connection failure is a failed integration.
- MLflow: `search_traces(experiment_id="0", max_results=1, extract_fields="info.trace_id")`. A missing experiment differs from connection failure; use the configured experiment if discoverable. MLflow is optional.

Provider inference is a separate authorized smoke. Do not silently send user documents or start paid research to turn an MCP connection check into an inference claim. Changes to shared environment require an MCP restart before retesting. After one controlled fix, retry only the failed check; preserve repeated failures.

Completion: each enabled integration has an observed result, with unavailable/disabled distinguished from failure.

## 4. Full Mode

Inspect the installed `comment-analyst.md` and file manifest in the install scope. Confirm the YouTube comments tool is in `tools:` and compare the installed SHA-256 against its manifest entry. Report user modifications before suggesting `--force`; the installer deliberately preserves them. Do not edit config or overwrite skills during a diagnostic request.

## Output

Return overall `PASS`, `PASS with optional limitations`, or `FAIL`; compact check results; exact fixes for failed checks; and the smallest retest. Distinguish configuration, MCP connection, provider metadata access, and inference. Do not call the whole setup healthy when an enabled integration failed, and do not call optional absence a core failure.
