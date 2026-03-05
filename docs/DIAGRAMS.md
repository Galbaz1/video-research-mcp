# Architecture Diagrams

Visual reference for the video-research MCP server architecture. Each section contains a Mermaid diagram with a brief description.

---

## 1. Server Mounting Hierarchy

The root `FastMCP("video-research")` server mounts 7 sub-servers, each owning a distinct set of tools. The lifespan hook manages shutdown of shared clients (GeminiClient, WeaviateClient).

```mermaid
graph TD
    classDef root fill:#1a1a2e,stroke:#e94560,color:#fff,stroke-width:2px
    classDef subserver fill:#16213e,stroke:#0f3460,color:#fff,stroke-width:1px
    classDef tool fill:#0f3460,stroke:#533483,color:#eee,stroke-width:1px
    classDef lifecycle fill:#533483,stroke:#e94560,color:#fff,stroke-width:1px

    ROOT["FastMCP('video-research')<br/>server.py"]:::root

    LIFE["_lifespan<br/>GeminiClient.close_all()<br/>WeaviateClient.aclose()"]:::lifecycle
    ROOT -. "lifespan hook" .-> LIFE

    VS["video_server<br/>FastMCP('video')"]:::subserver
    YS["youtube_server<br/>FastMCP('youtube')"]:::subserver
    RS["research_server<br/>FastMCP('research')"]:::subserver
    CS["content_server<br/>FastMCP('content')"]:::subserver
    SS["search_server<br/>FastMCP('search')"]:::subserver
    IS["infra_server<br/>FastMCP('infra')"]:::subserver
    KS["knowledge_server<br/>FastMCP('knowledge')"]:::subserver

    ROOT --> VS
    ROOT --> YS
    ROOT --> RS
    ROOT --> CS
    ROOT --> SS
    ROOT --> IS
    ROOT --> KS

    V1["video_analyze"]:::tool
    V2["video_create_session"]:::tool
    V3["video_continue_session"]:::tool
    V4["video_batch_analyze"]:::tool
    VS --> V1
    VS --> V2
    VS --> V3
    VS --> V4

    Y1["video_metadata"]:::tool
    Y0["video_comments"]:::tool
    Y2["video_playlist"]:::tool
    YS --> Y1
    YS --> Y0
    YS --> Y2

    R1["research_deep"]:::tool
    R2["research_plan"]:::tool
    R3["research_assess_evidence"]:::tool
    R4["research_document"]:::tool
    R5["research_web"]:::tool
    R6["research_web_status"]:::tool
    R7["research_web_followup"]:::tool
    R8["research_web_cancel"]:::tool
    RS --> R1
    RS --> R2
    RS --> R3
    RS --> R4
    RS --> R5
    RS --> R6
    RS --> R7
    RS --> R8

    C1["content_analyze"]:::tool
    C2["content_extract"]:::tool
    C3["content_batch_analyze"]:::tool
    CS --> C1
    CS --> C2
    CS --> C3

    S1["web_search"]:::tool
    SS --> S1

    I1["infra_cache"]:::tool
    I2["infra_configure"]:::tool
    IS --> I1
    IS --> I2

    K1["knowledge_search"]:::tool
    K2["knowledge_related"]:::tool
    K3["knowledge_stats"]:::tool
    K4["knowledge_fetch"]:::tool
    K5["knowledge_ingest"]:::tool
    K6["knowledge_ask"]:::tool
    K7["knowledge_query"]:::tool
    KS --> K1
    KS --> K2
    KS --> K3
    KS --> K4
    KS --> K5
    KS --> K6
    KS --> K7
```

---

## 2. GeminiClient Request Flow

Every tool that calls Gemini follows this pipeline: check the file-based cache, call GeminiClient (which delegates to the Google GenAI SDK with retry logic), validate the response, write back to cache, and optionally persist to Weaviate. The diagram shows both cache-hit and cache-miss paths.

```mermaid
flowchart TD
    classDef toolcall fill:#1a1a2e,stroke:#e94560,color:#fff,stroke-width:2px
    classDef cache fill:#16213e,stroke:#0f3460,color:#fff,stroke-width:1px
    classDef client fill:#0f3460,stroke:#533483,color:#eee,stroke-width:1px
    classDef api fill:#533483,stroke:#e94560,color:#fff,stroke-width:1px
    classDef validate fill:#2a9d8f,stroke:#264653,color:#fff,stroke-width:1px
    classDef store fill:#e76f51,stroke:#264653,color:#fff,stroke-width:1px
    classDef decision fill:#264653,stroke:#2a9d8f,color:#fff,stroke-width:1px

    TOOL["Tool function called<br/>(video_analyze, research_deep, etc.)"]:::toolcall

    CACHE_CHECK{"cache.load()<br/>File-based JSON cache<br/>keyed by content_id +<br/>tool + instruction_hash +<br/>model_hash"}:::decision

    TOOL --> CACHE_CHECK

    HIT["Return cached result<br/>cached: true"]:::cache
    CACHE_CHECK -- "Cache HIT<br/>(file exists, not expired)" --> HIT

    SCHEMA_CHECK{"Custom<br/>output_schema?"}:::decision
    CACHE_CHECK -- "Cache MISS<br/>(missing or TTL expired)" --> SCHEMA_CHECK

    GEN["GeminiClient.generate()<br/>response_schema=custom_dict<br/>Returns raw JSON text"]:::client
    GEN_S["GeminiClient.generate_structured()<br/>schema=PydanticModel<br/>Returns validated model"]:::client

    SCHEMA_CHECK -- "Yes (caller-provided)" --> GEN
    SCHEMA_CHECK -- "No (default schema)" --> GEN_S

    CFG["get_config()<br/>resolve model, thinking_level,<br/>temperature"]:::client
    GEN --> CFG
    GEN_S --> CFG

    RETRY["with_retry()<br/>Exponential backoff<br/>for transient errors<br/>(429, 503, quota, timeout)"]:::client
    CFG --> RETRY

    API["Google GenAI API<br/>client.aio.models.generate_content()<br/>+ ThinkingConfig<br/>+ response_json_schema"]:::api
    RETRY --> API

    STRIP["Strip thinking parts<br/>Extract text from<br/>non-thought parts"]:::validate
    API --> STRIP

    PARSE_JSON["json.loads(raw)<br/>Parse JSON text"]:::validate
    PARSE_PYDANTIC["schema.model_validate_json(raw)<br/>Pydantic validation"]:::validate

    STRIP --> PARSE_JSON
    STRIP --> PARSE_PYDANTIC

    PARSE_JSON -. "custom schema path" .-> RESULT
    PARSE_PYDANTIC -. "default schema path" .-> MODEL_DUMP

    MODEL_DUMP["model.model_dump()<br/>Convert to dict"]:::validate
    MODEL_DUMP --> RESULT

    RESULT["Result dict"]:::toolcall

    CACHE_WRITE["cache.save()<br/>Write JSON to<br/>~/.cache/video-research-mcp/"]:::cache
    RESULT --> CACHE_WRITE

    WEAVIATE["weaviate_store.store_*()<br/>Write-through to Weaviate<br/>(non-fatal on failure)"]:::store
    CACHE_WRITE --> WEAVIATE

    RETURN["Return result to MCP client"]:::toolcall
    WEAVIATE --> RETURN
    HIT --> RETURN
```

---

## 3. Session Lifecycle

Video sessions enable multi-turn conversations about a single video. The SessionStore holds sessions in memory with optional SQLite persistence. Sessions are evicted after a configurable TTL and history is trimmed to prevent unbounded growth.

```mermaid
stateDiagram-v2
    classDef active fill:#2a9d8f,color:#fff
    classDef expired fill:#e76f51,color:#fff
    classDef persist fill:#0f3460,color:#fff

    [*] --> CreateSession: video_create_session(url)

    state CreateSession {
        direction LR
        Evict[Evict expired sessions] --> CapCheck[Check max_sessions cap]
        CapCheck --> Allocate[Allocate new VideoSession<br/>session_id = uuid4 hex 12]
    }

    CreateSession --> Active: SessionInfo returned<br/>(session_id, video_title)

    state Active {
        direction TB
        InMemory[In-memory dict<br/>SessionStore._sessions]
        SQLite[SQLite WAL persistence<br/>SessionDB.save_sync()]
        InMemory --> SQLite: Write-through<br/>(if GEMINI_SESSION_DB set)
    }

    Active --> ContinueTurn: video_continue_session(session_id, prompt)

    state ContinueTurn {
        direction TB
        Lookup[SessionStore.get(session_id)]
        BuildHistory[Build contents from<br/>session.history + new prompt]
        GeminiCall[GeminiClient generate<br/>with full history context]
        AddTurn[session_store.add_turn()<br/>append user + model Content]
        TrimHistory[Trim history to<br/>session_max_turns * 2 items]
        WeaviateStore[store_session_turn()<br/>to SessionTranscripts]
        Lookup --> BuildHistory
        BuildHistory --> GeminiCall
        GeminiCall --> AddTurn
        AddTurn --> TrimHistory
        TrimHistory --> WeaviateStore
    }

    ContinueTurn --> Active: SessionResponse returned<br/>(response, turn_count)

    Active --> RecoverFromDB: Session evicted from memory<br/>but exists in SQLite
    RecoverFromDB --> Active: SessionDB.load_sync()<br/>restores to memory

    Active --> Expired: TTL exceeded<br/>(session_timeout_hours)
    Active --> EvictedByCap: max_sessions reached<br/>(oldest evicted)

    Expired --> [*]
    EvictedByCap --> [*]
```

---

## 4. Weaviate Knowledge Store Data Flow

All tool results are written through to Weaviate collections via `weaviate_store/`. The knowledge tools (`knowledge_*`) provide query access. The 12 collections store different data types, each with common properties (`created_at`, `source_tool`) plus domain-specific fields.

```mermaid
flowchart LR
    classDef tool fill:#1a1a2e,stroke:#e94560,color:#fff,stroke-width:2px
    classDef store fill:#16213e,stroke:#0f3460,color:#fff,stroke-width:1px
    classDef client fill:#0f3460,stroke:#533483,color:#eee,stroke-width:1px
    classDef collection fill:#533483,stroke:#e94560,color:#fff,stroke-width:1px
    classDef query fill:#2a9d8f,stroke:#264653,color:#fff,stroke-width:1px
    classDef weaviate fill:#e76f51,stroke:#264653,color:#fff,stroke-width:2px

    subgraph "Producer Tools (write-through)"
        T1["video_analyze<br/>video_batch_analyze"]:::tool
        T2["content_analyze"]:::tool
        T3["research_deep"]:::tool
        T4["research_plan"]:::tool
        T5["research_assess_evidence"]:::tool
        T9["research_document"]:::tool
        T10["research_web_status"]:::tool
        T11["research_web_followup"]:::tool
        T6["video_metadata"]:::tool
        T7["video_continue_session"]:::tool
        T8["web_search"]:::tool
    end

    subgraph "weaviate_store/"
        S1["store_video_analysis()"]:::store
        S2["store_content_analysis()"]:::store
        S3["store_research_finding()"]:::store
        S4["store_research_plan()"]:::store
        S5["store_evidence_assessment()"]:::store
        S9["store_deep_research()"]:::store
        S10["store_deep_research_followup()"]:::store
        S6["store_video_metadata()"]:::store
        S7["store_session_turn()"]:::store
        S8["store_web_search()"]:::store
    end

    T1 --> S1
    T2 --> S2
    T3 --> S3
    T4 --> S4
    T5 --> S5
    T9 --> S3
    T10 --> S9
    T11 --> S10
    T6 --> S6
    T7 --> S7
    T8 --> S8

    WC["WeaviateClient.get()<br/>Thread-safe singleton<br/>auto-creates schema"]:::client

    S1 --> WC
    S2 --> WC
    S3 --> WC
    S4 --> WC
    S5 --> WC
    S6 --> WC
    S7 --> WC
    S8 --> WC

    subgraph "Weaviate Cloud"
        direction TB
        C1["ResearchFindings<br/>topic, claim, evidence_tier,<br/>confidence, executive_summary"]:::collection
        C2["VideoAnalyses<br/>video_id, instruction,<br/>title, summary, key_points"]:::collection
        C3["ContentAnalyses<br/>source, instruction,<br/>title, summary, entities"]:::collection
        C4["VideoMetadata<br/>video_id, title, channel,<br/>tags, view_count, duration"]:::collection
        C5["SessionTranscripts<br/>session_id, video_title,<br/>turn_prompt, turn_response"]:::collection
        C6["WebSearchResults<br/>query, response,<br/>sources_json"]:::collection
        C7["ResearchPlans<br/>topic, scope,<br/>task_decomposition, phases"]:::collection
    end

    WC --> C1
    WC --> C2
    WC --> C3
    WC --> C4
    WC --> C5
    WC --> C6
    WC --> C7

    subgraph "Knowledge Query Tools"
        K1["knowledge_search<br/>hybrid: BM25 + vector<br/>alpha controls balance"]:::query
        K2["knowledge_related<br/>near-object vector search"]:::query
        K3["knowledge_stats<br/>object counts per collection"]:::query
        K4["knowledge_ingest<br/>manual object insertion"]:::query
    end

    C1 --> K1
    C2 --> K1
    C3 --> K1
    C4 --> K1
    C5 --> K1
    C6 --> K1
    C7 --> K1

    C1 --> K2
    C2 --> K2
    C3 --> K2
    C4 --> K2
    C5 --> K2
    C6 --> K2
    C7 --> K2

    C1 --> K3
    C2 --> K3
    C3 --> K3
    C4 --> K3
    C5 --> K3
    C6 --> K3
    C7 --> K3

    C1 --> K4
    C2 --> K4
    C3 --> K4
    C4 --> K4
    C5 --> K4
    C6 --> K4
    C7 --> K4
```

---

## 5. Reranker & Flash Post-Processing Flow

`knowledge_search` overfetches 3x the requested limit, reranks via Cohere (Weaviate-integrated), then optionally runs Gemini Flash to score relevance, generate one-line summaries, and trim properties before returning the final result set.

```mermaid
sequenceDiagram
    participant Caller
    participant KS as knowledge_search
    participant WV as Weaviate
    participant RR as Cohere Reranker<br/>(Weaviate module)
    participant Flash as Gemini Flash<br/>(summarize_hits)

    Caller->>KS: query, limit=10

    Note over KS: fetch_limit = limit * 3<br/>(overfetch factor)

    KS->>WV: hybrid/semantic/bm25<br/>limit=30, rerank=Rerank(prop, query)
    WV->>RR: rerank 30 candidates
    RR-->>WV: scored + reordered
    WV-->>KS: 30 results with<br/>rerank_score + base score

    Note over KS: Sort by rerank_score desc,<br/>base score as tiebreaker

    alt flash_summarize enabled
        KS->>Flash: _build_prompt(hits, query)<br/>batch up to 20 hits
        Flash-->>KS: HitSummaryBatch<br/>(relevance, summary,<br/>useful_properties per hit)
        Note over KS: Trim properties to<br/>useful ones, attach summaries
    end

    KS-->>Caller: KnowledgeSearchResult<br/>reranked=true,<br/>flash_processed=true/false
```

---

## 6. MLflow Tracing Flow

Optional tracing via `mlflow-tracing`. The `@trace` decorator wraps MCP tool entrypoints as `TOOL` root spans. `mlflow.gemini.autolog()` patches the google-genai SDK to capture every `generate_content` call as a child `CHAT_MODEL` span. Guarded import — the server runs fine without `mlflow-tracing` installed.

```mermaid
sequenceDiagram
    participant MCP as MCP Client
    participant Tool as Tool Function<br/>(@trace decorator)
    participant MLflow as MLflow
    participant Gemini as GeminiClient<br/>(autologged)
    participant API as Google GenAI API

    Note over MLflow: setup() at server start:<br/>set_tracking_uri()<br/>set_experiment()<br/>gemini.autolog()

    MCP->>Tool: tool invocation

    alt tracing enabled
        Tool->>MLflow: Start TOOL span<br/>(name, span_type="TOOL")
        MLflow-->>Tool: span context
    end

    Tool->>Gemini: generate() / generate_structured()
    Gemini->>API: aio.models.generate_content()

    alt tracing enabled
        Note over Gemini,MLflow: autolog captures<br/>CHAT_MODEL child span<br/>(model, tokens, latency)
        API-->>Gemini: response
        Gemini-->>Tool: parsed result
        Tool->>MLflow: Complete TOOL span<br/>(success/error, attributes)
    else tracing disabled
        API-->>Gemini: response
        Gemini-->>Tool: parsed result
        Note over Tool: @trace is identity —<br/>zero overhead
    end

    Tool-->>MCP: tool result

    Note over MLflow: shutdown():<br/>flush_trace_async_logging()
```

---

## 7. Monorepo Package Structure

Three independent Python packages share a single git repository. The root package (`video-research-mcp`) is the main MCP server. The two packages under `packages/` are standalone MCP servers for video production workflows. All packages use hatchling and share the same Python/tooling requirements but have no runtime cross-dependencies.

```mermaid
graph TD
    classDef root fill:#1a1a2e,stroke:#e94560,color:#fff,stroke-width:2px
    classDef pkg fill:#16213e,stroke:#0f3460,color:#fff,stroke-width:1px
    classDef detail fill:#0f3460,stroke:#533483,color:#eee,stroke-width:1px
    classDef dep fill:#533483,stroke:#e94560,color:#fff,stroke-width:1px

    REPO["gemini-research-mcp<br/>(monorepo)"]:::root

    subgraph "Root: video-research-mcp"
        ROOT_PKG["video-research-mcp<br/>28 tools | 7 sub-servers<br/>PyPI + npm (plugin installer)"]:::pkg
        ROOT_DEPS["google-genai >=1.57<br/>fastmcp >=3.0.2<br/>weaviate-client >=4.19.2<br/>pydantic >=2.0"]:::dep
        ROOT_PKG --- ROOT_DEPS
    end

    subgraph "packages/video-agent-mcp"
        AGENT_PKG["video-agent-mcp<br/>2 tools | 1 sub-server<br/>Parallel scene generation"]:::pkg
        AGENT_DEPS["claude-agent-sdk >=0.1.0<br/>fastmcp >=3.0.2<br/>pydantic >=2.0"]:::dep
        AGENT_PKG --- AGENT_DEPS
    end

    subgraph "packages/video-explainer-mcp"
        EXPLAINER_PKG["video-explainer-mcp<br/>15 tools | 4 sub-servers<br/>Video synthesis pipeline"]:::pkg
        EXPLAINER_DEPS["fastmcp >=3.0.2<br/>pydantic >=2.0"]:::dep
        EXPLAINER_PKG --- EXPLAINER_DEPS
    end

    REPO --> ROOT_PKG
    REPO --> AGENT_PKG
    REPO --> EXPLAINER_PKG

    SHARED["Shared: Python >=3.11<br/>hatchling build<br/>ruff + pytest"]:::detail
    REPO -.- SHARED
```
