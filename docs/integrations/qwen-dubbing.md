# Optional video translation and dubbing

This first-party integration implements vrm-0e8.8.6: source preparation, external
speech services, exact evidence joins, speaker-guided translation groups, local
rendering, executable technical QA and a separate listening review. Root owns
mounting, packaging, configuration gates and operational qualification. The
entry point is video_research_mcp.tools.video_dubbing:video_dubbing_server.
Its nine tools can be discovered without an installed service or GPU framework.

Protocol/workflow attribution:
[QwenLM/Qwen-MM-Plugins at 07736672525443c7f8a3f6405eed37d2236f023f](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-chatcut),
Apache-2.0 original code/skills. This is independently written against that
contract. No upstream implementation, launcher, GPU dependency, checkpoint or
model is copied/imported. IndexTTS2, Demucs, TEN-VAD and isolated ChatCut remain
independently configured, licensed and operated; their model licenses and actual
availability are unqualified.

## Operator configuration and exact service contract

QWEN_MM_DUBBING_SERVER_URL must be a clean origin. Remote origins require HTTPS,
public DNS/IP addresses and the environment credential VRM_DUBBING_API_KEY.
VRM_DUBBING_LOCAL=true admits a separately operated literal 127.0.0.1 or ::1
service and permits HTTP there. localhost, userinfo, queries, fragments and origin
paths are rejected. Tokens appear only in Authorization headers. The existing
HTTP fence pins DNS and proves the peer before sending headers or content.
Proxies, redirects, transport retries and curl rerouting are disabled.

| Endpoint | Exact request | Required response |
| --- | --- | --- |
| GET /health | Empty body; environment bearer token when configured | Boolean model_loaded and string status; false is terminal unready evidence. |
| POST /separate | audio_base64, audio_filename, model="htdemucs", two_stems="vocals", mp3=false, return_audio=true | stems_base64.vocals and stems_base64.no_vocals containing complete PCM WAV. |
| POST /vad | audio_base64, audio_filename, separate_first=false, threshold=0.5, hop_size=256, min_speech=0.2, min_silence=0.3, pad=0.1 | Positive finite duration, integer sample_rate, ordered segments with start_time/end_time. |
| POST /tts | text, voice_base64, voice_filename, trim_silence=true, trim_ref_silence=true, return_audio=true | audio_base64, finite duration_sec and integer sample_rate matching actual local PCM. |

Returned base64 audio is downloaded and strictly decoded into local project files.
Server-local paths are ignored. Empty/truncated/non-PCM data, inconsistent metadata
and missing stems fail closed. Bounds: 256 MiB per WAV, 350 MiB per request,
700 MiB per service response, 16 KiB per health response and 4 MiB per evidence
JSON. Raw reception, including framing, is bounded. Each service operation has a
900-second deadline and joined cleanup. Oversize failure never creates partial
source coverage or clipped speech. These are operation bounds, not an agent deadline.

## Complete workflow and durable state

1. Obtain authority for the specific source, external submission, voice use and
   rendering. Readiness grants none of these. Core startup never installs,
   downloads or launches models/services.
2. Call prepare_video_translation_project with the exact source SHA256, output
   directory, languages, requested target and approved style brief. It checks readiness before source/process access,
   snapshots/probes source video/audio, extracts full 48 kHz stereo PCM, downloads
   both separated stems and obtains VAD from the local vocal stem. Missing,
   unreachable, malformed or unready service returns readiness_terminal.
3. Use independently configured isolated ChatCut omni_call for spoken/visible
   evidence, speakers and approximate absolute timing. This entry point is
   documented in the pinned workflows; installation, route and execution are not
   established here. At duration <=600 seconds, request the complete source once.
   Longer sources require ordered bounded windows covering the source, with
   overlaps reconciled. There is no automatic alternative provider/credit fallback.
4. Reconcile spoken/visible evidence, audible boundaries, speaker continuity and
   VAD. VAD is speech presence, not sentence/speaker authority. Do not invent OCR
   when subtitles are absent. Write analysis/transcript.json using Transcript in
   models/video_dubbing.py, retaining detected language, source/VAD hashes,
   evidence_windows, ordered source speech and unresolved_issues. Material
   unresolved facts block rendering. Analysis-only stops after transcript review.
5. Author plan/translation_plan.json using TranslationPlan. Preserve meaning,
   names, tone and natural spoken delivery. Consume every transcript item exactly
   once and in order. Merge adjacent same-speaker items with a concrete reason;
   exact source text and span must match. Copy source/transcript/VAD hashes.
6. Choose an independent evidenced reference per group: own clean speech first,
   normally >=1.5 seconds; adjacent same-speaker speech with gaps <=1.2 seconds
   next; nearest clean same-speaker speech if needed. Record IDs, interval and
   selection reason. Cross-speaker, reordered/duplicate references and unsupported
   padding fail. No enrollment or real speaker registry is involved.
7. Call validate_video_translation_plan. Low VAD overlap is a review flag, not
   automatic rejection of quiet/missed speech. Duration estimates are diagnostics,
   never semantic or listening verdicts. Translation-only stops after validation.
8. Review the full background stem. Choose omit only after an explicit whole-stem
   decision; uncertainty defaults to include. Call render_video_translation with
   the valid plan. It cuts exact references, synthesizes groups, borrows at most
   0.3 seconds/half adjacent silent gaps, preserves short speech pace, centers
   silence/fades and accelerates at most 1.18x. Overlong speech explicitly fails;
   it is never clipped or allowed to overlap neighbors.
9. A known overlong candidate permits at most three candidates for that group
   when the duration estimate is <=1.35x its slot. Cached candidates count toward
   the total; retain the first fitting candidate. An interrupted/unknown effect
   stops immediately, without another request or candidate.
10. Assemble a 48 kHz stereo bus; include the whole background when selected and
    use amix normalize=0 without ducking. Apply measured two-pass EBU R128
    normalization once to the full mix at -16 LUFS/-1.5 dBTP/11 LRA. Copy all
    source video/subtitle streams into lossless-audio Matroska. Unsupported
    data/attachment streams or subtitle/container/decode combinations fail explicitly.
11. Listen end to end and review every group's translation, timing, voice
    reference, natural delivery and mix. Write ListeningReview to
    listening_review.json beside the selected render report, bound to exact
    output/plan hashes. Missing, partial, stale or failed checks retain
    UNRESOLVED/FAIL. The program never performs listening or fabricates a PASS.
12. Call validate_video_translation_delivery to rerun technical QA and join the
    separately supplied review. Supplied labels are assertions; Root's independent
    service/native/listening/product qualification remains separate.

get_video_translation_state derives routes from actual content joins. A project
lock excludes concurrent writers. Durable intent precedes every POST; completed
exact response bytes can be reused, while unknown, failed, mismatched or altered
receipts require reconciliation. Process receipts bind argv, inputs and outputs.
Raw TTS reuse requires the same source/reference/group/text/language. Changed
plans create new content-addressed renders; prior outputs/failures remain.
full/current.json identifies the selected report and QA.
The active generation remains occupied across plan and filename changes.
Explicit regenerate_segment_ids regenerates only reviewed known groups and
preserves other successful speech. Unknown effects or exhausted overlong speech
cannot be made runnable by changing a generation name. Full source/stem refresh
uses a newly prepared project, retaining the prior evidence and requiring fresh
transcript/VAD joins; a renderer never silently invalidates accepted source evidence.
Standalone separation accepts the pinned model selector; speech detection accepts
strict VadSettings. Operator configuration supplies the service origin, rather
than accepting an unchecked caller URL override.

## Executable QA and retained uncertainty

Rendering and delivery validation check output SHA256, all stream accounting,
duration, full video/audio decode and subtitle conversion, encoded video/subtitle
stream hashes, actual audio replacement, decoded lossless output versus the final
mix, PCM bus format, segment count/timing, stem identities, process receipts and
report joins. FFmpeg uses existing file-only helpers, bounded output, no shell and
owned cancellation cleanup.

Flags retain low VAD overlap, acceleration >1.12x, speech fill <60%, short
references, merged groups, boundary silence and retries. Overlong TTS retains
candidate evidence and timing FAIL; technical failure cannot publish a current
delivery. Technical success retains unresolved listening by default. Even complete
supplied review labels leave service/native/feature acceptance UNQUALIFIED.

## Source mapping and every leaf criterion

| Pinned tool/workflow | Implemented behavior |
| --- | --- |
| prepare_video_translation_project | Full source/PCM/stems/VAD preparation, project joins and analysis route. |
| check_dubbing_service | Strict health and terminal readiness without model effects. |
| separate_dubbing_audio | Exact separation POST, bounded local stems and durable intent. |
| detect_dubbing_speech | Exact TEN-VAD POST, ordered intervals and durable receipt. |
| synthesize_dubbing_speech | Standalone reference-guided TTS, bounded local PCM, durable intent and unresolved listening/voice quality. |
| validate_video_translation_plan | Source/VAD/transcript joins, languages, references, groups and slots. |
| render_video_translation | Journaled candidates, references, fitting, mix, normalization, remux and executable QA. |
| validate_video_translation_delivery | Current output/report/process readback, technical QA and supplied listening evidence. |
| Source-analysis | Prepare → isolated ChatCut analysis → audible/VAD reconciliation → uncertain authored transcript; inclusive 600-second route. |
| Translation-authoring | Natural spoken text, exact ordered coverage, same-speaker groups, independent references, valid plan and translation-only stop. |
| Dubbing-rendering | Readiness, full background decision, bounded candidates/timing/mix/remux, QA, listening review and delivery validation. |
| State/resume | First-party get_video_translation_state, occupied durable intent, exact completed reuse and preserved render epochs. |

All nine files in the exact pinned tools directory were inspected: __init__.py,
check_service.py, detect_speech.py, prepare_project.py, render_project.py,
separate_audio.py, synthesize_speech.py, validate_delivery.py and validate_plan.py.
Root supplied the small filtered tree manifest; its full tree was not read.
Earlier failed filename probes remain in the R107 packet as separate failures.
All eight source tools and the three named workflows have concrete mappings.

| Leaf criterion | Source/mock evidence |
| --- | --- |
| Exact mock health/VAD/separation/TTS and local audio | test_dubbing_client.py: bodies/headers, strict responses, local PCM, remote-path rejection, bounds and pre-transmission peer proof. |
| Required hashes, references, groups and slots | test_video_dubbing.py: actual preparation, hash/byte mutation, language/speaker/group/reference and source-coverage boundaries before TTS. |
| Output/all streams/duration/decode/mix/report/QA; explicit timing/listening failure | Full mock process journey, retained timing/decode/stream/duration failures, output tampering and absent/failed/synthetic supplied reviews. |
| Terminal missing/unready service; no core model effects | Readiness stops before source/process access; import/discovery needs no service, model or GPU library. |

Tests use mocked HTTP/process boundaries and owned temporary files. They establish
source contracts and executable workflow behavior, not actual service/model
availability, FFmpeg/native success, speaker consent, listening completion,
product admission or comparative acceptance.
