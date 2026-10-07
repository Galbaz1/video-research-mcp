# User documentation

For a searchable visual guide, open the
[interactive function map (Dutch)](https://galbaz1.github.io/video-research-mcp/guide/).
It maps user problems to tools, prerequisites and steps in the RC6/RC4 candidate.
Publication and fresh-client installation checks remain pending.

Choose the problem you want to solve, then follow the linked guide. The research
server works with any stdio MCP client. Codex uses the native plugin and skills;
`/gr:*` commands are Claude Code workflows, not Codex commands. Start with
[Getting started](tutorials/GETTING_STARTED.md) if you have not connected a client.

## Choose a task

The routes below describe the **RC6 source candidate**, core `0.8.0rc6` on
PyPI and npm `0.8.0-rc.6`. Publication and installation verification are pending.
Check each registry before installing; use a source checkout while pending.
Optional backends require their own setup. Source inventory: 120 core tools,
39 explainer tools and two scene-agent tools; companions connect separately.

| Your task or problem | Recommended route | Next guide or example | Prerequisites and result bounds |
| --- | --- | --- | --- |
| “What does this recording say, and where?” | `video_analyze`; use a video session for follow-up questions | [First analysis](tutorials/GETTING_STARTED.md#make-a-first-useful-call) | Gemini access and a supported URL or local video. Check answers and timestamps against the source; sampling can miss events. |
| “This recording is too long for one useful answer.” | `media_info`, then a dry-run `video_analyze_windows` plan | [Windowed analysis](integrations/VIDEO_WINDOWS.md#bounded-long-video-workflow) | Local media inspection needs FFmpeg/FFprobe; execution needs Gemini access. Inspect intervals and budgets before running; partial outcomes remain visible. |
| “I need a cited answer or research plan on this topic.” | `web_search` for a focused search; `research_plan` to structure work; `research_web` for a background report | [First web question](tutorials/GETTING_STARTED.md#make-a-first-useful-call) and [research status/recovery](integrations/DURABLE_JOBS.md#research-operations) | Gemini access, including access to the configured Deep Research agent for `research_web`. Poll with `research_web_status`; launching a job is not a finished report. Check cited sources. |
| “I need to understand a PDF or compare documents.” | `content_analyze` or `research_document` on the original source | [Document example](tutorials/GETTING_STARTED.md#make-a-first-useful-call) | Gemini access and an accessible PDF, text file or supported URL. Keep the original and check cited pages; a summary does not verify a claim. |
| “I need reusable text, tables or source positions.” | `source_ingest`, then `source_ingest_read` | [Original-source ingestion](integrations/source-ingestion.md) | Builtin PDF extraction needs separately installed Poppler; optional pixel observations need PDFium. Retains original bytes and located elements with format limits; no automatic knowledge indexing. Docling is optional and needs a separately qualified service. |
| “Show the frame or export the clip behind this claim.” | `video_frame` / `video_frames`, then `video_clip_export` or `audio_clip_export` | [Frame example](tutorials/GETTING_STARTED.md#inspect-a-local-frame) and [clip exports](integrations/IMAGE_EXPORTS.md#export-a-finite-source-clip) | Accessible local source, FFmpeg/FFprobe and the operation's optional extras. Inspect actual decoded times and output metadata. Frame selection and exports do not establish what happened elsewhere in the recording. |
| “I need captions, a transcript or audio measurements.” | `audio_transcribe` for supplied captions or explicit ASR; `audio_dsp_analyze` for signal measurements | [Captions and speech](integrations/audio-transcription.md) and [audio DSP](integrations/AUDIO_DSP.md) | Captions need explicit source association; ASR needs a selected backend and submission permission. DSP needs `audio`/`images` extras and FFmpeg, with 30 seconds of aggregate selected audio. Speech accuracy, speaker identity and perceptual quality require separate checks. |
| “Find or save research across sessions.” | Inspect `knowledge_schema`; store with `knowledge_ingest`, retrieve with `knowledge_search` and `knowledge_fetch` | [Knowledge setup](tutorials/KNOWLEDGE_STORE.md#setup) and [tool examples](tutorials/KNOWLEDGE_STORE.md#using-the-knowledge-tools) | Weaviate, collection access and configured embeddings. `knowledge_ask` also needs the optional agents dependency. Verify a stored object when persistence matters; automatic write-through errors are non-fatal. |
| “I need to create, edit or translate an image.” | Explainer image submit, finalize/poll and cancel APIs | [Image setup and lifecycle](../packages/video-explainer-mcp/docs/integrations/image-generation.md) | Companion `generation` extra, regional DashScope endpoint/key, existing pinned script/scene files and current price/access/quote declarations. Translation needs an already public HTTPS image; no automatic upload. Human submission/spending authority is separate from request flags. |
| “I need a short video from text or one/two frames.” | Explainer video submit, poll and cancel APIs | [Text/frame-video setup](../packages/video-explainer-mcp/docs/integrations/generation.md) | Same companion extra and pinned project/quote setup, plus FFmpeg/ffprobe. No upstream CLI required. Saved bytes get hashes and a complete decode check; provider and creative quality remain unqualified. |
| “Turn my material into an explainer or assembled video.” | Configure the separate explainer companion; use existing-material assembly when you already have assets | [Explainer setup](../packages/video-explainer-mcp/README.md#install-and-configure) and [assembly guide](../packages/video-explainer-mcp/docs/integrations/materials.md) | Separate companion; existing-material assembly needs local assets and FFmpeg/ffprobe. CLI project/pipeline/render steps additionally need the upstream checkout, renderer dependencies and chosen provider credentials. Stock search/download is unmounted. |

## Describe your problem in your client

You can use ordinary language in the MCP client where you connected the server:

```text
I have a recording and its requirements PDF. Find decisions that change a
requirement, with recording timestamps and PDF page references. First suggest
which tools to use and tell me what configuration or files are missing.
```

Give the client the source path or URL, the result you need, and any relevant
interval or output format. It can use the tools exposed by your running server;
use your client's normal conversation to refine the request.

## Resolve setup problems

| Symptom | Recommended next step | Exact guide |
| --- | --- | --- |
| No tools appear after installation | Check the client route and launch path; restart the client. In Codex, avoid a manual entry hiding the native plugin server. | [Installation routes](tutorials/GETTING_STARTED.md#choose-an-installation-route) |
| A key works in the terminal but the client cannot use it | Check the client process environment and the selected credential file. Local installs select the project file. | [Configuration precedence](tutorials/GETTING_STARTED.md#configuration) |
| Analysis is denied or exceeds quota | Read the returned category and hint; check account access, selected model and quota. | [Troubleshooting](tutorials/GETTING_STARTED.md#troubleshooting) |
| A download reports `Unsupported Content-Encoding` | Supply the original as a local file, or use a URL that honors identity encoding. | [Download troubleshooting](tutorials/GETTING_STARTED.md#troubleshooting) |
| YouTube metadata returns 403 | Check YouTube Data API v3 enablement and key restrictions; this is separate from Gemini video analysis. | [YouTube setup checks](tutorials/GETTING_STARTED.md#troubleshooting) |
| Frames, clips, speech or knowledge are unavailable | Check the chosen operation's runtime, extras or store configuration in its task guide above. | [Optional configuration](tutorials/GETTING_STARTED.md#add-only-the-options-you-need) |
| Core `job_status` refuses an image/video generation job | Use the companion image finalize/poll or video poll API with an explicit bounded operation. Keep the original job/logical ID; reconcile ambiguous submissions before any new request. | [Image lifecycle](../packages/video-explainer-mcp/docs/integrations/image-generation.md) and [video lifecycle](../packages/video-explainer-mcp/docs/integrations/generation.md) |
| My source fix does not change the installed behavior | Check whether the client launches the published package or your exact checkout. | [Source checkout registration](tutorials/GETTING_STARTED.md#a-source-checkout) |

## Which version does this guide describe?

Installation examples target core RC6 and companion RC4 (`0.2.2rc4` on PyPI),
all pending publication and fresh installation checks. Historical RC5/RC3 facts
retain their original versions. RC6 adds generated-media workflows and source
corrections to the RC5 baseline; it is not whole-programme or full-security
acceptance. Stable `0.7.1` predates the expanded media routes.
Detailed guides follow source main. The connected server's discovered schema
is authoritative for its tool arguments. The
[tool manifest](metrics/tool-contract-manifest.json) is a dated generated source
snapshot. It does not establish the inventory or schemas of your installed server.

A packaged tool or skill does not qualify every provider or runtime. Local model,
spatial and other experimental integrations are not qualified production defaults.
Install only the optional dependencies needed for your chosen route; the plugin
does not install model weights, external runtimes or provider accounts.

## Install and use

| Guide | Use it to |
|---|---|
| [Getting started](tutorials/GETTING_STARTED.md) | Install, configure credentials, connect a client, and verify your first call |
| [Updating the plugin](update-plugin.md) | Refresh workflows and runtime packages while preserving local edits |
| [Knowledge store](tutorials/KNOWLEDGE_STORE.md) | Configure Weaviate, choose embeddings, and verify stored results |
| [Weaviate skills](weaviate-agent-skills.md) | Use the database skills alongside the plugin's knowledge tools |
| [Explainer companion](../packages/video-explainer-mcp/README.md) | Configure the external video pipeline and render a project |
| [Scene-agent companion](../packages/video-agent-mcp/README.md) | Generate scene code with bounded Claude Agent SDK calls |

The [root README](../README.md) gives the pinned installation routes.
[Metrics notes](metrics/README.md) explain the dated source snapshots and their limits.

## Extend and understand

| Guide | Use it to |
|---|---|
| [Architecture](ARCHITECTURE.md) | Follow requests through validation, providers, sessions, caches, and storage |
| [Diagrams](DIAGRAMS.md) | See the server boundaries and main request flows |
| [Adding a tool](tutorials/ADDING_A_TOOL.md) | Implement and register a tool using the existing contracts |
| [Selected text/frame-video generation](../packages/video-explainer-mcp/docs/integrations/generation.md) | Configure the candidate HTTP route, pinned inputs and explicit recovery; live quality remains open |
| [Image generation, editing and translation](../packages/video-explainer-mcp/docs/integrations/image-generation.md) | Configure the candidate image route and its quote/finalize/poll lifecycle |
| [Optional Qwen image/video contracts](integrations/qwen-video-edit.md) | Inspect the disabled pinned integration, schemas and operating limits |
| [Writing tests](tutorials/WRITING_TESTS.md) | Use mocked fixtures and verify observable behavior |
| [Contributing](../CONTRIBUTING.md) | Prepare a focused change and run its required checks |
| [Security policy](../SECURITY.md) | Understand the trust boundaries and report a vulnerability |
| [Live security validation](tutorials/LIVE_SECURITY_VALIDATION.md) | Separate offline checks from authorized provider and process validation |

## Maintain and release

- [Plugin distribution](PLUGIN_DISTRIBUTION.md) explains Python runtime packages,
  npm workflow assets, and native Codex/Claude discovery.
- [Publishing](PUBLISHING.md) describes artifact preparation and each publication
  destination.
- [Release checklist](RELEASE_CHECKLIST.md) gives the final verification sequence.
- [Changelog](../CHANGELOG.md) records released changes;
  [roadmap](../ROADMAP.md) separates implemented work from proposed work.

## Evidence and historical findings

- [Comprehensive capability programme, September 30, 2026](research/2026-09-30-capability-programme.md):
  expanded source audit, complete transfer coverage, Beads execution map and
  [loop contract](loops/multimodal-capability-programme/LOOP.md). Implementation
  and comparative acceptance remain open under `vrm-0e8`.
- [Open-source landscape, September 30, 2026](research/2026-09-30-open-source-landscape.md):
  Qwen plugins, direct video MCP alternatives, adjacent research/production systems,
  verified source boundaries and prioritized opportunities.
- [September 2026 modernization audit](audits/2026-09-modernization.md): dated
  source decisions, verification results, and limits.
- [Dependency source inventory](audits/2026-09-dependency-sources.json): primary
  registry metadata collected for that audit.
- [Knowledge-ingest UX findings](KNOWLEDGE_INGEST_UX_FINDINGS.md): the conditions and
  results of a specific diagnostic session.
- [Supply-chain report](../.supply-chain-risk-auditor/results.md): bounded advisory
  and dependency-source inspection.

A historical receipt describes the revision and checks it names. Use current
source, registry metadata, and the running MCP configuration to establish what is
available now.
