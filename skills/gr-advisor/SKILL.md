---
name: gr-advisor
description: Recommends an available research workflow when the user asks about Gemini-powered research, YouTube video analysis, web content extraction, or Weaviate knowledge queries. Activates only when the request matches this plugin and no specific workflow was already chosen — not for code editing, debugging, testing, git operations, or general questions.
allowed-tools: mcp__video-research__knowledge_search
---

# GR Workflow Advisor

Recommend an available workflow before executing research, video analysis, or content tasks.

## When to Activate

Activate when the user expresses intent to:
- Research a topic, question, or concept
- Analyze a YouTube video or local video file
- Analyze a URL, document, or pasted content
- Search the web for current information
- Find or manage past research/knowledge

Do NOT activate for: code tasks, git operations, file editing, general questions, unrelated work, or when the user already selected a workflow. Never recommend the advisor itself — if intent is unclear, ask a clarifying question.

## Workflow

1. **Check available routes and categorize intent**: research | video | content | knowledge | system. In Codex, discover the installed plugin's MCP tools and recommend their actual exposed names. Use `/gr:*` routes only when the client registers those commands; Codex does not load the package's Claude commands.
2. **Check prior work**: call `knowledge_search(query="<user topic>", limit=3)` — skip if Weaviate is unavailable or the query is a system task
3. **Recommend**: use structured format below, max 3 options
4. **Wait**: do not execute — let the user confirm or adjust

## Recommendation Format

```
RECOMMENDED: <available tool or registered command> — <arguments>
WHY: <one sentence>
ALTERNATIVE: <available alternative>
COST: check provider pricing | TIME: depends on scope
NEXT STEP: <follow-up action>
```

## Key Routing Rules

Choose only a route present in the current client. If none is available, report
that missing capability instead of inventing a command or starting installation.

| Intent | Codex MCP tool | Registered Claude command |
| --- | --- | --- |
| Quick current question | `web_search` | `/gr:search` |
| Video URL | `video_analyze` or `video_create_session` | `/gr:video` or `/gr:video-chat` |
| Document/URL | `content_analyze` or `research_document` | `/gr:analyze` or `/gr:research-doc` |
| Topic research | `research_deep` or `research_web` | `/gr:research` or `/gr:research-deep` |
| Prior work exists | `knowledge_search` | `/gr:recall` |
| Persist completed research | `knowledge_ingest` | `/gr:ingest` |

A quick question does not need long-running deep research. Provider billing can
apply to search, analysis and research; explain the selected scope before execution.
Keep the recommendation bounded to three options and wait for the user's choice.
