---
description: Get workflow advice — which /gr command best fits your task
argument-hint: <what you want to accomplish>
allowed-tools: mcp__video-research__knowledge_search, mcp__video-research__knowledge_stats, Read, Glob
---

# Workflow Advisor: $ARGUMENTS

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
| Quick web lookup | `/gr:search` | provider billing applies |
| Deep topic research | `/gr:research` | provider billing applies |
| Thorough web-grounded research | `/gr:research-deep` | long-running; provider billing |
| Research grounded in documents | `/gr:research-doc` | provider billing applies |
| Analyze a video | `/gr:video` | provider billing applies |
| Multi-turn video Q&A | `/gr:video-chat` | provider billing per turn |
| Analyze a URL/file/text | `/gr:analyze` | provider billing applies |
| Find past work | `/gr:recall` | provider billing applies |
| Save to knowledge store | `/gr:ingest` | provider billing applies |
| Check setup | `/gr:doctor` | provider billing applies |
| View/change model preset | `/gr:models` | provider billing applies |
| Debug MLflow traces | `/gr:traces` | provider billing applies |
| First-time setup guide | `/gr:getting-started` | provider billing applies |

Present your recommendation in this format:

```
RECOMMENDED: /gr:<command> "<args>"
WHY: <one sentence>
ALTERNATIVE: /gr:<other>
COST: check provider pricing | TIME: depends on scope
NEXT STEP: <follow-up action>
```

## Step 4: Suggest Follow-up

- After research → verify automatic persistence; use `/gr:ingest` for explicit missing records
- Prior work found → suggest `/gr:recall` to review first
- Video analysis → suggest `/gr:video-chat` for follow-up questions
- Unsure about setup → suggest `/gr:doctor`
