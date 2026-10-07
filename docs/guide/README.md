# Video Research: from problem to solution

[English](README.md) · [Nederlands](README.nl.md)

English text version of the [interactive guide](https://galbaz1.github.io/video-research-mcp/guide/).
This guide describes release candidate RC6/RC4. Source links point to the
fixed tag `v0.8.0-rc.6`. Check the release and requirements for each route.
Local-model qualification is outside the scope of this API release.

The core server has 120 tools; the separately connected explainer and agent servers
have 39 and two tools. The package contains 26 skills. Start with
[installation and configuration](https://github.com/Galbaz1/video-research-mcp/blob/main/docs/tutorials/GETTING_STARTED.md).
Choose your problem below, check the requirements and follow the steps.

Stock search/download is not connected. Local ASR intake timing and the
retained renderer timing failure remain open. Provider quality, full
security review and broad comparative acceptance have not been established.
The HTTP image/video routes do not require an upstream CLI; other pipeline functions
have their own requirements. Verify model results against the source.

All exact entry points are in [catalog.en.json](catalog.en.json); routes are in
[journeys.en.json](journeys.en.json). [Technical documentation](../README.md) ·
[Report an issue](https://github.com/Galbaz1/video-research-mcp/issues).

## Understand a video

**Problem:** What does this video say about my question?

**Result:** A focused analysis with source moments, uncertainties and follow-up questions.

**Requires:** Core server and Gemini; YouTube Data API only if you want to fetch metadata.

**First prompt:**

```text
Analyze this video: <YouTube-URL>. Explain how <topic> works. Cite source moments, state what is not visible and ask two follow-up questions.
```

- **Choose the source.** Use metadata for a YouTube video; pass a local file directly to the analysis route. [video_metadata](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube.py#L81)
- **Analyze with focus.** Use video_analyze for one source; choose windows for a long file or batch for multiple local files. Batch selects locally, but provides the video files to Gemini for potentially paid analysis. [video_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L117), [video_analyze_windows](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_windows.py#L23), [video_batch_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_batch.py#L31)
- **Ask follow-up questions.** Create a session only for multiple questions and reuse its context. [video_create_session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L426), [video_continue_session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L550)

## Convert speech to text

**Problem:** I want a transcript with timestamps.

**Result:** Subtitle or transcription lines with provenance, export and retained partial results.

**Requires:** Local source and any subtitles; FFmpeg/ffprobe for audio. ASR requires an explicit backend. Local ASR does not yet have a qualified total intake deadline.

**First prompt:**

```text
Transcribe <file>. Use my subtitles first. Show timestamps and missing sections. Ask for consent and name the backend before ASR.
```

- **Check source and audio.** Inspect the local file and determine which interval is needed. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L28)
- **Choose subtitles or ASR.** Subtitles take precedence. Model words and speaker labels remain interpretations. [audio_transcribe](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/audio_transcribe.py#L27)
- **Store only if wanted.** Ingest the transcript as a source for later research. [source_ingest](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/ingestion.py#L36)

## Answer a question with sources

**Problem:** I want a verifiable answer to a scoped question.

**Result:** An answer with source citations, counterarguments and open questions.

**Requires:** Gemini for planning and synthesis; search providers only for the chosen search route.

**First prompt:**

```text
Research <question> for <audience>. Limit it to <period>. Make a plan first, find primary sources and distinguish source facts, interpretation and unknowns.
```

- **Scope the question.** A plan does not start research by itself. [research_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research.py#L119)
- **Gather sources.** Choose Gemini Search or a configured search provider and read the relevant pages. [web_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search.py#L24), [web_search_provider](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L26), [web_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L46)
- **Develop the answer.** research_execute can use supplied or fetched sources. research_deep synthesizes and does not fetch new sources itself. [research_execute](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research_execute.py#L24), [research_deep](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research.py#L39), [research_assess_evidence](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research.py#L177)

## Explore scientific literature

**Problem:** Which papers and contrary findings fit my question?

**Result:** A bounded literature list and a comparison of sources actually read.

**Requires:** Semantic Scholar for metadata; Gemini for document analysis.

**First prompt:**

```text
Find papers on <question>. Give a selection with DOI or paper ID. Separate metadata from full texts actually read and compare methods and limitations.
```

- **Search for papers.** Search titles, authors and publication metadata. [research_paper_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L49), [research_author_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L233)
- **Follow relevant references.** Read details, citations and recommendations for selected papers. [research_paper_details](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L106), [research_paper_citations](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L141), [research_paper_recommendations](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/academic.py#L191)
- **Read the full text.** Pass available documents explicitly; metadata is not a paper that has been read. [research_document](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research_document.py#L55)

## Read and compare a document

**Problem:** I want to know what my documents actually support.

**Result:** Source passages with page or location and a separate comparison.

**Requires:** Original files; separately installed Poppler (pdftotext and pdfimages on PATH) for built-in PDF extraction with source_ingest, not bundled in the package. Docling is optional. Gemini for interpretation.

**First prompt:**

```text
Read <documents>. Keep page references. Compare what they say about <question> and show passages next to the interpretation.
```

- **Read the original source.** Keep the source identity and locations; do not start from a separately rewritten document. Check the installation requirements for source_ingest: https://github.com/Galbaz1/video-research-mcp/blob/019c59eafa70315f9f751227eef168bc22ec818e/docs/integrations/source-ingestion.md. [source_ingest](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/ingestion.py#L36)
- **Check the extraction.** Reread the relevant pages or elements. [source_ingest_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/ingestion.py#L67)
- **Compare content.** Choose joint document analysis or a specific output schema. [content_batch_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/content_batch.py#L174), [content_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/content.py#L242), [research_document](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/research_document.py#L55)

## Find events in video and audio

**Problem:** Where in this recording does `<event>` happen?

**Result:** Supported time intervals with source frames or audio windows, and visible gaps in coverage.

**Requires:** Local media, FFmpeg/ffprobe and Gemini for the selected AV analysis.

**First prompt:**

```text
Find <event> in <file> between <start> and <end>. Identify the supporting frames and audio. Report uncertainty and missed coverage.
```

- **Inspect the interval.** Measure the source and view the storyboard. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L28), [video_storyboard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_scenes.py#L66)
- **Choose one analysis.** Caption, count, ground and music are alternatives for different questions. [media_caption_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L48), [media_count_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L64), [media_ground_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L83), [media_analyze_music](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L99)
- **Check source moments.** View frames or export a clip. A model estimate is not a physically verified count. [video_frames](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L120), [video_clip_export](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L132)

## Read or edit an image

**Problem:** I want text, objects or a crop from this image.

**Result:** A source-bound OCR result, model interpretation or deterministic edit.

**Requires:** Pillow; local OCR requires Tesseract or Apple Vision. Vision and segmentation require a separate provider.

**First prompt:**

```text
Read <image>. Start with an inspectable view. Use OCR for text and label model interpretations separately. Keep the original when cropping.
```

- **View the source.** Provide real pixels; a model description is separate from them. [image_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L50)
- **Choose OCR or vision.** Local OCR and model OCR are separate routes; segmentation requires an external service. [image_ocr](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L105), [vision_ocr](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/vision.py#L41), [vision_chat](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/vision.py#L23), [image_segment](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/segmentation.py#L27)
- **Edit if needed.** Crop and image_edit are deterministic edits; check the manifest. [image_crop](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media.py#L37), [image_edit](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L43), [image_manifest_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/image.py#L76)

## Edit existing footage

**Problem:** I want to use existing clips in a short edit.

**Result:** A verified hard-cut edit with approved source moments.

**Requires:** Local clips, FFmpeg/ffprobe and access to the source files.

**First prompt:**

```text
Make an edit plan for <clips> of about <duration>. Show scene previews first. Edit only after my approval and check the audio and full decode.
```

- **Review scenes.** Detect cuts and create a storyboard. [video_detect_scenes](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_scenes.py#L42), [video_storyboard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_scenes.py#L66)
- **Prepare the edit.** The prepare route creates previews; record the chosen moments explicitly. [media_edit_footage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/footage_edit.py#L29)
- **Assemble after approval.** Use the same source and plan data; read the actual outcome. [media_edit_footage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/footage_edit.py#L29), [job_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/jobs.py#L19)

## From research to an explainer

**Problem:** I want to make a video from well-supported research.

**Result:** An approved plan, a bound script and a rendered video with a separate content review.

**Requires:** Separate explainer companion. Upstream video_explainer CLI for the chosen generation steps; renderer, Node and FFmpeg/ffprobe. Providers and keys per generation action.

**First prompt:**

```text
Make an explainer plan for <topic> based on <sources>. Check the available companion and renderer. Let me approve the plan and claims before you generate or render.
```

- **Check prerequisites and create a project.** Read the prerequisites and create a project in the configured environment. [explainer_doctor](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/doctor.py#L17), [explainer_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L27)
- **Plan and bind the content.** Supply source material, approve the plan and choose one generation step. [explainer_inject](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L55), [explainer_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/planning.py#L20), [explainer_step](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/pipeline.py#L164)
- **Render and review.** Follow the render job and check claims, readability and audio separately. The fact-check tool processes supplied observations. [explainer_render_start](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_jobs.py#L70), [explainer_render_poll](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_jobs.py#L150), [explainer_render_factcheck](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/render_factcheck.py#L25)

## Make a small interactive lesson

**Problem:** I want a bounded diagram lesson with narration.

**Result:** A self-contained HTML lesson and local video within the fixed three-scene domain.

**Requires:** Educational-explainer skill, lesson.py, local audio/source material and media dependencies. Only the described three-scene examples.

**First prompt:**

```text
Make a lesson within the educational-explainer domain about <supported example>. Use my narration. Validate the specification first and check the HTML and video separately.
```

- **Choose a supported example.** The skill describes the finite lesson domains; open-ended lessons require a different production route. [educational-explainer](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/educational-explainer/SKILL.md#L1)
- **Validate and build.** Use the CLI validate and build commands with exact source and audio input. [education-lesson](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/educational-explainer/scripts/lesson.py#L1)
- **Check the result.** Use check for source/output binding; readability and intelligibility require separate review. [education-lesson](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/educational-explainer/scripts/lesson.py#L1)

## From demonstration to instructions

**Problem:** I want to reuse the steps from a recording.

**Result:** Source-bound instructions or a transferable skill with explicitly marked missing information.

**Requires:** Gemini for interpretation; local frames for a PDF. The video-to-skill validators do not perform the task.

**First prompt:**

```text
Describe the steps from <recording> for <task>. Cite source moments, do not fill in missing actions, and then create a reusable instruction.
```

- **Examine the demonstration.** Review the relevant source moments. [video_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video.py#L117), [media_ground_events](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_perceive.py#L83)
- **Create readable instructions.** The PDF route uses real source frames; the skill route keeps steps and source data. [video_note_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_note.py#L22), [video-to-skill](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/video-to-skill/SKILL.md#L1)
- **Validate before packaging.** Structure and provenance checks do not prove that the described task was performed successfully. [video-skill-validate](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/scripts/validate_video_skill.py#L1), [video-skill-package](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/scripts/package_video_skill.py#L1)

## Find earlier research

**Problem:** I want to search my stored knowledge.

**Result:** Relevant stored objects and source references; optional synthesis remains model output.

**Requires:** WEAVIATE_URL, access to the chosen collections and the search/embedding configuration: hybrid/semantic require vectorization, keyword uses BM25. Gemini summarization and Cohere reranking are separate optional provider steps; QueryAgent is optional for an answer.

**First prompt:**

```text
Find earlier research on <topic> in <collection>. Return the source objects. Create a summary only if that option is available, and label it as interpretation.
```

- **Review collections.** Read the available schemas and counts. [knowledge_schema](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/schema.py#L25), [knowledge_stats](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/retrieval.py#L101)
- **Search and read the source objects.** Use knowledge_search, fetch and related; knowledge_query is deprecated. Without Weaviate configuration, search returns empty results; a search error is returned as a tool error. Empty results do not prove that there is no stored knowledge. [knowledge_search](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/search.py#L30), [knowledge_fetch](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/retrieval.py#L166), [knowledge_related](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/retrieval.py#L35)
- **Request an answer only if wanted.** knowledge_ask requires the optional QueryAgent. [knowledge_ask](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/knowledge/agent.py#L73)

## Understand audience comments

**Problem:** Which questions or objections appear in these comments?

**Result:** A bounded sample with exact quotes and transparent characteristics.

**Requires:** YouTube Data API for acquisition; audience_manage stores and analyzes supplied comments locally.

**First prompt:**

```text
Read a bounded selection of comments on <video>. Group questions and objections, give exact quotes and do not treat the sample as the whole audience.
```

- **Review channel context.** Read only the required metadata or uploads page. [youtube_channel_inspect](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube_channels.py#L17), [youtube_channel_catalog](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube_channels.py#L38)
- **Fetch the sample.** Keep the chosen size and sort order. [video_comments](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/youtube.py#L122)
- **Store and compare.** Work with source-bound quotes; model inference is a separate choice. [audience_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/audience.py#L23)

## Explore spatial visualization · experimental

**Problem:** I want a spatial sketch based on source footage.

**Result:** A chosen external route with explicit requirements; geometry and physical correctness require separate verification.

**Requires:** Separately configured external source and runtime. These routes are not a generally qualified native feature of RC3.

**First prompt:**

```text
Explore a spatial visualization for <source footage>. First check which external route is actually available. State geometric assumptions and do not start local model execution without a suitable runtime.
```

- **Choose source footage.** Fetch the required frames. [video_frames](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L120)
- **Check the external route.** The spatial skill and adapter are experimental; their presence is not proof of execution. [spatial-video-analysis](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/spatial-video-analysis/SKILL.md#L1), [spatial-session](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/scripts/spatial_session.py#L1)
- **Choose a visualization environment.** Blender and FreeCAD have separate prerequisites. [research-visualization-blender](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/research-visualization-blender/SKILL.md#L1), [research-visualization-freecad](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/research-visualization-freecad/SKILL.md#L1)

## Simulate hardware behavior · experimental

**Problem:** I want to read or modify a simulator.

**Result:** Simulation values and recorded changes; no physical hardware observation.

**Requires:** Explicit simulator registration and appropriate permission for changes.

**First prompt:**

```text
Examine <simulator>. Read devices, metadata and limits first. Propose a change and apply it only with the required permission.
```

- **Read devices and limits.** Discovery describes the simulator. [mhs_discover](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L66), [mhs_meta_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L107)
- **Inspect the state.** Health and read do not prove physical presence. [mhs_health_check](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L88), [mhs_read](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L123)
- **Change only explicitly.** Write and reset change simulator state and require the applicable permission. [mhs_write](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L141), [mhs_reset](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/hardware.py#L170)

## Install and check availability

**Problem:** Which components do I need for my task?

**Result:** A chosen core server or companion with verified configuration.

**Requires:** Python ≥3.11 and uv/uvx for MCP; Node ≥22 for the npm installer. The native Codex plugin connects the core server; you connect companions separately.

**First prompt:**

```text
Check which video-research tools and skills are connected. Show missing configuration for <task> without displaying keys. Do not install or change anything without my instruction.
```

- **Choose the entry point.** Codex has 26 packaged skills. The Claude installer has 26 skill entries plus supporting resources. [native-codex-plugin](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/plugin.json#L1), [plugin-installer](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/bin/install.js#L1)
- **Read the configuration.** provider_capabilities describes routes and does not test a provider connection. [infra_configure](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/infra.py#L101), [provider_capabilities](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/text_provider.py#L43)
- **Track your own work.** job_status reads supported core jobs. For generated media: companion image finalize/poll or video poll with an explicit operation; job_cancel is only for core video jobs. [job_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/jobs.py#L19), [job_cancel](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/jobs.py#L50)

## Find the origin of an image

**Problem:** Where does this image or clip come from?

**Result:** Candidate pages with separate visual and textual verification.

**Requires:** An exact local PNG frame; an enabled Serper route and SERPER_API_KEY. Running reverse_search_frame always uploads the selected PNG publicly to Uguu, verifies the hosted bytes and then sends the URL to Serper Lens. Concrete consent to publication, submission and potentially paid use is required. A dry-run publishes nothing.

**First prompt:**

```text
Find the origin of <image>. Give candidates with source pages. Do not publish my image without consent, and verify matches by appearance, text and context.
```

- **Choose an exact image.** Fetch one source frame. [video_frame](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L81)
- **Find candidates.** Choose either a local dry-run without upload, or execution of reverse_search_frame with a public PNG upload to Uguu, byte verification and subsequent URL submission to Serper Lens. web_search_provider is a separate text search route; it does not replace this frame search route. [reverse_search_frame](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L66), [web_search_provider](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L26)
- **Check the pages.** A search match is not yet an established origin. [web_extract](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/search_provider.py#L46)

## Create narration and visual assets

**Problem:** I want to produce audio or images for a video.

**Result:** Provider artifacts that still need to be reviewed for content, quality and coherence.

**Requires:** The core server does not generate images/TTS/clips. Choose the separate HTTP companion route below or a separately available provider workflow. CLI narration/music/SFX require upstream prerequisites.

**First prompt:**

```text
Make an asset plan for <video>. Check the real generators, inputs and costs before execution. Start with one sample and review the image and audio before scaling up.
```

- **Choose an available generator.** These skills guide usage; they do not add a generator. [tts-production](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/tts-production/SKILL.md#L1), [image-generation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/image-generation/SKILL.md#L1), [video-generation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/skills/video-generation/SKILL.md#L1)
- **Use the companion if connected.** Narration requires an approved bound script; music and SFX use chosen upstream routes. [explainer_narration](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L77), [explainer_music](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L53), [explainer_sound](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio.py#L25)
- **Inspect and mix.** Measure source media and mix existing project audio separately. [media_info](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/media_read.py#L28), [audio_dsp_analyze](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/audio_dsp.py#L29), [explainer_audio_mix](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/audio_mix.py#L18)

## Assemble existing materials

**Problem:** I have my own images and clips and want to make a video from them.

**Result:** A local MP4 following a recorded order and timing.

**Requires:** Separate explainer companion, a configured project, local materials with usage declarations and FFmpeg/ffprobe. Stock search/download is not connected.

**First prompt:**

```text
Assemble my existing materials <files> into <duration>. Use only these files. Record order, timing and usage declarations, and check the full MP4.
```

- **Create or choose a project.** Use an existing project environment; create uses the upstream CLI. [explainer_create](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L27), [explainer_status](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/project.py#L112)
- **Record the plan and materials.** Bind scenes, script and the explicitly supplied sources. [explainer_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/planning.py#L20)
- **Assemble and check.** Use local materials; this route does not search for or download stock. [explainer_materials_assemble](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/materials.py#L18)

## Reuse sources and notes locally

**Problem:** I want to find and share passages from my own sources.

**Result:** Local collections, citable passages, notes and readable exports.

**Requires:** Existing local source records; no Weaviate or model provider is needed for these record operations.

**First prompt:**

```text
Organize <source records> into a collection. Find passages about <question>, save notes with exact references and export a readable overview.
```

- **Organize and search.** Work with the supplied source records and a bounded search query. [collections_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/collections.py#L26), [corpus_retrieve](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/corpus.py#L27)
- **Keep context.** Link notes or wiki revisions to exact passages. [notebook_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/notebooks.py#L23), [wiki_manage](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/wiki.py#L27)
- **Share source data.** Check which source data is suitable for sharing. [evidence_export](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/evidence_export.py#L24)

## Translate a video · experimental

**Problem:** I want a spoken translation for my video.

**Result:** A source-bound translation plan and a possible render; voice quality and listening review remain separate checks.

**Requires:** Optional configured dubbing service for stems, VAD and TTS; local media and FFmpeg/ffprobe. Approved voice references.

**First prompt:**

```text
Prepare a translation of <video> into <language>. Check the dubbing service first. Create only an analysis and plan; ask for approval before synthesis and review the final audio.
```

- **Check and prepare.** A missing service is a stop condition. [check_dubbing_service](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L32), [prepare_video_translation_project](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L43)
- **Check the translation plan.** Work with exact source moments, speaker assignments and slots. [get_video_translation_state](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L152), [validate_video_translation_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L169)
- **Render after approval.** Technical delivery and voice quality verified by listening are separate outcomes. [render_video_translation](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L187), [validate_video_translation_delivery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/src/video_research_mcp/tools/video_dubbing.py#L212)

## Create film commentary

**Problem:** I want commentary on selected film clips.

**Result:** An approved commentary plan, separately executed segment groups and verified delivery.

**Requires:** Separate explainer companion; local source video, FFmpeg/ffprobe and a suitable execution route for the approved segment groups.

**First prompt:**

```text
Prepare commentary for <video> about <question>. Record exact source moments and narration. Let me approve the plan and the segment groups before you create partial renders.
```

- **Create and check the plan.** Link the project to the exact source video. [commentary_prepare](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L39), [commentary_validate_plan](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L87)
- **Record segment groups.** Approve grants execution scope; the tool does not run a partial render. That execution requires a separate suitable route. [commentary_freeze_shards](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L105), [commentary_approve_shard](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L125)
- **Combine existing partial renders.** Assemble and delivery validation follow only after successful partial outcomes. [commentary_assemble](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L143), [commentary_validate_delivery](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/commentary.py#L166)

## Create, edit or translate an image

**Problem:** I want a new image, an edit with references or translated text in an image.

**Result:** A locally stored PNG/JPG with source pins, hashes and full raster decode; you review semantics and style separately.

**Requires:** Separate explainer companion with the generation extra; regional DashScope configuration and an existing project. Exact script/scene pins and current pinned price, access and quote declarations. Actual consent to submission and costs is required separately. Pillow/HTTPX via the generation extra. Text/edit: qwen-image-2.0-pro. Translation: qwen-mt-image in Beijing, already-public HTTPS source; Chinese or English on one side. No upstream CLI.

**First prompt:**

```text
Choose text, edit or translation for <image task>. Check the companion, region, sources and current quote. Record source pins and costs; ask for my actual consent before submission. Keep the job ID and check the saved files.
```

- **Prepare source and quote.** Follow https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/docs/integrations/image-generation.md. Pin script/scene, references and current price/access/quote. spend_authorized=true is an input confirmation, not human authority. [explainer_image_generation_submit](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L17)
- **Save or recover explicitly.** Finalize for synchronous images; poll for translation/recovery. Each fetch gets an operation_id, the same principal and authorize=true. Do not use core job_status. [explainer_image_generation_finalize](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L57), [explainer_image_generation_poll](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L37)
- **Check outcome and limits.** Review assets, hashes and decode; paid provider quality and identity/style remain unqualified. On UNKNOWN, reconcile the original task first. Synchronous cancel is not supported. [explainer_image_generation_cancel](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/image_generation.py#L77)

## Create a short video from text or frames

**Problem:** I want a synthetic clip from text, a first frame or a first plus last frame.

**Result:** A saved MP4 with script/scene identity, source/request hashes and full decode; visual and audio quality remain separate.

**Requires:** Separate explainer companion with the generation extra; regional DashScope configuration and an existing project. Exact script/scene pins and current pinned price, access and quote declarations. Actual consent to submission and costs is required separately. FFmpeg/ffprobe; Wan text/frame models and explicit video endpoint configuration. No upstream CLI. S2V/HappyHorse are separate optional successors without accepted qualification here.

**First prompt:**

```text
Prepare one short synthetic clip about <scene>. Choose text or first/last frame and pin script, scene and references. Check the quote and limits. Ask for consent before submission; inspect the fully decoded MP4.
```

- **Bound and submit once.** Follow https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/docs/integrations/generation.md. Text/frame: whole-second durations of 2–15 seconds, 720P/1080P, permitted ratio. Frame pins and expected dimensions are explicit. spend_authorized is not actual spending authority. [explainer_generation_submit](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/generation.py#L17)
- **Fetch and check explicitly.** One poll per operation_id/principal/authorize; no background loop and no core job_status. Only permitted HTTPS output, saved hashes, dimensions/duration and full decode. [explainer_generation_poll](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/generation.py#L37)
- **Recover or cancel in a controlled way.** UNKNOWN requires reconciliation of the original task, not a new logical_job_id. Cancel only after a fresh PENDING and separate confirmation. Provider/creative quality, full security review and program acceptance remain open. [explainer_generation_cancel](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/tools/generation.py#L57)
