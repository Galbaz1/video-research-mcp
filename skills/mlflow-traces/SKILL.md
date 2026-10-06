---
name: mlflow-traces
description: "Use when working with MLflow traces: debugging via MCP tools, analyzing performance, logging feedback, writing custom scorers/evaluations, or cleaning up trace data"
---

# MLflow Trace Management — video-research-mcp

## Overview

Query, tag, evaluate, and manage MLflow traces captured from video-research-mcp Gemini API calls. Uses `mcp__mlflow-mcp__*` MCP tools — no code writing needed for most operations.

**Core principle:** Search first, then act. Always verify before destructive operations.

## Quick Reference

| Task | Tool | Key Params |
|------|------|------------|
| Find traces | `search_traces` | `experiment_id`, `filter_string`, `extract_fields` |
| Get details | `get_trace` | `trace_id`, `extract_fields` |
| Tag trace | `set_trace_tag` | `trace_id`, `key`, `value` |
| Log score | `log_feedback` | `trace_id`, `name`, `value`, `rationale` |
| Run scorers | `evaluate_traces` | `experiment_id`, `trace_ids`, `scorers` |
| List scorers | `list_scorers` | — |

## Canonical Field Paths

**CRITICAL — only use fields that actually exist:**

| Path | Content | Common mistake |
|------|---------|----------------|
| `info.trace_id` | Trace identifier | — |
| `info.state` | Status: OK, ERROR | **NOT** `info.status` |
| `info.request_time` | Timestamp | **NOT** `info.timestamp_ms` |
| `info.execution_duration_ms` | Duration in ms | **NOT** `info.execution_duration` |
| `info.request_preview` | First ~100 chars of request | — |
| `info.response_preview` | First ~100 chars of response | — |
| `info.tags` | All tags as object | Use `info.tags.*` for all |
| `data.spans.*.name` | Span names | Must include `data.` prefix |
| `data.spans.*.status_code` | Span status | **NOT** `data.spans.*.status` |
| `data.spans.*.inputs` | Span inputs | Moderate size |
| `data.spans.*.outputs` | Span outputs | Moderate size |

## extract_fields Discipline

**Always use `extract_fields`.** Video-research-mcp traces contain video URIs, cached content references, full Gemini prompts/responses. A single `get_trace` without `extract_fields` can flood your context window.

```javascript
// BAD - pulls everything
get_trace({ trace_id: "tr-..." })
search_traces({ experiment_id: "2" })

// GOOD - selective fields
get_trace({ trace_id: "tr-...",
  extract_fields: "info.*,data.spans.*.name,data.spans.*.status_code" })
search_traces({ experiment_id: "2", max_results: 10,
  extract_fields: "info.trace_id,info.state,info.execution_duration_ms" })
```

**Never** request `data.spans.*.attributes` unqualified — it silently drops dotted keys and can contain massive payloads.

## Filter String vs Extract Fields — DIFFERENT NAMING!

**CRITICAL**: `filter_string` and `extract_fields` use DIFFERENT field names:

| Data | `filter_string` syntax | `extract_fields` syntax |
|------|----------------------|------------------------|
| Status | `status = 'ERROR'` | `info.state` |
| Timestamp | `timestamp_ms > 170000...` | `info.request_time` |
| Duration | `execution_time_ms > 5000` | `info.execution_duration_ms` |
| Tags | `tags.reviewed = 'true'` | `info.tags.*` |

## Common Workflows

### Debug failed traces

```javascript
search_traces({ experiment_id: "<id>", filter_string: "status='ERROR'", max_results: 20,
  extract_fields: "info.trace_id,info.state,info.execution_duration_ms,info.request_preview" })

get_trace({ trace_id: "tr-abc123",
  extract_fields: "info.*,data.spans.*.name,data.spans.*.status_code" })

set_trace_tag({ trace_id: "tr-abc123", key: "needs_investigation", value: "true" })
```

### Find slow traces

```javascript
search_traces({ experiment_id: "<id>", filter_string: "execution_time_ms > 5000",
  max_results: 20, extract_fields: "info.trace_id,info.execution_duration_ms,data.spans.*.name" })
```

### Log human feedback

```javascript
log_feedback({ trace_id: "tr-abc123", name: "response_quality", value: 4.5,
  source_type: "human", rationale: "Accurate analysis, good structure" })
```

### Run built-in scorers

```javascript
// List available scorers first
list_scorers()

// Run evaluation
evaluate_traces({ experiment_id: "<id>", trace_ids: "tr-abc,tr-def",
  scorers: "Correctness,RelevanceToQuery" })
```

### Search before delete

```javascript
// Step 1: Preview
search_traces({ experiment_id: "<id>", filter_string: "timestamp_ms < 1704067200000",
  max_results: 10, extract_fields: "info.trace_id,info.request_time" })

// Step 2: Verify count and IDs, then delete
delete_traces({ experiment_id: "<id>", max_timestamp_millis: 1704067200000 })
```

## Field Selection Recipes

```javascript
"info.trace_id,info.state"                                    // Minimal overview
"info.trace_id,info.execution_duration_ms,data.spans.*.name"  // Performance
"info.*,data.spans.*.name,data.spans.*.status_code"           // Full context (safe)
"info.trace_id,info.tags.*"                                   // Tags only
"info.trace_id,info.assessments.*.feedback.value"             // Feedback scores
```

## video-research-mcp Context

| Setting | Value |
|---------|-------|
| Tracking server | Operator-selected URI; `http://127.0.0.1:5001` is a loopback example |
| Experiment name | `video-research-mcp` |
| Env var | `MLFLOW_TRACKING_URI` |
| Autolog captures | All `GeminiClient` generate/generate_structured calls |
| Trace spans | Gemini API calls with model, thinking level, tokens, cost |

Tracing requires the installed tracing extra and a reachable `MLFLOW_TRACKING_URI`. `GEMINI_TRACING_ENABLED=false` disables it even with a URI. When enabled, `mlflow.gemini.autolog()` captures SDK calls; inspect actual retained traces before claiming coverage.

## Troubleshooting

### MCP tools not available / connection refused

The MLflow tracking server must be running:
```bash
MLFLOW_TRACKING_URI=http://127.0.0.1:5001 mlflow server --port 5001
```
Then restart Claude Code to reconnect.

### No traces found

1. Check `MLFLOW_TRACKING_URI` is set in the server environment
2. Verify the experiment name: search with `max_results: 1` across experiment IDs
3. Use a separately authorized inference call if needed, then search its retained trace; do not send user material solely for diagnostics without authority

### Wrong experiment

The default experiment is `video-research-mcp`. If traces land in `Default` (experiment 0), the `MLFLOW_EXPERIMENT_NAME` env var is not set.

## Resources

- [MLflow MCP Docs](https://mlflow.org/docs/latest/genai/mcp/)
- [MLflow Tracing](https://mlflow.org/docs/latest/llms/tracing/index.html)
- [Filter Syntax](https://mlflow.org/docs/latest/search-runs.html)
