---
name: weaviate-setup
description: Interactive onboarding for the Weaviate knowledge store. Guides users through choosing a deployment type (Cloud, Local Docker, or Custom), setting environment variables, and verifying the connection. Activates when users want to set up or configure Weaviate for persistent knowledge storage.
---

# Weaviate Knowledge Store Setup

You are guiding a user through setting up Weaviate as the persistent knowledge store for the video-research MCP server. Analysis and research tools attempt write-through storage when configured; infrastructure/query tools do not create analysis records and storage failures are non-fatal. Use `knowledge_search`, `knowledge_related`, `knowledge_stats`, `knowledge_fetch`, `knowledge_ingest`, and `knowledge_schema`; optional `knowledge_ask` provides AI Q&A. `knowledge_query` remains available but is deprecated in favor of `knowledge_search`.

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
          description: "Managed service at console.weaviate.cloud — check current plans and embedding costs"
        - label: "Local Docker"
          description: "Run Weaviate locally via Docker; the selected embedding provider may still use a network service"
        - label: "Custom/Self-hosted"
          description: "Your own Weaviate deployment at a custom URL"
```

### Step 2: Collect Credentials (based on choice)

**If Weaviate Cloud:**
- Direct the user to https://console.weaviate.cloud to select an authorized plan and obtain the cluster URL/API key
- Collect the URL; have the user store the key locally and confirm its presence without pasting it into chat

**If Local Docker:**
- Select the server version using the [official Docker guide](https://docs.weaviate.io/deploy/installation-guides/docker-installation). This example uses its 2026-10-06 documented image and OpenAI vectorizer; it is not a tested deployment receipt:
```yaml
services:
  weaviate:
    image: cr.weaviate.io/semitechnologies/weaviate:1.39.8
    ports:
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:50051:50051"
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      PERSISTENCE_DATA_PATH: "/var/lib/weaviate"
      DEFAULT_VECTORIZER_MODULE: text2vec-openai
      ENABLE_MODULES: text2vec-openai
```
- [Weaviate Embeddings](https://docs.weaviate.io/weaviate/model-providers/weaviate/embeddings) are Cloud-only. For this Docker example, configure the already supported OpenAI vectorizer and authorize its embedding costs separately. No local model or sidecar is selected.
- The URL will be `http://localhost:8080`
- Anonymous loopback access needs no Weaviate API key; the OpenAI vectorizer still needs its provider key.
- Before retaining knowledge, add the persistent volume from the official Docker guide. `PERSISTENCE_DATA_PATH` alone does not preserve data when the container is replaced.

**If Custom:**
- Ask for the full URL (including port)
- Ask whether authentication is required; keep any API key in local configuration

### Step 3: Configure Environment

Once you have the URL (and optionally API key), tell the user to configure the shared server config file (recommended) or shell env:

**Option A -- Shared config file (recommended for plugin users):**
Edit `~/.config/video-research-mcp/.env`:

**Docker deployment:**
```bash
GEMINI_API_KEY=<their-gemini-key>
WEAVIATE_URL=http://localhost:8080
WEAVIATE_VECTORIZER=openai
OPENAI_API_KEY=<locally-stored-embedding-key>
```

**Cloud deployment:**
```bash
GEMINI_API_KEY=<their-gemini-key>
WEAVIATE_URL=<cluster-url>
WEAVIATE_API_KEY=<locally-stored-key>
WEAVIATE_VECTORIZER=weaviate
```

The server auto-detects `WEAVIATE_VECTORIZER` based on `OPENAI_API_KEY`: if present → `openai`, otherwise → `weaviate` (built-in embeddings). Setting it explicitly avoids surprises.

Notes:
- Use a full URL with scheme (`https://...` for cloud, `http://localhost:8080` for local).
- Verify substitutions resolve in the server process; supported client placeholders may remain in `.mcp.json`.

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

This attempts connection, collection setup, and search only when `WEAVIATE_URL` is configured. An empty result also occurs when storage is disabled; confirm configuration and test a known record before claiming retrieval works.

Then confirm collections exist:

```
knowledge_stats()
```

Inspect the returned collection list and errors. Disabled storage returns an empty list; per-collection failures can appear as zero counts. Check a known record or server diagnostics before interpreting zeros as an empty healthy store. Troubleshoot reported errors:

| Error | Fix |
|-------|-----|
| `WEAVIATE_CONNECTION` | Check URL is reachable, Docker is running, firewall allows the port |
| `WEAVIATE_SCHEMA` | Check the selected server/client/vectorizer compatibility; preserve existing collections and diagnose schema drift before any authorized migration |
| `Weaviate not configured` | `WEAVIATE_URL` env var is not set or server wasn't restarted |

### Step 5: Confirm Working

Once `knowledge_stats` returns successfully, tell the user:

1. The knowledge connection works; verify a known stored record separately before claiming analysis persistence
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
          description: "Enables knowledge_ask; requires weaviate-agents and a compatible authorized QueryAgent service. knowledge_query is deprecated."
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
- `knowledge_query(query="...")` -- deprecated natural-language retrieval; prefer `knowledge_search`

These tools use Weaviate's AsyncQueryAgent, which automatically translates natural-language queries into optimized Weaviate operations.

## Collections Created Automatically

| Collection | Populated by | Knowledge tools that query it |
|---|---|---|
| `ResearchFindings` | `research_deep`, `research_assess_evidence`, `research_document` | Supported knowledge tools |
| `VideoAnalyses` | `video_analyze`, `video_batch_analyze` | Supported knowledge tools |
| `ContentAnalyses` | `content_analyze`, `content_batch_analyze` | Supported knowledge tools |
| `VideoMetadata` | `video_metadata` | Supported knowledge tools |
| `SessionTranscripts` | `video_continue_session` | Supported knowledge tools |
| `WebSearchResults` | `web_search` | Supported knowledge tools |
| `ResearchPlans` | `research_plan` | Supported knowledge tools |
| `DeepResearchReports` | `research_web_status`, `research_web_followup` | Supported knowledge tools |
| `CommunityReactions` | Explicit ingestion of checked comment analysis | Supported knowledge tools |
| `ConceptKnowledge` | concept extraction/enrichment pipelines | Supported knowledge tools |
| `RelationshipEdges` | relationship graph extraction | Supported knowledge tools |
| `CallNotes` | Explicit ingestion of call/meeting notes | Supported knowledge tools |
| `AcademicPapers` | Semantic Scholar discovery tools | Supported knowledge tools |

## Supported Deployment URLs

| Type | Example URL | API Key |
|------|------------|---------|
| Weaviate Cloud | `https://my-cluster-abc123.weaviate.network` | Required |
| Local Docker | `http://localhost:8080` | Not needed |
| Custom | `https://weaviate.mycompany.com:8080` | Depends |

## Graceful Degradation

Without `WEAVIATE_URL`, analysis remains available and write-through storage is skipped. Basic search/stats return empty results; optional agent tools can return dependency/configuration errors. Report persistence separately from analysis success.
