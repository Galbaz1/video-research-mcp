# Comprehensive capability transfer programme

Audit date: September 30, 2026. Beads programme: **`vrm-0e8`**. This expands the
[earlier landscape comparison](2026-09-30-open-source-landscape.md) into a complete
implementation and acceptance packet for the included projects. It is preparation;
no new runtime feature, provider experiment or comparative performance result is
claimed here.

## Scope and coverage

Three independent source-family audits were completed and joined, then reconciled
with current public source and unpublished repository work. The inventory covers
**22 external repositories**, all **14 Qwen capability families**, and **85 transfer
units**. Overlapping units share implementation work: **74 leaf work packages** sit
under nine capability/acceptance epics. The graph has **149 blocking links**, using
transitive reduction while retaining each declared prerequisite.

The [machine-readable inventory](2026-09-30-capability-transfer.json) retains exact
revisions, source paths/URLs, license evidence, reuse decisions, target responsibility,
runtime requirements, risks, acceptance criteria, public tools/workflows, omissions,
and each unit's Bead. It maps **400 namespaced tool references** and **191 workflow
references**. These are audited upstream surfaces, not promised new tool counts.
Twenty-four direct-lane entries are official TwelveLabs documentation references to
external implementations; 186 are source-registered direct tools, including two
conditional VidLens tools. Those evidence classes remain separate.

The earlier comparison's community
[Qwen wrapper](https://github.com/adamanz/qwen-video-mcp-server/blob/4eb23d237c431c67994320e13717224838a4f732/server.py)
was rechecked too. Its eight tools and metadata resource are recorded separately as
overlap references, mapped to existing perception, image, speech/OCR, synthesis,
grounded-answer and onboarding packages. Its missing backend, unresolved copy grant,
64-frame cap and unproved recall/timestamp claims warrant no extra wrapper runtime.

This is a bounded source audit, not proof that every internet repository was found.
Unavailable leads and overlapping candidates have explicit dispositions. STORM's
research perspectives/reporting, generic memory stacks and raw rendering libraries
were considered; their useful outcomes are represented without adding duplicate
runtime dependencies. An advertised Vision OCR semantic-structure tool absent from
registration is excluded as an unsupported claim. External hosted inference is not
classified as open-source inference.

## Substantial omissions added

- [Watch Skill](https://github.com/oxbshw/watch-skill/tree/f1317c8fe64744a606c31867b05fbbe3144268c6):
  persistent timestamped AV evidence, source freshness, durable lease/CAS jobs,
  correction replay, bounded live evidence and deterministic completion contracts.
- [whosaid](https://github.com/sblattj/whosaid/tree/f7e100d1f04b108b322378b6c43534e27a19eab2):
  local transcription/diarization, speaker enrollment/correction, scoped workspace
  indexing and source-linked meeting commitments.
- [Omni Image](https://github.com/alexlivre/omni-image-tools-mcp/tree/4d191573b7e459519c3ec9414ade744456115a5a),
  [Media Context](https://github.com/vishalguptax/media-context-mcp/tree/2cc68be304d7151f2a980fc59940938d2fa20b72)
  and [Vision OCR](https://github.com/stelaino/vision-ocr-mcp/tree/4c9225ca81d1c237901d7c58a6b32f7895968415):
  bounded image preparation/crops, dense filmstrips, temporal/numeric OCR and native
  PDF/region/barcode/document-boundary tools.
- [Audio Analyzer](https://github.com/JuzzyDee/audio-analyzer-rs/tree/0387fe1630ff0fc7f71bf656be81f3b1f400dda8)
  and [Ferrous Waves](https://github.com/willibrandon/ferrous-waves/tree/d28ec11361123eb3778454deddf164f1fb6d25e4):
  optional measured DSP, reference comparison, fingerprints and bounded visual artifacts.
- [Deep Agents](https://github.com/langchain-ai/deepagents/tree/1756bbe1eb348e20b925598ed49665b0d34b4b2d),
  [LightRAG](https://github.com/HKUDS/LightRAG/tree/453dce83d6d0354a06e46c8d4029a0895c4e054b)
  and [Open Notebook](https://github.com/lfnovo/open-notebook/tree/3127f14ea9dbb519f0e4ddc64a0742ca644ba6ef):
  retained original context, checkpoint/store recovery, graph/vector retrieval,
  ingestion lifecycle, notebook-scoped knowledge and multi-speaker podcast jobs.
- [TwelveLabs client plugin](https://github.com/twelvelabs-io/twelve-labs-claude-code-plugin/tree/c9d4936dbee87ecfd4fb8c54f7369d9b83439f14):
  optional hosted-service interoperability, with source/client/service boundaries explicit.

The expanded Qwen audit retains the peripheral families too: document/data/code/3D/
GIS/NIfTI previews, segmentation, music videos, commentary, dubbing, educational
pages/videos, spatial reasoning, Blender, FreeCAD/FEM and hardware adapters. The
production audit retains planning, timing, refinement, factchecking, subtitles,
shorts, local/stock assets, music/SFX, provider generation, UI/API/CLI and publication
receipts. An optional integration is still a complete product task, with installation,
discovery, errors and actual supported journeys; configuration examples alone do
not finish it.

## Product shape and reuse decisions

Extend the existing research server and companions. Keep original source identity,
observed media spans and claim references continuous through perception, retrieval,
research, narration, scenes and final exports. Shared capability logic should be
implemented once. Use existing clients, source policies, typed contracts and job
behavior before adding new layers. Proposed source-lane paths are responsibility
suggestions; they do not require creating every proposed module.

Import supported dependencies when that is the smallest credible complete solution.
Adapt permissive feature code with exact notices. Use independently authored behavior
or cleared assets where the first copy route is unsuitable. Heavy local models,
foreign MCP stacks, CAD, hardware and provider services remain opt-in isolated
processes with pinned readiness evidence. Shared registration/config/client/lock and
release edits belong to the coordinator when work is parallel.

Copy clearance is per file/component, not per repository badge. Qwen Blender/FreeCAD
contain MIT-derived portions, selected fonts have OFL terms, and Smiley Sans metadata
says its license is unknown. mcptube's MIT declaration lacks a grant file. The pinned
renderer lacks a license file despite its README label. GPT Researcher's root Apache
license conflicts with MIT package metadata. ImageBind and MusicGen weight paths
have noncommercial restrictions. Keep those direct copy/model routes blocked until
resolved; retain functionality through permitted alternatives. The licensing item
also checks transitive executable/model/service terms before bundling.

Do not import known weaknesses: provider-blind image cache keys, path/mtime/size
identity masquerading as a content digest, model self-certainty renamed as calibrated
confidence, approximate indexed frames renamed exact, unperformed PDF review,
source-only exports presented as registry availability, or a tool confirmation flag
presented as human device authority. The inventory carries the exact source evidence
and corresponding negative acceptance checks.

## Reconcile existing work first

Public runtime baseline is `a3d75f6ab87bd893c7d167394fb5bace717f23ec`: 34 core tools,
15 explainer tools and two scene-agent tools. Preparation starts from `9664f20` on
`codex/multimodal-capability-programme` in the modernization worktree. The original
checkout remains `feat/local-video-windowing` at `bd980e8`, with its unrelated dirty
files protected.

Local windows and retry-safe upload caching already exist in unpublished commits
`e326fde`/`bd980e8`; reconcile those behaviors against modern source. Do not merge the
old branch wholesale. Evaluate Interactions experiment `0004342` against cache,
security, schema and persistence contracts; deletion of existing cache tests cannot
establish equivalence. Old model-default-only changes are not a current default
recommendation. Unpublished own-source GitHub URLs may not resolve; local refs are
their authority.

## Execution map

Beads owns status and readiness. This table is a static scope index, not a task board.

| Capability family | Parent Bead | Leaf work packages |
|---|---|---:|
| Foundation | `vrm-0e8.2` | 11 |
| Media | `vrm-0e8.3` | 8 |
| Audio | `vrm-0e8.4` | 4 |
| Research | `vrm-0e8.5` | 6 |
| Memory | `vrm-0e8.6` | 8 |
| Knowledge | `vrm-0e8.7` | 8 |
| Production | `vrm-0e8.8` | 18 |
| Optional | `vrm-0e8.9` | 8 |
| Acceptance | `vrm-0e8.10` | 3 |

After preparation closure, the first eligible leaves are `vrm-0e8.2.7` (freeze the
evaluation protocol) and `vrm-0e8.2.6` (reuse/license routes). They can proceed
independently. Then establish `vrm-0e8.2.10` (baseline regression fixtures) and
`vrm-0e8.2.8` (source/evidence/MCP contracts). `vrm-0e8.2.2` covers complete cache
identity, and `vrm-0e8.3.1` reconciles unpublished windows after its actual graph
prerequisites. Choose later work from live leaf readiness, never from table order.

The three terminal gates are `vrm-0e8.10.1` (whole-product journeys/build/install),
`vrm-0e8.10.2` (sealed comparative acceptance) and `vrm-0e8.10.3` (verified release).
The main epic stays open until all required outcomes and evidence exist. No-op proof
is acceptable for behavior already present; a mock, untested optional runtime or
permitted replacement plan is not a completed live journey.

Use the [loop execution contract](../loops/multimodal-capability-programme/LOOP.md)
and canonical `.claude/handoff.md`. The loop is observe, choose one complete slice,
act, verify, record in its Bead, then continue or stop from fresh evidence. It inherits
configured models, uses bounded useful independent work, joins required lanes and
stops a repeated infrastructure failure after one controlled intervention. This
preparation installs no scheduler or unattended worker.

## Proving the requested advantage

Freeze strong per-workflow baselines, original evidence, evaluator, cases, failure
denominator, material advantage thresholds and non-regression constraints before
implementation tuning. Keep development and independently retained held-out cases
separate. Preserve failures/refusals/abstentions; measure support, correctness,
coverage, completion, efficiency and maintenance separately. Freeze the candidate
before acceptance. Any held-out set used to tune a new candidate is retired.

The target includes visual facts, speech, temporal relations, long recordings,
cross-video recall, contradictions, missing evidence, artifact lineage, restart and
optional capability journeys. Source/human checks and uncertainty are required for
comparative claims. Feature count and third-party published scores cannot show that
this product is superior. Negative comparisons leave the epic incomplete.

The user grants time and unlimited agent tokens. Live provider spend, recording,
source uploads, hardware and content publication still use concrete applicable
authority. `vrm-0e8.2.9` prepares capability/resource/run plans; offline work continues
while a missing live input is resolved. Prior source-push authority persists.

## Reproduce preparation checks

```bash
uv run python scripts/validate_capability_programme.py
bd dep cycles
bd ready --parent vrm-0e8 --exclude-type epic --limit 0 --json
```

The checker rejects orphan tools/workflows/units, ambiguous primary mappings,
unmapped overlap-candidate surfaces, missing/cyclic or weakened prerequisites,
missing live Beads IDs/parents, changed
blocking edges and weakened acceptance text. Negative tests cover omitted tools,
orphan units, weakened transitive prerequisites, cycles and unmapped overlap surfaces.
Current statuses are
read from the local Beads database; no remote Beads synchronization is implied.

The independent review identified two checker weaknesses, with no current mapping
or live contract omission: coordinated edits could remove an entire source unit
or weaken package acceptance/prerequisites. Those reproductions now fail. The
checker anchors source contracts and identities to fingerprints of all four
terminal audit packets, verifies retained tool inventories and population counts,
and requires source-unit criteria and effective prerequisites in package contracts.
Overlap population is frozen separately. Nine negative tests include coordinated
unit removal, both dependency summaries removed, empty TTS criteria and deletion
of the overlap candidate. An intentionally changed source audit is a new baseline;
it must not silently rewrite these fingerprints. These are preparation checks,
not media-quality or comparative performance results.

## Pinned external source inventory

Per-unit paths, additional sources, registry gaps and license URLs are in the JSON.
The following identities establish the source audit, not installed runtime proof.

| Repository | Audited revision | Observed license boundary |
|---|---|---|
| [QwenLM/Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f) | `0773667` | Apache-2.0 original project code; MIT Blender/FreeCAD vendored and derived code; OFL-1.1 ChatCut Noto font and selected video-edit fonts; MIT notice in LXGW directory; Smiley Sans metadata says unknown license. No blanket asset/model reuse clearance. |
| [thatsrajan/vidlens-mcp](https://github.com/thatsrajan/vidlens-mcp/tree/edd1d9fba8cf2364343b4cbd07378a649f956f08) | `edd1d9f` | MIT |
| [0xchamin/mcptube](https://github.com/0xchamin/mcptube/tree/e619bc1c0ab425ecb7b214819b9f434fdf4809a3) | `e619bc1` | MIT declared; grant file absent |
| [ludmila-omlopes/youtube-video-analyzer-mcp](https://github.com/ludmila-omlopes/youtube-video-analyzer-mcp/tree/cdb00e98fcfe6198f209cc69288a2cdc3b495f58) | `cdb00e9` | MIT |
| [smallthinkingmachines/video-context-mcp](https://github.com/smallthinkingmachines/video-context-mcp/tree/4f39f0312401bc428f07dcd69da6b757daf3e441) | `4f39f03` | MIT |
| [guimatheus92/mcp-video-analyzer](https://github.com/guimatheus92/mcp-video-analyzer/tree/9e476c02f8426f5c277ed5e7f5729c1aee75b31a) | `9e476c0` | MIT |
| [oxbshw/watch-skill](https://github.com/oxbshw/watch-skill/tree/f1317c8fe64744a606c31867b05fbbe3144268c6) | `f1317c8` | MIT |
| [sblattj/whosaid](https://github.com/sblattj/whosaid/tree/f7e100d1f04b108b322378b6c43534e27a19eab2) | `f7e100d` | MIT |
| [alexlivre/omni-image-tools-mcp](https://github.com/alexlivre/omni-image-tools-mcp/tree/4d191573b7e459519c3ec9414ade744456115a5a) | `4d19157` | MIT |
| [JuzzyDee/audio-analyzer-rs](https://github.com/JuzzyDee/audio-analyzer-rs/tree/0387fe1630ff0fc7f71bf656be81f3b1f400dda8) | `0387fe1` | MIT |
| [willibrandon/ferrous-waves](https://github.com/willibrandon/ferrous-waves/tree/d28ec11361123eb3778454deddf164f1fb6d25e4) | `d28ec11` | MIT |
| [vishalguptax/media-context-mcp](https://github.com/vishalguptax/media-context-mcp/tree/2cc68be304d7151f2a980fc59940938d2fa20b72) | `2cc68be` | Apache-2.0 |
| [stelaino/vision-ocr-mcp](https://github.com/stelaino/vision-ocr-mcp/tree/4c9225ca81d1c237901d7c58a6b32f7895968415) | `4c9225c` | MIT |
| [twelvelabs-io/twelve-labs-claude-code-plugin](https://github.com/twelvelabs-io/twelve-labs-claude-code-plugin/tree/c9d4936dbee87ecfd4fb8c54f7369d9b83439f14) | `c9d4936` | MIT client plugin only |
| [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher/tree/0957c301ed06c2a5857b834358c7227c739041d4) | `0957c30` | Apache-2.0 root LICENSE; pyproject metadata incorrectly says MIT |
| [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research/tree/1b7d2e80db9faa586165c60e09096dbbfd483a64) | `1b7d2e8` | MIT; archived 2026-08-21 |
| [HKUDS/VideoRAG](https://github.com/HKUDS/VideoRAG/tree/c412a093a820ef7a0e0dda31076ed871136198b3) | `c412a09` | MIT architecture; current integrated ImageBind implementation explicitly noncommercial |
| [prajwal-y/video_explainer](https://github.com/prajwal-y/video_explainer/tree/c033e28d6eccae43c1762f4653f9c320b16b050e) | `c033e28` | UNRESOLVED: README says MIT but no LICENSE/COPYING/NOTICE exists in pinned tree; no code copying/import |
| [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo/tree/44e6d5e11832beccc2c3ce6b139bf437e920bb6a) | `44e6d5e` | MIT application; cloud/media-service and asset licenses separate |
| [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents/tree/1756bbe1eb348e20b925598ed49665b0d34b4b2d) | `1756bbe` | MIT SDK; optional execution/sandbox services separate |
| [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG/tree/453dce83d6d0354a06e46c8d4029a0895c4e054b) | `453dce8` | MIT; parser/model/server dependencies retain separate licenses |
| [lfnovo/open-notebook](https://github.com/lfnovo/open-notebook/tree/3127f14ea9dbb519f0e4ddc64a0742ca644ba6ef) | `3127f14` | MIT; SurrealDB/content-core/podcast/TTS dependencies separate |
