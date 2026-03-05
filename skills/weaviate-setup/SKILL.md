---
name: weaviate-setup
description: Interactive onboarding for the Weaviate knowledge store. Guides users through choosing a deployment type (Cloud, Local Docker, or Custom), setting environment variables, and verifying the connection. Activates when users want to set up or configure Weaviate for persistent knowledge storage.
---

# Weaviate Knowledge Store Setup

You are guiding a user through setting up Weaviate as the persistent knowledge store for the video-research MCP server. All 28 tools automatically write results to Weaviate when configured. 8 knowledge tools (`knowledge_search`, `knowledge_related`, `knowledge_stats`, `knowledge_fetch`, `knowledge_ingest`, `knowledge_schema`, `knowledge_ask`, `knowledge_query`) enable semantic search and AI-powered Q&A across accumulated research.

## Setup Flow

Follow these steps IN ORDER. Use `AskUserQuestion` for each decision point.

### Step 1: Deployment Type

Ask the user which Weaviate deployment they want to use:

```
AskUserQuestion:
  questions:
    - question: "Which Weaviate deployment will you use?"
      header: "Deployment"
      multiSelect: false
      options:
        - label: "Weaviate Cloud (Recommended)"
          description: "Managed cloud service at console.weaviate.cloud — free tier available, no infrastructure to manage"
        - label: "Local Docker"
          description: "Run Weaviate locally via Docker on port 8080 — full control, no network latency"
        - label: "Custom/Self-hosted"
          description: "Your own Weaviate deployment at a custom URL"
```

### Step 2: Collect Credentials (based on choice)

**If Weaviate Cloud:**
- Tell the user to go to https://console.weaviate.cloud, create a free cluster, then copy the cluster URL and API key
- Ask them to provide both values

**If Local Docker:**
- Provide the docker-compose snippet:
```yaml
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.28.4
    ports:
      - "8080:8080"
      - "50051:50051"
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"
      DEFAULT_VECTORIZER_MODULE: text2vec-weaviate
      ENABLE_MODULES: text2vec-weaviate
```
- Note: Our collections use the `text2vec-weaviate` vectorizer (Weaviate's built-in embedding service). No sidecar container needed.
- The URL will be `http://localhost:8080`
- No API key needed for local

**If Custom:**
- Ask for the full URL (including port)
- Ask if authentication is required (API key)

### Step 3: Configure Environment

Once you have the URL (and optionally API key), tell the user to configure the shared server config file (recommended) or shell env:

**Option A -- Shared config file (recommended for plugin users):**
Edit `~/.config/video-research-mcp/.env`:
```bash
GEMINI_API_KEY=<their-gemini-key>
WEAVIATE_URL=<their-url>
WEAVIATE_API_KEY=<their-key-if-any>
```

Notes:
- Use a full URL with scheme (`https://...` for cloud, `http://localhost:8080` for local).
- Keep `.mcp.json` free of unresolved placeholders like `${WEAVIATE_URL}`.

**Option B -- Shell environment:**
```bash
export WEAVIATE_URL="<their-url>"
export WEAVIATE_API_KEY="<their-key-if-any>"  # only for Cloud/authenticated deployments
```

### Step 4: Verify Connection

After the user has configured the environment, tell them to restart Claude Code (or the MCP server) and test with:

```
knowledge_search(query="test")
```

This will attempt to connect and search. On first connection, the server auto-creates all 12 collections. If the search returns empty results with no error, the connection is working.

Then confirm collections exist:

```
knowledge_stats()
```

This should return counts for all 12 collections (all 0 initially). If it returns an error, troubleshoot based on the error category:

| Error | Fix |
|-------|-----|
| `WEAVIATE_CONNECTION` | Check URL is reachable, Docker is running, firewall allows the port |
| `WEAVIATE_SCHEMA` | Collections couldn't be created -- check Weaviate version (need >= 1.25) |
| `Weaviate not configured` | `WEAVIATE_URL` env var is not set or server wasn't restarted |

### Step 5: Confirm Working

Once `knowledge_stats` returns successfully, tell the user:

1. All 28 tools now automatically store results to Weaviate
2. Use `knowledge_search(query="...")` to find past results semantically (supports hybrid, semantic, keyword modes)
3. Use `knowledge_related(object_id="...", collection="...")` to find similar items
4. Use `knowledge_fetch(object_id="...", collection="...")` to retrieve a specific object by UUID
5. Use `knowledge_stats()` to see how much knowledge has accumulated
6. Use `knowledge_ingest(collection="...", properties={...})` to manually insert data
7. The file cache continues to work alongside Weaviate -- dual persistence

### Step 6: Optional -- Enable QueryAgent Tools

Ask the user if they want AI-powered Q&A over their knowledge store:

```
AskUserQuestion:
  questions:
    - question: "Do you want to enable AI-powered knowledge Q&A?"
      header: "QueryAgent (Optional)"
      multiSelect: false
      options:
        - label: "Yes -- install weaviate-agents"
          description: "Enables knowledge_ask (AI answers with sources) and knowledge_query (natural language search). Requires the weaviate-agents package."
        - label: "No -- skip for now"
          description: "You can install it later with: uv pip install 'video-research-mcp[agents]'"
```

**If yes**, tell them to install the agents extra:

```bash
uv pip install 'video-research-mcp[agents]'
```

Then restart the MCP server and test:

```
knowledge_ask(query="What have I researched so far?")
```

If successful, they now also have:
- `knowledge_ask(query="...")` -- AI-generated answers grounded in stored knowledge, with source citations
- `knowledge_query(query="...")` -- natural language object retrieval with automatic query understanding

These tools use Weaviate's AsyncQueryAgent, which automatically translates natural-language queries into optimized Weaviate operations.

## 12 Collections Created Automatically

| Collection | Populated by | Knowledge tools that query it |
|---|---|---|
| `ResearchFindings` | `research_deep`, `research_assess_evidence`, `research_document` | All 8 knowledge tools |
| `VideoAnalyses` | `video_analyze`, `video_batch_analyze` | All 8 knowledge tools |
| `ContentAnalyses` | `content_analyze`, `content_batch_analyze` | All 8 knowledge tools |
| `VideoMetadata` | `video_metadata` | All 8 knowledge tools |
| `SessionTranscripts` | `video_continue_session` | All 8 knowledge tools |
| `WebSearchResults` | `web_search` | All 8 knowledge tools |
| `ResearchPlans` | `research_plan` | All 8 knowledge tools |
| `DeepResearchReports` | `research_web_status`, `research_web_followup` | All 8 knowledge tools |
| `CommunityReactions` | comment-analyst agent outputs | All 8 knowledge tools |
| `ConceptKnowledge` | concept extraction/enrichment pipelines | All 8 knowledge tools |
| `RelationshipEdges` | relationship graph extraction | All 8 knowledge tools |
| `CallNotes` | call/meeting analysis pipelines | All 8 knowledge tools |

## Supported Deployment URLs

| Type | Example URL | API Key |
|------|------------|---------|
| Weaviate Cloud | `https://my-cluster-abc123.weaviate.network` | Required |
| Local Docker | `http://localhost:8080` | Not needed |
| Custom | `https://weaviate.mycompany.com:8080` | Depends |

## Graceful Degradation

If `WEAVIATE_URL` is not set, the server works identically to before -- no errors, no changes. All store operations silently return `None`. Knowledge tools return empty results with a hint to configure Weaviate.
