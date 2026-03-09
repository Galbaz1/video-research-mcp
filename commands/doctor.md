---
description: Diagnose /gr plugin setup, MCP wiring, and API connectivity
argument-hint: "[quick|full]"
allowed-tools: mcp__video-research__infra_configure, mcp__video-research__video_metadata, mcp__video-research__knowledge_stats, mcp__mlflow-mcp__search_traces, Glob, Read, Bash
model: sonnet
---

# Doctor: $ARGUMENTS

Run a deterministic health check for the video-research plugin and MCP server.

## Mode

- Default mode is `quick`.
- If `$ARGUMENTS` contains `full`, run extra checks for agent/manifest drift.

## Context Discipline (mandatory)

- Keep `quick` mode output compact: target <= 220 tokens.
- Never print raw tool payloads, JSON blobs, full file contents, or stack traces.
- Never run broad repository searches. Only inspect exact paths listed below.
- Extract only the required keys from config/env files.
- If you need details, include one short line: `Run /gr:doctor full for deep diagnostics`.

## Tool discipline (mandatory)

Only use the tools listed in `allowed-tools`. In particular:
- **File reading**: use `Read` (Claude Code built-in), never `plugin:serena:serena - Read File` or any other MCP file-reading tool.
- **File search**: use `Glob` (Claude Code built-in), never Serena's `find_file` or `list_dir`.
- **Shell**: use `Bash` (Claude Code built-in), never Serena's `execute_shell_command`.

## 1) Discover active config

Use `Glob` + `Read` to inspect:
- `./.mcp.json`
- `~/.claude/.mcp.json`
- `~/.config/video-research-mcp/.env`
- `./.env` (optional)

Determine active server config:
- If `./.mcp.json` has `mcpServers.video-research`, treat it as active.
- Otherwise use `~/.claude/.mcp.json`.

Capture and report:
- Active config path
- `video-research` command + args
- Whether an `env` block exists under `mcpServers.video-research`
- Whether shared config file exists and contains:
  - `GEMINI_API_KEY`
  - `YOUTUBE_API_KEY` (optional)
  - `WEAVIATE_URL` (optional)

If the active `.mcp.json` contains unresolved placeholders (for example `${WEAVIATE_URL}`), flag it as a warning and recommend removing the `env` block in favor of `~/.config/video-research-mcp/.env`.

## 2) Runtime config check

Call `infra_configure()` with no arguments to inspect live server settings.
Never pass `preset` unless it is exactly one of: `best`, `stable`, `budget`.
Do not call `infra_configure(preset="")`.

Report:
- `current_config.default_model`
- `current_config.youtube_api_key` present/empty
- `current_config.weaviate_url` (masked if needed)
- `current_config.weaviate_enabled`

Interpretation rules for YouTube key status:
- If `youtube_api_key` is present: PASS.
- If `youtube_api_key` is empty but `GEMINI_API_KEY` exists in shared config/env: INFO only (fallback path is active).
- Warn only when both keys appear missing.

If runtime `weaviate_url` is non-empty and does not start with `http://` or `https://`, mark as fail and provide exact fix.

## 3) Smoke tests

### YouTube API

Call:
`video_metadata(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")`

- PASS: non-empty `video_id` and no `error`
- FAIL: has `error` (show `category`, `hint`, and concrete fix)

### Weaviate

Call:
`knowledge_stats()`

- PASS: response has `collections`
- WARN: error indicates not configured/disabled
- FAIL: connection or validation error

For failures, include exact remediation text (URL format, API key, restart requirement).
If any env file values are changed (for example `~/.config/video-research-mcp/.env`), explicitly require a Claude Code restart before retest.

### MLflow Tracing

Call:
`search_traces(experiment_id="0", max_results=1, extract_fields="info.trace_id")`

Use the `mcp__mlflow-mcp__search_traces` tool.

- PASS: returns a result (MLflow MCP server connected)
- WARN: connection refused or timeout (MLflow server not running — `mlflow server --port 5001`)
- INFO: tool not available (mlflow-mcp not installed — run the plugin installer)

Do not fail the overall health check for MLflow issues — it is an optional component.

## 4) Full mode extras

If mode is `full`, also:

1. Inspect comment-analyst definitions (project first, then global):
   - `./.claude/agents/comment-analyst.md`
   - `~/.claude/agents/comment-analyst.md`
2. Verify `tools:` includes `mcp__video-research__video_comments`.
3. If `~/.claude/gr-file-manifest.json` exists, compare manifest hash for `agents/comment-analyst.md` against current file hash using:
   `shasum -a 256 ~/.claude/agents/comment-analyst.md`
4. If mismatched, warn that installer upgrades may skip this file unless user runs with `--force`.

## Output format (strict)

For `quick` mode, produce exactly 4 short sections:

1. `Summary`: `PASS`, `PASS with warnings`, or `FAIL`
2. `Checks` (no table; 6 bullets only):
   - Active MCP config
   - Shared env file
   - Runtime config
   - YouTube API smoke test
   - Weaviate smoke test
   - MLflow tracing smoke test
3. `Fixes`:
   - If none: `None`
   - If needed: numbered command-ready steps (max 3)
4. `Retest`: one line with `/gr:doctor` and any failing smoke test command

For `full` mode, include:
- Full checks table
- Comment-agent wiring row
- Expanded remediation details

Never claim healthy if any smoke test failed.
