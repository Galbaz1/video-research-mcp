---
description: Web search via Gemini grounding
argument-hint: <query>
allowed-tools: mcp__video-research__web_search
---

# Web Search: $ARGUMENTS

Search the web for the given query using Gemini-grounded search.

## Steps

1. Use `web_search` with query="$ARGUMENTS"
2. Present results clearly with:
   - **Source title** and URL for each result
   - **Key excerpt** or summary from each source
   - **Relevance** — how well it answers the query
3. If results are thin, suggest refined queries the user could try
