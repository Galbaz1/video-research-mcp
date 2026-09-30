# Roadmap

This page separates capabilities present in the source from earlier proposals.
Use it to find an implementation entry point or a discussion to join. A source
capability does not establish which version a registry or running client has;
see [Publishing](docs/PUBLISHING.md) for that verification.

The linked issues identify feature discussions. Their current status and agreed
scope belong to the issue itself.

## Completed

<a id="2-document-research-"></a>

### 2. Document Research

Research a supplied document set with multi-phase extraction, evidence tiers,
and document/page citations. `research_document` and `/gr:research-doc` are
implemented; file preparation handles local files and checked URL downloads.
Citation presence still requires source inspection when a claim matters.

Sources: [document tool](src/video_research_mcp/tools/research_document.py),
[file preparation](src/video_research_mcp/tools/research_document_file.py),
[issue #2](https://github.com/Galbaz1/video-research-mcp/issues/2).

<a id="3-mlflow-tracing-"></a>

### 3. MLflow Tracing

Optional tracing provides MCP tool spans and Gemini SDK autologging when enabled.
The `[tracing]` extra, `/gr:traces`, and `mlflow-traces` skill are implemented.
Tracing is disabled without the required configuration/library and can be forced
off with `GEMINI_TRACING_ENABLED=false`. Trace coverage depends on the SDK call
path; do not infer that every external call was captured.

Sources: [tracing module](src/video_research_mcp/tracing.py),
[issue #3](https://github.com/Galbaz1/video-research-mcp/issues/3).

<a id="5-video-explainer-mcp-"></a>

### 5. Video Explainer MCP

The independent companion wraps an external `video_explainer` checkout with
15 tools for projects, pipeline steps, rendering, audio, and quality checks.
Background rendering uses start/poll jobs. `/ve:*` workflows are shipped by the
installer, but require separate companion registration and upstream setup.

Sources: [package guide](packages/video-explainer-mcp/README.md),
[issue #5](https://github.com/Galbaz1/video-research-mcp/issues/5).

<a id="video-agent-mcp-"></a>

### Video Agent MCP

Two companion tools generate scene components through bounded concurrent Claude
Agent SDK queries. Successful scene files and failed results remain distinct;
a single-scene tool supports targeted regeneration. Terminal SDK success,
timeouts, turn budgets, and isolated child settings are enforced. Generation
speed depends on project and provider conditions; typechecking and rendering
remain separate checks.

Source: [package guide](packages/video-agent-mcp/README.md).

<a id="knowledge-store-reranker--flash-summarization-"></a>

### Knowledge Store Reranker + Flash Summarization

Knowledge search supports Cohere reranking and Gemini Flash post-processing.
Search overfetches candidates before ranking; results can include `rerank_score`
and concise `summary` fields. Cohere use is auto-enabled by its configured key
unless explicitly disabled. Summarization and reranking can be configured
separately.

Sources: [knowledge tools](src/video_research_mcp/tools/knowledge/),
[knowledge-store guide](docs/tutorials/KNOWLEDGE_STORE.md).

<a id="media-asset-pipeline-"></a>

### Media Asset Pipeline

Video/content results can retain local media and screenshot paths in the
knowledge store. `/gr:recall` helps rediscover local artifacts. Paths support
access only while the underlying files are available; provider analysis remains
an external-processing workflow.

Sources: [recall command](commands/recall.md),
[storage modules](src/video_research_mcp/weaviate_store/).

### 1. Deep Research Agent

The earlier proposal is implemented as `research_web`, `research_web_status`,
`research_web_followup`, and `research_web_cancel`, rather than the proposed
`research_agent_*` names. These use the Interactions API and a start/poll pattern;
completed reports and follow-ups can be stored in `DeepResearchReports`.
Provider runtime and usage vary; inspect terminal status, citations, and errors.

Sources: [web research tools](src/video_research_mcp/tools/research_web.py),
[issue #1](https://github.com/Galbaz1/video-research-mcp/issues/1).

<a id="in-progress"></a>

### Contract Hardening (PR #19)

The previously listed work now has an implementation in source:
`video_analyze(strict_contract=True)` runs analysis, strategy/concept-map
construction, artifact rendering, and quality gates. Semantic validation and
JSON validation helpers also exist. The schema-complexity helper is present;
its existence does not imply it is enforced for every caller-provided schema.

This feature is optional, and its quality gates do not independently verify all
factual claims.

Sources: [contract pipeline](src/video_research_mcp/contract/pipeline.py),
[semantic validation](src/video_research_mcp/validation.py),
[schema helper](src/video_research_mcp/schema_guard.py),
[PR #19](https://github.com/Galbaz1/video-research-mcp/pull/19).

## Planned

The following remain proposals rather than implemented tools/skills in this
checkout. They carry no delivery date or release commitment.

### 4. Writing Style Skill

The earlier proposal describes a passive `writing-style` skill applying selected
humanizer patterns to command/agent `analysis.md` prose. Its proposed scope is
research writing; structured MCP output and visualization HTML remain outside it.
A dedicated skill with this name is not shipped in `FILE_MAP`.

Discussion: [issue #4](https://github.com/Galbaz1/video-research-mcp/issues/4).

### 6. Knowledge Conflict Detection

The proposal describes `knowledge_conflicts` and a `/gr:recall conflicts` route
for contradictory, outdated, or inconsistent stored information. It proposes
four conflict types, severity/resolution guidance, and strict/balanced/lenient
sensitivity. Those interfaces are not registered in the current source.

Discussion: [issue #9](https://github.com/Galbaz1/video-research-mcp/issues/9).

Before starting a proposal, confirm its current scope in the tracker and follow
[Contributing](CONTRIBUTING.md).
