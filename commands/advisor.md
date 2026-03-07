---
description: Get workflow advice — which /gr command best fits your task
argument-hint: <what you want to accomplish>
allowed-tools: mcp__video-research__knowledge_search, mcp__video-research__knowledge_stats, Read, Glob
model: sonnet
---

# Workflow Advisor: $ARGUMENTS

Last updated: 2026-03-07 12:34 CET

Recommend the optimal `/gr` command for this task. Do NOT execute anything.

## Step 1: Check Prior Work

Call `knowledge_search(query="$ARGUMENTS", limit=3)` to find existing research, video notes, or analyses.

If results are found, report:
```
PRIOR WORK FOUND: <count> results for "$ARGUMENTS"
Top match: <title> (<collection>, <date>)
SUGGESTION: Review existing work with /gr:recall "$ARGUMENTS" before starting new research
```

If `knowledge_search` fails (Weaviate not configured), skip this step silently.

## Step 2: Categorize Intent

Determine which category best fits "$ARGUMENTS":

| Category | Signals |
|----------|---------|
| **research** | topic, question, "how does X work", "what is X" |
| **video** | YouTube URL, "this video", "analyze video" |
| **content** | URL, file path, "this article", "this PDF" |
| **knowledge** | "find", "recall", "what did I research", "past work" |
| **system** | "setup", "config", "models", "traces", "doctor" |

## Step 3: Recommend

Use this quick-reference to select the right command:

| I want to... | Use | Cost |
|--------------|-----|------|
| Quick web lookup | `/gr:search` | free, instant |
| Deep topic research | `/gr:research` | free, instant |
| Thorough web-grounded research | `/gr:research-deep` | $2-5, 10-20 min |
| Research grounded in documents | `/gr:research-doc` | free, instant |
| Analyze a video | `/gr:video` | free, instant |
| Multi-turn video Q&A | `/gr:video-chat` | free, per-turn |
| Analyze a URL/file/text | `/gr:analyze` | free, instant |
| Find past work | `/gr:recall` | free, instant |
| Save to knowledge store | `/gr:ingest` | free, instant |
| Check setup | `/gr:doctor` | free, instant |
| View/change model preset | `/gr:models` | free, instant |
| Debug MLflow traces | `/gr:traces` | free, instant |
| First-time setup guide | `/gr:getting-started` | free, instant |

Present your recommendation in this format:

```
RECOMMENDED: /gr:<command> "<args>"
WHY: <one sentence>
ALTERNATIVE: /gr:<other>
COST: free|$2-5 | TIME: instant|10-20 min
NEXT STEP: <follow-up action>
```

## Step 4: Suggest Follow-up

- After research → suggest `/gr:ingest` to persist results
- Prior work found → suggest `/gr:recall` to review first
- Video analysis → suggest `/gr:video-chat` for follow-up questions
- Unsure about setup → suggest `/gr:doctor`
