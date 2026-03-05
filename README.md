# video-research-mcp

Claude Code can't process video. Gemini 3.1 Pro can. This plugin bridges the two -- giving Claude access to Gemini's video understanding, multi-source research, and web search through MCP.

[![CI](https://github.com/Galbaz1/video-research-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Galbaz1/video-research-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/video-research-mcp)](https://pypi.org/project/video-research-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

<div align="center">
  <a href="https://youtu.be/MQn7dMalTq4">
    <img src="https://img.youtube.com/vi/MQn7dMalTq4/maxresdefault.jpg" alt="video-research-mcp demo" width="600">
  </a>
  <p><em>Watch the full demo on YouTube</em></p>
</div>

## What's in the box

A **Claude Code plugin** -- not just MCP servers, but a full integration: 45 tools, 16 slash commands, 6 skills, and 6 sub-agents that work together out of the box. The MCP servers provide the tools, the commands give you quick workflows (`/gr:video`, `/gr:research`), the skills teach Claude how to use everything correctly, and the agents handle background tasks like parallel research and visualization.

| Server | Tools | Purpose |
|--------|-------|---------|
| **video-research-mcp** | 28 | Video analysis, deep research, content extraction, web search, knowledge store |
| **video-creation** | 17 | Synthesize explainer videos from research — project setup, pipeline, quality, audio, and parallel scene generation (wraps [video_explainer](https://github.com/prajwal-y/video_explainer) + [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk)) |

## Install

```bash
npx video-research-mcp@latest
export GEMINI_API_KEY="your-key-here"
```

One install. One API key. The installer copies 16 commands, 6 skills, and 6 agents to `~/.claude/` and configures the MCP servers to run via `uvx` from PyPI.

```bash
npx video-research-mcp@latest --check     # show install status
npx video-research-mcp@latest --uninstall  # clean removal
npx video-research-mcp@latest --local      # install for this project only
```

Requires Python >= 3.11, [uv](https://docs.astral.sh/uv/), [Node.js](https://nodejs.org/) >= 16, and a [Google AI API key](https://aistudio.google.com/apikey).

## What it does

### Watch a meeting recording

```
/gr:video-chat ~/recordings/project-kickoff.mp4
> "Create meeting minutes in Dutch. Screenshot every shared screen."
```

Gemini watches the full video and pulls out timestamps, decisions, and action items. For local files, ffmpeg extracts frames at key visual moments. Files over 20MB are uploaded to Gemini's File API and context-cached -- follow-up questions reuse the cache instead of re-uploading.

### Analyze a YouTube tutorial

```
/gr:video https://youtube.com/watch?v=...
```

Same capabilities, applied to YouTube. You get precise timestamps, a concept map, and comment sentiment analyzed in the background.

### Research a topic with evidence grading

```
/gr:research "HNSW index parameters for high-dimensional embeddings"
```

Runs web search and Gemini analysis in parallel. Every finding gets an evidence tier -- Confirmed, Strong Indicator, Inference, or Speculation -- so you know how much weight to give each claim. Results are visualized as an interactive evidence network.

### Analyze papers, URLs, or directories

```
/gr:analyze https://arxiv.org/abs/2401.12345
/gr:analyze ~/papers/attention-is-all-you-need.pdf
/gr:analyze ~/papers/                              # cross-document comparison
```

Works with PDFs, URLs, and raw text. Extracts entities, relationships, and key arguments. Point it at a directory and it compares all documents in a single pass. Supports PDF, TXT, MD, HTML, XML, JSON, CSV.

### Research grounded in source documents

```
/gr:research-doc ~/papers/
/gr:research-doc paper1.pdf paper2.pdf "Compare methodologies and find contradictions"
```

Four-phase pipeline: Document Mapping, Evidence Extraction, Cross-Reference, Synthesis. Every claim is cited back to document and page number. Documents are uploaded once and reused across all phases.

### Search the web

```
/gr:search "latest developments in MCP protocol"
```

Google Search via Gemini grounding with source citations.

### Recall what you've learned

```
/gr:recall                                # overview: stats + saved analyses
/gr:recall "kubernetes"                   # semantic search + filesystem grep
/gr:recall ask "what do I know about X?"  # AI-powered Q&A with source citations
```

Nothing gets lost. Every analysis and research finding is stored automatically. Weeks later, in a different project, you just ask. When Weaviate is configured, searches use semantic matching -- find "gradient descent tuning" even when you searched for "ML optimization". Without Weaviate, recall falls back to exact keyword grep over saved files.

### Use it as a standalone MCP server

The tools are standard MCP. Any MCP client can call them -- no Claude Code required.

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["video-research-mcp"],
      "env": { "GEMINI_API_KEY": "${GEMINI_API_KEY}" }
    }
  }
}
```

## Commands

| Command | What it does |
|---------|-------------|
| `/gr:video <source>` | One-shot video analysis with concept map and frame extraction |
| `/gr:video-chat <source>` | Multi-turn video Q&A with progressive note-taking |
| `/gr:research <topic>` | Deep research with evidence-tier labeling |
| `/gr:research-deep <topic>` | Launch Gemini Deep Research Agent with interview-built brief |
| `/gr:research-doc <files>` | Evidence-tiered research grounded in source documents |
| `/gr:analyze <content>` | Analyze any URL, file, text, or directory of documents |
| `/gr:search <query>` | Web search via Gemini grounding |
| `/gr:recall [filter]` | Browse past analyses from memory |
| `/gr:models [preset]` | Switch Gemini model preset (best/stable/budget) |
| `/gr:getting-started` | Guided onboarding and environment check |
| `/gr:ingest <file>` | Import external structured knowledge into Weaviate |
| `/gr:explainer <project>` | Create and manage explainer video projects |
| `/gr:explain-video <project>` | Generate a full explainer video from project content |
| `/gr:explain-status <project>` | Check render progress and pipeline state |
| `/gr:traces [filter]` | Query, debug, and evaluate MLflow traces |
| `/gr:doctor [quick\|full]` | Diagnose MCP wiring, API keys, Weaviate, and MLflow connectivity |

### How a command runs

```
/gr:video-chat ~/recordings/call.mp4
> "Summarize this meeting, extract action items"

 Phase 1   Gemini analyzes the video
 Phase 2   Results saved to memory
 Phase 2.5 ffmpeg extracts frames (local files only)
 Phase 3   Concepts and relationships enriched
 Phase 4   Interactive visualization generated (opt-in)
 Phase 5   Playwright screenshots it
 Phase 6   Everything copied to output/<slug>/
```

Visualization and comment analysis run as background agents, so they don't block the conversation.

### Output structure

```
output/project-kickoff-2026-02-28/
├── analysis.md          # timestamped analysis with YAML frontmatter
├── frames/              # extracted video frames (local files)
├── concept-map.html     # interactive visualization
└── screenshot.png       # static capture
```

Files are also saved to Claude's project memory for `/gr:recall`.

## Tools

<details>
<summary><strong>video-research-mcp -- 28 tools</strong></summary>

**Video** (4): `video_analyze`, `video_create_session`, `video_continue_session`, `video_batch_analyze`

**YouTube** (3): `video_metadata`, `video_comments`, `video_playlist`

**Research** (8): `research_deep`, `research_plan`, `research_assess_evidence`, `research_document`, `research_web`, `research_web_status`, `research_web_followup`, `research_web_cancel`

**Content** (3): `content_analyze`, `content_batch_analyze`, `content_extract`

**Search** (1): `web_search`

**Infrastructure** (2): `infra_cache`, `infra_configure`

**Knowledge** (7): `knowledge_search`, `knowledge_related`, `knowledge_stats`, `knowledge_fetch`, `knowledge_ingest`, `knowledge_ask`, `knowledge_query` (deprecated)

</details>

<details>
<summary><strong>Video Creation -- 17 tools</strong></summary>

**Project** (4): `explainer_create`, `explainer_inject`, `explainer_status`, `explainer_list`

**Pipeline** (6): `explainer_generate`, `explainer_step`, `explainer_render`, `explainer_render_start`, `explainer_render_poll`, `explainer_short`

**Quality** (3): `explainer_refine`, `explainer_feedback`, `explainer_factcheck`

**Audio** (2): `explainer_sound`, `explainer_music`

**Scene Generation** (2): `agent_generate_scenes`, `agent_generate_single_scene`

</details>

## Knowledge store

Connect Weaviate, and everything you learn gets stored -- searchable across projects, across sessions. Without it, the plugin works the same; you just don't get persistent semantic search.

Twelve collections are created on first connection:

| Collection | Filled by |
|------------|-----------|
| `ResearchFindings` | `research_deep`, `research_assess_evidence`, `research_document` |
| `VideoAnalyses` | `video_analyze`, `video_batch_analyze` |
| `ContentAnalyses` | `content_analyze`, `content_batch_analyze` |
| `VideoMetadata` | `video_metadata` |
| `SessionTranscripts` | `video_continue_session` |
| `WebSearchResults` | `web_search` |
| `ResearchPlans` | `research_plan` |
| `DeepResearchReports` | `research_web_status` (reports), `research_web_followup` (Q&A updates) |
| `CommunityReactions` | comment analysis (via `/gr:video` agent) |
| `ConceptKnowledge` | concept extraction from analyses |
| `RelationshipEdges` | relationship mapping between concepts |
| `CallNotes` | meeting/call analysis notes |

Eight knowledge tools let you query this data: hybrid search with optional Cohere reranking, semantic similarity, fetch by UUID, manual ingest, schema introspection, and collection stats. `knowledge_ask` uses Weaviate's QueryAgent for AI-generated answers with source citations (requires the `weaviate-agents` package).

```bash
# install QueryAgent support
uv pip install 'video-research-mcp[agents]'
```

To set up Weaviate, run the interactive onboarding or set the vars directly:

```
/skill weaviate-setup
```

```bash
export WEAVIATE_URL="https://your-cluster.weaviate.network"
export WEAVIATE_API_KEY="your-key"
```

## Configuration

| Variable | Default | What it does |
|----------|---------|-------------|
| `GEMINI_API_KEY` | **(required)** | Google AI API key |
| `GEMINI_MODEL` | `gemini-3.1-pro-preview` | Primary model |
| `GEMINI_FLASH_MODEL` | `gemini-3-flash-preview` | Fast model for search and summaries |
| `DEEP_RESEARCH_AGENT` | `deep-research-pro-preview-12-2025` | Interactions API agent for `research_web*` tools |
| `GEMINI_THINKING_LEVEL` | `high` | Thinking depth (minimal / low / medium / high) |
| `GEMINI_TEMPERATURE` | `1.0` | Sampling temperature |
| `GEMINI_CACHE_DIR` | `~/.cache/video-research-mcp/` | Cache directory |
| `GEMINI_CACHE_TTL_DAYS` | `30` | Cache expiry |
| `GEMINI_MAX_SESSIONS` | `50` | Max concurrent video sessions |
| `GEMINI_SESSION_TIMEOUT_HOURS` | `2` | Session TTL |
| `GEMINI_SESSION_MAX_TURNS` | `24` | Max turns per session |
| `GEMINI_SESSION_DB` | `""` | SQLite path for session persistence (empty = in-memory) |
| `YOUTUBE_API_KEY` | `""` | YouTube Data API key (falls back to `GEMINI_API_KEY`) |
| `WEAVIATE_URL` | `""` | Weaviate URL (empty = knowledge store disabled) |
| `WEAVIATE_API_KEY` | `""` | Required for Weaviate Cloud |
| `MLFLOW_TRACKING_URI` | `""` | MLflow server URL (empty = tracing disabled) |
| `MLFLOW_EXPERIMENT_NAME` | `video-research-mcp` | MLflow experiment name |
| `EXPLAINER_PATH` | `""` | Path to cloned video_explainer repo |
| `EXPLAINER_TTS_PROVIDER` | `"mock"` | TTS provider: mock, elevenlabs, openai, gemini, edge |

## Other install methods

### Standalone MCP server (no plugin assets)

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["video-research-mcp"],
      "env": { "GEMINI_API_KEY": "${GEMINI_API_KEY}" }
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "video-research": {
      "command": "uvx",
      "args": ["video-research-mcp"],
      "env": { "GEMINI_API_KEY": "your-key-here" }
    }
  }
}
```

### From source

```bash
git clone https://github.com/Galbaz1/video-research-mcp
cd video-research-mcp
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
node bin/install.js --global
```

## Development

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uv run pytest tests/ -v        # 540 tests, all mocked
uv run ruff check src/ tests/  # lint
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No API key error | Set `GEMINI_API_KEY` |
| 429 / quota exceeded | Wait 60s, or switch to `/gr:models budget` for higher rate limits |
| Video analysis empty | Video may be private, age-restricted, or region-locked |
| No frames extracted | Install ffmpeg: `brew install ffmpeg` |
| Visualization missing | Ensure Node.js is on PATH (Playwright runs via npx) |
| Weaviate won't connect | Check `WEAVIATE_URL` and that the instance is running |
| Knowledge tools empty | Set `WEAVIATE_URL` to enable the knowledge store |
| `weaviate-agents not installed` | `uv pip install 'video-research-mcp[agents]'` |
| MLflow tools unavailable | Set `MLFLOW_TRACKING_URI` and start `mlflow server --port 5001` |
| No traces captured | Ensure `MLFLOW_TRACKING_URI` is set in the server environment |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and PR guidelines. See [ROADMAP.md](ROADMAP.md) for planned work. Report security issues via [SECURITY.md](SECURITY.md).

## Author

**Fausto Albers** -- Lead Gen AI Research & Development at the [Industrial Digital Twins Lab](https://www.hva.nl), Amsterdam University of Applied Sciences (HvA), in the research group of Jurjen Helmus. Founder of [Wonder Why](https://wonderwhy.ai).

## Credits

- **[video_explainer](https://github.com/prajwal-y/video_explainer)** by [prajwal-y](https://github.com/prajwal-y) -- the video synthesis engine behind the explainer pipeline. We extended it with configurable ElevenLabs voice settings, env-based configuration, and MCP tool integration. The original repo is included as a git submodule at `packages/video-explainer/`.
- **[Weaviate](https://weaviate.io/)** -- vector database powering the knowledge store. Twelve collections, hybrid search, and the [Weaviate Claude Code skill](https://github.com/weaviate/weaviate-claude-code-skill) that inspired the knowledge architecture.
- **[Google Gemini](https://ai.google.dev/)** (`google-genai` SDK) -- Gemini 3.1 Pro provides native video understanding, thinking mode, context caching, and the 1M token window that makes all of this work.
- **[FastMCP](https://github.com/jlowin/fastmcp)** -- MCP server framework. The composable sub-server pattern (`app.mount()`) keeps 45 tools organized across 3 servers.
- **[MLflow](https://mlflow.org/)** (`mlflow-tracing`) -- optional observability. Every Gemini call becomes a traceable span with token counts and latency.
- **[Pydantic](https://docs.pydantic.dev/)** -- schema validation for all tool I/O. Structured generation via `model_json_schema()`.
- **[Remotion](https://www.remotion.dev/)** -- React-based video rendering for the explainer pipeline.
- **[ElevenLabs](https://elevenlabs.io/)** -- text-to-speech with word-level timestamps for voiceover generation.
- **[Cohere](https://cohere.com/)** -- optional reranking in knowledge search for better result relevance.
- **[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk)** -- powers parallel scene generation in `video-agent-mcp`.

## License

MIT
