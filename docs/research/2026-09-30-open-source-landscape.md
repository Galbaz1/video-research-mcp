# Open-source landscape: video research, multimodal plugins and explanation

Observed **September 30, 2026**. Research task: `vrm-59c`.

The subsequent [comprehensive capability programme](2026-09-30-capability-programme.md)
expands the audit to 22 external projects and maps every included useful capability
to implementation and acceptance work under Beads epic `vrm-0e8`. This report
retains the earlier comparison scope and its original evidence limits.

## Assessment

**video-research-mcp has a credible distinction in its combined research workflow:** video understanding, document comparison, grounded web research, academic discovery, reusable knowledge and an explainer handoff. None of the five inspected direct MCP competitors exposes that complete combination. This is a source-backed architectural comparison; it does not establish better answers.

**Qwen is further along in multimodal breadth, source-moment retrieval and packaged outputs.** Its official plugin suite includes long-video and audio-visual memory, editing, tutorial PDFs, demonstration-derived skills, spatial reasoning and several agent-harness installers. Several smaller video MCP projects also expose concrete frames, transcript spans and extraction timestamps that this project's public video interface does not return.

The best opportunity is to make the existing research breadth produce **evidence a user can inspect and reuse**, with measured quality and preserved references through the explainer. Adding more unrelated generation APIs would have less demonstrated value.

The timing distinction is real but bounded: this repository's [first commit](https://github.com/Galbaz1/video-research-mcp/commit/5ea6248bb8a211ef80baa14ad10f27a9352650aa) is February 26, 2026; Qwen-MM-Plugins announces its initial release on August 3. That establishes an earlier start than this official Qwen suite, not priority over the entire video/research ecosystem. [Qwen release history](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/README.md).

## Method and evidence limits

Three independent researchers owned disjoint areas: Qwen; direct video/research MCP competitors; adjacent research and video-production systems. The primary researcher verified this project's baseline, joined all three lanes, and synthesized their findings. Sources were primary repositories, implementation files, GitHub metadata and package registries.

- **Confirmed:** a capability, restriction, revision or artifact directly observed in source or authoritative metadata.
- **Derived:** a comparative conclusion inferred from those observations, scoped to the inspected projects.
- **Unmeasured:** answer accuracy, retrieval recall, end-to-end reliability, cost, latency, adoption and creative quality. No installation journeys, paid inference, generation or comparative benchmarks ran in this study.

Code presence proves implementation, not successful operation. Current source and a released registry package may differ; material differences are retained below. Tool counts and stars were not used as quality rankings. This is a bounded shortlist, not an exhaustive census.

## Current project baseline

The baseline is GitHub main **`a3d75f6ab87bd893c7d167394fb5bace717f23ec`**, verified through the live GitHub API. The clean implementation worktree initially had a handoff-only commit above that source. The original dirty `feat/local-video-windowing` checkout was preserved and was not substituted for the public release.

| Confirmed capability | Practical boundary |
|---|---|
| Native Gemini analysis of YouTube or local video; instruction-driven default structured output and optional custom schema | The public tool has no start/end/FPS controls. Its default timestamps are model-generated descriptions, not returned source frames or measured segment evidence. |
| Video sessions, optional SQLite persistence, result/upload/context caches | Useful reuse mechanisms; conversation caching is different from indexing source utterances, frames and events for cross-video retrieval. |
| Document mapping, evidence extraction, cross-reference and synthesis; structured document/page citations | Citation fields and evidence labels remain model-generated and require source checking. |
| Grounded web search; provider-managed cited background research with status/follow-up/cancel | `research_deep` is a separate three-prompt synthesis path with no search-tool wiring. It must not be treated as equivalent to `research_web`. |
| Semantic Scholar papers, authors, citations/references and recommendations | Metadata discovery is separate from obtaining and reading full text. |
| Optional Weaviate storage across research domains, concept graph, hybrid search, reranking and recall | Stores mainly derived results. Writes are best-effort; a successful analysis is not proof of persistence. |
| Independent explainer and scene-agent MCP companions | Renderer installation and providers are separate. Rendering/refinement machinery is largely inherited from upstream `video_explainer`. |
| Standard stdio MCP, input policies, bounded jobs, CI and release checks | The npm workflow installer targets Claude Code. Other clients can use MCP but do not receive equivalent native workflow installation. |

These observations are supported by the [architecture](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/docs/ARCHITECTURE.md), [public video contract](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/src/video_research_mcp/tools/video.py), [video storage](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/src/video_research_mcp/weaviate_store/video.py) and [research implementation](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/src/video_research_mcp/tools/research.py).

The exact-source [main CI run](https://github.com/Galbaz1/video-research-mcp/actions/runs/36682488841) completed successfully. It exercises mocked provider tests, installer/security/release contracts and a built-wheel MCP smoke check. This is a solid engineering base, not a comparison of research outcomes. The optional strict-video gates check structural properties, including timestamp order and the final timestamp relative to stated duration; they do not establish actual video coverage or claim support. [CI definition](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/.github/workflows/ci.yml), [quality gates](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/src/video_research_mcp/contract/quality.py).

## What Qwen offers

The official target is **[QwenLM/Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins)**, inspected at `07736672525443c7f8a3f6405eed37d2236f023f` (September 23). It is Apache-2.0. Its release index declares distribution 1.1.9 and fourteen independently versioned capabilities. Installs resolve capability-specific tags; inspecting main does not establish byte identity with every tagged release. [Release index](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/plugin-versions.json).

| Capability | Source-confirmed offering |
|---|---|
| [core](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/core) | Timestamped video frames, image crop/annotation, media metadata and document/data/3D visualization for the host model. |
| [api](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/api) | Vision, OCR, grounding, audio-visual analysis, transcription, ASR and segmentation through model services. |
| [search](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/search) | Web/page and reverse-image search through several providers. |
| [video-memory](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/video-memory) | Hierarchical long-video memory and event/entity/OCR/time retrieval. |
| [omni-memory](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-memory) | People, utterances, facts, acoustic events and clip records; hybrid retrieval, replay and resumable memory building. |
| [video-edit](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/video-edit) | Image/video/audio generation and editing workflows with timeline/render checks. |
| [omni-chatcut](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-chatcut) | Music videos, movie commentary and video translation/dubbing workflows. |
| [omni-video2note](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-video2note) | Tutorial recording to illustrated PDF notes with timeline screenshots. |
| [omni-skill-creator](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-skill-creator) | Demonstration video to agent skill, annotated assets and provenance/structure validation. |
| [video-spatio](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/video-spatio) | Spatial scene/relationship/motion geometry based on model-supplied observations. |
| [edu-agent](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/edu-agent) | Chinese math/science explainer videos and interactive pages; skill rather than a separate MCP server. |
| [blender](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/blender) | Operate a running Blender for modeling, materials, lighting and rendering. |
| [freecad](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/freecad) | Operate a running FreeCAD for parametric CAD and FEM. |
| [mhs](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/mhs) | Owner-operated hardware adapters with declared limits and health/reset controls. |

The important competitive difference is concrete source access. Qwen's [video reader](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/core/qwen_mm_plugins_core/readers/video.py) exposes windows, FPS and frame/resolution budgets and returns actual sampled frames. Its [AV memory](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-memory/qwen_mm_plugins_omni_memory/mem_core.py) implements local stores, entity links and BM25/dense retrieval. These are real infrastructure beyond a summarization prompt. They still depend on inferred captions, facts and identities; extraction explicitly lacks an acoustic diarization step. [Extraction stages](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-memory/skill/script/build_memory/stages.py).

Qwen also has a wider adoption surface: seven guided harnesses, additional manual integrations, modular installs, configuration verification and rollback. Native frame emission uses the host model; compatible API endpoints can support self-hosting. Memory, generation and TTS default to external services, while rendering needs additional system applications. A local plugin does not establish local inference. [Installation](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/docs/en/installation.md), [configuration](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/docs/en/configuration.md).

Source checks qualify three claims: the current video2note handler excludes final model-based PDF review; dense omni-memory queries can incur embedding calls despite prose describing subsequent answers as free; spatial scene assembly uses model-estimated boxes/depth and fixed field of view, so it is not independent physical measurement. [PDF handler](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-video2note/qwen_mm_plugins_omni_video2note/tools/create_video_note.py), [memory configuration](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-memory/qwen_mm_plugins_omni_memory/config.py), [scene builder](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/video-spatio/qwen_mm_plugins_video_spatio/tools/build_scene.py).

The inspected Qwen search module has search/page extraction, but no equivalent bundled Semantic Scholar suite, YouTube metadata/comments/playlists or provider-managed cited deep-research workflow was found. This is an absence within this repository, not the entire Qwen ecosystem. [Search handler](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/search/qwen_mm_plugins_search/tools/web_search.py).

## Other projects worth comparing

Capabilities below are confirmed in inspected source; their comparative significance is derived. Complete source identities and distribution caveats follow the table.

| Project | Strongest relevant offering | How this project compares |
|---|---|---|
| [VidLens](https://github.com/thatsrajan/vidlens-mcp) | Persistent transcript/comment collections, media assets, frame-backed visual search, social/local ingestion and Claude/Codex setup. | More developed video-library and source-frame journey; narrower research-domain integration. Visual semantic search embeds descriptions/OCR rather than images themselves. |
| [mcptube](https://github.com/0xchamin/mcptube) | Automatically merged entity/topic/concept wiki, history, illustrated reports and Markdown/HTML export; cloud-provider selection through LiteLLM. | A stronger visible example of knowledge accumulating across recordings. Automatic wiki building requires an LLM; retrieval is FTS plus model reasoning. |
| [YouTube Video Analyzer](https://github.com/ludmila-omlopes/youtube-video-analyzer-mcp) | Published clip offsets, adaptive FPS/token planning, long-video MCP tasks and reusable sessions. | Further along in explicit long-video execution controls; Gemini-only and narrower in research breadth. |
| [Video Context MCP](https://github.com/smallthinkingmachines/video-context-mcp) | Local captions/Whisper, keyframes/OCR, hybrid speech/screen retrieval, frame inspection and cropping. | A complementary evidence backend. It leaves reasoning to the host model and distinguishes requested from actual frame time. |
| [MCP Video Analyzer](https://github.com/guimatheus92/mcp-video-analyzer) | Broad platform/local adapters, captions/Whisper, scene/dense frames, OCR, timeline and resumable batch sidecars. | Broader extraction/source coverage; no persistent semantic video corpus in this MCP. |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | General web/local/hybrid research, multiple model providers, MCP consumption and inspectable outcome-evaluation machinery. | More provider-flexible general research and more explicit evaluation. This project's video tools can be a specialized input to it. |
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research) | Configurable LangGraph research and groundedness/correctness/completeness evaluators. | Useful design/evaluation reference; archived August 21, 2026. |
| [VideoRAG / Vimo](https://github.com/HKUDS/VideoRAG) | Persistent cross-video segment, graph and vector retrieval; source video/time context and desktop chat. | Stronger inspected corpus-first architecture. Its current integrated implementation is explicitly noncommercial because of ImageBind. |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | Topic/script-to-short-video WebUI/API/CLI, materials, narration, subtitles, music and provider integrations. | Broader short-form production UX. Research-grounded technical explanation is a distinct opportunity. |
| [video_explainer](https://github.com/prajwal-y/video_explainer) | Remotion scenes, narration/storyboards, source-oriented factchecking and refinement. | This project's existing renderer dependency, rather than an independent rival to its wrapper. Those production features are inherited. |

For concrete implementation evidence, see [VidLens visual search](https://github.com/thatsrajan/vidlens-mcp/blob/edd1d9fba8cf2364343b4cbd07378a649f956f08/src/lib/visual-search.ts), [mcptube wiki storage](https://github.com/0xchamin/mcptube/blob/e619bc1c0ab425ecb7b214819b9f434fdf4809a3/src/mcptube/wiki/storage.py), [published long-video planning](https://github.com/ludmila-omlopes/youtube-video-analyzer-mcp/blob/27682c62b4f37b70a8b02ad4118599824580d7c5/src/lib/analysis.ts), [Video Context frame contract](https://github.com/smallthinkingmachines/video-context-mcp/blob/4f39f0312401bc428f07dcd69da6b757daf3e441/src/tools/peek-frame.ts), [Analyzer timeline](https://github.com/guimatheus92/mcp-video-analyzer/blob/9e476c02f8426f5c277ed5e7f5729c1aee75b31a/src/tools/analyze-core.ts), [VideoRAG retrieval](https://github.com/HKUDS/VideoRAG/blob/c412a093a820ef7a0e0dda31076ed871136198b3/VideoRAG-algorithm/videorag/_op.py) and [MoneyPrinterTurbo task lifecycle](https://github.com/harry0703/MoneyPrinterTurbo/blob/44e6d5e11832beccc2c3ce6b139bf437e920bb6a/app/services/task.py).

## Where the current project is stronger

1. **Research integration across source types.** The direct shortlist concentrates on video extraction, transcripts, library search or wiki creation. This project also has document cross-reference, academic citation discovery and provider-managed web research. Its advantage is fewer manual boundaries when one question needs a recording, a paper and a document together. That advantage remains a workflow hypothesis until demonstrated end to end.
2. **A reusable research store spanning domains.** Optional Weaviate links analyses, findings and concepts beyond video. Competitors have strong video stores; this project's broader schema is useful for research continuity. It is not equivalent to their finer source-moment retrieval.
3. **An agent-facing path into technical explanation.** Existing research and explainer companions create a useful integration surface. However, the current [bridge command](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/commands/explain-video.md) requests facts and sources in manually synthesized Markdown; it does not enforce claim-to-scene provenance. Topic input also routes to `research_deep`, so grounding must be selected deliberately.
4. **An inspectable engineering base.** Typed defaults, explicit errors, input policies, bounded companion jobs, tests, release contracts and exact-source CI are concrete assets. They support predictable integration. They do not prove greater factual accuracy, security or reliability than every competitor.

These strengths justify positioning the project around **recordings and documents becoming inspectable research, reusable knowledge and source-linked explanations**. Generic research and media production each have substantial competitors already.

## Prioritized opportunities

| Priority | Opportunity | Smallest credible validation | What would establish value |
|---|---|---|---|
| 1 | **Inspectable video evidence** | Compose one existing local extractor with the current analysis workflow. Return source identity/hash, an actual frame/clip and its extraction time, nearby transcript/OCR and the associated claim. | A reviewer can open the cited moment and determine whether it supports the answer. Requested and actual frame times remain distinct. |
| 2 | **Reproducible outcome evaluation** | Freeze a small licensed recording/document/question set, revisions, provider settings and attempt/spend bounds before any run. Include visual-only facts, timing, contradictions and missing evidence. | Supported-claim precision, timestamp correctness, omissions, abstention, task completion and cost/latency are reported separately. Failures remain in the denominator. |
| 3 | **Evidence preserved into explanation** | Carry the same source/claim IDs into a script and storyboard; inspect additions before rendering one explanation. | Claims in the final artifact can be traced to their source, with unsupported additions and draft claims visible. Renderer success remains separate from factual acceptance. |
| 4 | **Long-video and corpus reuse** | Expose a bounded window using existing helper support, then test repeated questions over a fixed small video set before selecting a new retrieval stack. | Correct source moments are reused, long jobs have actionable status, and repeated-question cost is measured. Bypass the current result cache when varying schema/thinking settings. |
| 5 | **Portable onboarding and useful outputs** | Prove one native Codex workflow and one source-linked illustrated note or demonstrated-process checklist. | A new user reaches the outcome through verified setup, can inspect sources, and can distinguish a drafted skill from an execution-verified one. |

Evaluation is a genuine competitive gap. GPT Researcher includes a seeded Deep Research Bench harness, fixed comparison settings and saved FACT/RACE artifacts. Its authors report roughly **56% citation precision on ten tasks**—35.2 supported citations from 62.9 citations per report. Those are author-reported, unreproduced results for other systems. They illustrate why citation abundance and green unit tests need a separate outcome evaluation. [Method/results](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/deep_agents/BENCHMARK.md), [harness](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/deep_agents/drb_generate.py). Open Deep Research provides reusable evaluation ideas for [groundedness and correctness](https://github.com/langchain-ai/open_deep_research/blob/1b7d2e80db9faa586165c60e09096dbbfd483a64/tests/evaluators.py), subject to its archived status.

The current cache key excludes schema and thinking settings; controlled evaluations should set `use_cache=False` when these vary. A late final timestamp is not evidence of full recording coverage. [Cache and validation boundaries](https://github.com/Galbaz1/video-research-mcp/blob/a3d75f6ab87bd893c7d167394fb5bace717f23ec/docs/ARCHITECTURE.md).

The first integration candidates are Video Context or MCP Video Analyzer for local evidence, maintained research engines as clients of the specialized MCP, and existing renderers for production. Model/provider flexibility can initially come from passing extracted evidence to the host model. This tests demand without committing to a broad provider framework.

## Source identities, release and license boundaries

This ledger preserves reproducibility. Activity dates are commit observations, not support guarantees. Model weights, cloud APIs and media assets have separate terms from application code.

| Project | Source examined | Distribution / license caveat |
|---|---|---|
| video-research-mcp | `a3d75f6ab87bd893c7d167394fb5bace717f23ec` | MIT; core 0.7.1 and companions 0.2.1. Study concerns public source, not the user's older running installation. |
| Qwen-MM-Plugins | `07736672525443c7f8a3f6405eed37d2236f023f` | Apache-2.0; distribution 1.1.9; independently versioned plugin tags. |
| VidLens | `edd1d9fba8cf2364343b4cbd07378a649f956f08` | MIT; main 1.5.2 vs npm 1.5.1 at `ec4076274f9fb77230d47468e8c3b4fb5f6111d7`. Source/install differences are not treated as verified npm behavior. |
| mcptube | `e619bc1c0ab425ecb7b214819b9f434fdf4809a3` (`vision`) | Source/PyPI 0.2.1 declare MIT; standalone license text absent from inspected branch. |
| YouTube Video Analyzer | `cdb00e98fcfe6198f209cc69288a2cdc3b495f58`; npm source `27682c62b4f37b70a8b02ad4118599824580d7c5` | MIT; main 0.3.0 vs npm 0.2.1. Offsets/long tasks/sessions are published; newer exact-frame/audio/compatibility-job tools are main-only. |
| Video Context MCP | `4f39f0312401bc428f07dcd69da6b757daf3e441`; npm source `78ca2c41444495d8f4b0e960424e7ab252e9c218` | MIT; source/npm 0.8.0, with follow-up source changes. Local extraction leaves interpretation to the host model. |
| MCP Video Analyzer | `9e476c02f8426f5c277ed5e7f5729c1aee75b31a`; npm source `e684edf16a2860e73d138653c0c3cf7a4cf2d6fd` | MIT; source/npm 0.10.1. Inspected capability source unchanged since registry revision; later lock/security changes exist. |
| GPT Researcher | `0957c301ed06c2a5857b834358c7227c739041d4` | Root license Apache-2.0; package metadata still says MIT. Record the discrepancy. |
| Open Deep Research | `1b7d2e80db9faa586165c60e09096dbbfd483a64` | MIT; archived August 21, 2026. |
| VideoRAG / Vimo | `c412a093a820ef7a0e0dda31076ed871136198b3` | MIT framework architecture; complete current implementation explicitly noncommercial because of ImageBind. [License notice](https://github.com/HKUDS/VideoRAG/blob/c412a093a820ef7a0e0dda31076ed871136198b3/LICENSE). |
| MoneyPrinterTurbo | `44e6d5e11832beccc2c3ce6b139bf437e920bb6a` | MIT app; provider/media terms separate. |
| video_explainer | `c033e28d6eccae43c1762f4653f9c320b16b050e` | Pinned dependency README claims MIT, but recursive tree has no LICENSE/COPYING/NOTICE and LICENSE endpoint returns 404. The license grant remains unverified. [Pinned README](https://github.com/prajwal-y/video_explainer/blob/c033e28d6eccae43c1762f4653f9c320b16b050e/README.md). |

Primary registry metadata was inspected for [VidLens](https://registry.npmjs.org/vidlens-mcp), [YouTube Analyzer](https://registry.npmjs.org/@ludylops%2fyoutube-video-analyzer-mcp), [Video Context](https://registry.npmjs.org/@smallthinkingmachines%2fvideo-context-mcp), [MCP Video Analyzer](https://registry.npmjs.org/mcp-video-analyzer) and [mcptube](https://pypi.org/pypi/mcptube/json). GPT Researcher's [source license](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/LICENSE) and [package metadata](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/pyproject.toml) substantiate that discrepancy. These are observations, not legal adjudications.

The community [adamanz/qwen-video-mcp-server](https://github.com/adamanz/qwen-video-mcp-server/blob/4eb23d237c431c67994320e13717224838a4f732/server.py) was also checked: eight prompt-oriented tools calling externally deployed Modal endpoints, capped at 64 frames; backend absent and license unresolved. Its hours-long/full-recall claim is not established by wrapper code. It is substantially narrower than the official Qwen suite.

Search also considered smaller Gemini/VideoSeek wrappers; stronger comparables covered their relevant product shapes. The referenced `qiyun-kxc/vision-video-mcp` returned GitHub 404, so it was not scored. No ecosystem-wide uniqueness or comparative performance claim is made.
