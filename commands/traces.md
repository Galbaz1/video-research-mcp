---
description: Query, debug, and evaluate MLflow traces from Gemini tool calls
argument-hint: "[errors|slow|<trace-id>|feedback <trace-id> <score>]"
allowed-tools: mcp__mlflow-mcp__search_traces, mcp__mlflow-mcp__get_trace, mcp__mlflow-mcp__set_trace_tag, mcp__mlflow-mcp__log_feedback, mcp__mlflow-mcp__evaluate_traces, mcp__mlflow-mcp__list_scorers, Bash
---

# Traces: $ARGUMENTS

Query and debug MLflow traces captured from video-research-mcp Gemini API calls.

## Prerequisites

The MLflow tracking server must be running. If tools are unavailable or connection is refused:
```
MLFLOW_TRACKING_URI=http://127.0.0.1:5001 mlflow server --port 5001
```
Then restart Claude Code to reconnect the `mlflow-mcp` MCP server.

## Default Experiment

Use experiment name `video-research-mcp` unless the user specifies otherwise. Resolve the experiment ID by searching with that name first.

## Context Discipline (mandatory)

- **Always use `extract_fields`** — never pull full traces. Gemini traces contain large payloads (video URIs, cached content, full prompts/responses).
- Keep output compact: target <= 300 tokens for overview, expand on detail requests.
- Never print raw JSON blobs or full span attributes.

## Argument Routing

### No arguments (empty `$ARGUMENTS`)

Show a recent traces overview:

```javascript
search_traces({
  experiment_id: "<resolved>",
  max_results: 10,
  extract_fields: "info.trace_id,info.state,info.execution_duration_ms,info.request_time,info.request_preview"
})
```

Present as a compact table: trace ID (short), status, duration, time, and request preview.

### `errors`

Filter for failed traces:

```javascript
search_traces({
  experiment_id: "<resolved>",
  filter_string: "status='ERROR'",
  max_results: 20,
  extract_fields: "info.trace_id,info.state,info.execution_duration_ms,info.request_time,info.request_preview"
})
```

### `slow`

Filter for traces over 5 seconds:

```javascript
search_traces({
  experiment_id: "<resolved>",
  filter_string: "execution_time_ms > 5000",
  max_results: 20,
  extract_fields: "info.trace_id,info.execution_duration_ms,info.request_time,info.request_preview,data.spans.*.name"
})
```

### Trace ID (starts with `tr-` or is a hex string)

Get trace detail:

```javascript
get_trace({
  trace_id: "<id>",
  extract_fields: "info.*,data.spans.*.name,data.spans.*.status_code,data.spans.*.start_time_unix_nano,data.spans.*.end_time_unix_nano"
})
```

Present span tree with timing. **Never** request `data.spans.*.attributes` unqualified.

### `feedback <trace-id> <score>`

Log human feedback (score 1-5):

```javascript
log_feedback({
  trace_id: "<id>",
  name: "response_quality",
  value: <score>,
  source_type: "human",
  rationale: "Logged via /gr:traces"
})
```

Confirm with the trace ID and score logged.

## Field Name Gotcha

`filter_string` and `extract_fields` use **different** names for the same data:

| Data | `filter_string` | `extract_fields` |
|------|-----------------|-------------------|
| Status | `status = 'ERROR'` | `info.state` |
| Duration | `execution_time_ms > 5000` | `info.execution_duration_ms` |
| Timestamp | `timestamp_ms > ...` | `info.request_time` |

## Output Format

- Overview: compact table with short trace IDs
- Detail: span tree with timing breakdown
- Always show trace count and time range
- Suggest next actions: "Use `/gr:traces <trace-id>` for detail" or "Use `/gr:traces feedback <id> <score>` to log feedback"
