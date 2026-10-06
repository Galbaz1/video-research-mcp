# Exact-source captions and optional speech inference

`audio_transcribe` provides a bounded captions-first component. It accepts exact local
media bytes, explicit caption associations and an absent output directory. Existing
captions are timing/text assertions from their source. Model transcripts, words and
speaker labels are inference. Neither route verifies speech accuracy, acoustic word
alignment, speaker identity or diarization.

The root API calls `await transcribe(TranscriptRequest(...))` for both `transcribe` and
`readback` actions. The independent restart helper is
`await read_transcript(directory, expected_receipt_sha256, *, file_path=None,
expected_source_sha256=None)`. A tool readback supplies both caller source fields;
they must match the retained source identity. The external receipt SHA commits exact
bytes and metadata; it does not authenticate a human, provider or caption author.

Caption candidates explicitly declare `origin` (`uploaded`, `embedded`, `native` or
`sidecar`), `source_sha256`, format and their own path/SHA. An embedded extraction
instead declares `embedded_track` (0 through 7) and uses owned file-only FFmpeg SRT
output. Native captions are explicitly supplied files in this slice. There is no
YouTube caption fetch or automatic neighboring-file discovery. The default preference
is uploaded, embedded, native, sidecar; the request can reorder this complete list.
Within one origin, caller order wins. A malformed selected caption refuses the run;
it does not silently select a different caption or backend.

SRT requires numeric cue indices and complete `HH:MM:SS,mmm` clocks. VTT requires
`WEBVTT` and complete millisecond clocks. Unsupported VTT settings/metadata are
refused. Numeric lines after a cue timestamp remain spoken text. Canonical JSON is
`schema_version: 1`, `segments: [{id,start_seconds,end_seconds,text,speaker_id,
words:[{text,start_seconds,end_seconds}]}]`, with optional provenance. Words must
match the full cue text and remain ordered inside that cue. Missing speakers use
`null`; missing words remain absent. Supplied provenance cannot claim verified
speech, alignment or identity. TSV admits explicitly declared `start_seconds`,
`end_seconds`, `text`, `speaker_id` columns, optionally preceded by `id`. A separately
declared `start_ms`/`end_ms` header uses integer milliseconds. Unknown headers refuse.
Absent TSV IDs are generated from the complete cue values.

All supplied cues are checked against the observed source clock before selection.
Overlapping cues may refer to different speakers. A selection retains a complete cue
that intersects its interval and reports boundary-crossing IDs and omitted counts;
it does not clip text or invent new words. Caption timing is a source assertion,
including when the source video has no audio. Non-WAV extent observation and embedded
extraction require separately installed FFmpeg; there is no installer. PCM16 WAV
extent observation reads the complete source using the existing ingestion helper.

The optional backend is explicit: `none` (default), `gemini`, `qwen` or
`faster_whisper`. ASR defaults
to `dry_run=true`; live submission also requires `authorize_submission=true`.
Caption parsing is local work and can complete during a dry run. A dry ASR run retains
measured WAV windows and records a plan without selecting an account or submitting
media. The focused request has no visual/frame/image parameters.

Gemini inherits the configured account and model. Its exact task schema is passed to
the existing structured generator and serialized byte budget. The existing provider
contract supplies classified retries (at most three for selected server failures),
token/call accounting, finish gates, account rechecks and fixed redaction. Speech
times returned relative to a WAV are projected from **actual**
`selected_window.start_seconds`, never from the requested cut start. Each WAV is
retained byte-for-byte with its full hash, duration and complete PCM frame population.
The only local silence shortcut is a complete selected PCM16 population whose sample
bytes are all zero. It has no first-120-seconds heuristic or near-silence threshold,
and says nothing about the semantic contents of nonzero audio.

The dedicated Qwen-compatible service is disabled by default.
`ServerConfig.asr_service` is selected through `ASR_SERVICE_JSON`, with `base_url`,
`local`, optional `api_key_env`, optional `declared_model` and `runtime_qualified`.
Credentials come only from the selected environment variable. No endpoint, key or
model override is accepted in a transcript request. A local profile requires literal
`127.0.0.1` or `::1`; an internet URL cannot become local through a boolean assertion.
The existing bounded HTTP policy denies proxies, redirects and transport retries,
attests the peer before body transmission and bounds response bytes/deadlines.
`runtime_qualified` and `declared_model` are operator assertions, not proof of a
loaded model, service grant, accuracy or isolation.

The admitted Qwen `/asr` request is one POST with `audio` as a WAV data URI and
`return_time_stamps: false`. It returns actual untimed `results[].text`. The selected
source contract does not forward language/glossary or provide words/timestamps;
required options refuse before HTTP. This route accepts JSON/text exports only and
never assigns its whole chunk interval to every sentence. Untimed text retains the
selected WAV support separately. Cloud-to-local fallback is available only through
explicit `backend=gemini, fallback_backend=qwen` and an admitted local profile/options.
Every requested/actual attempt is retained. `local_only=true` rejects cloud selection
or a cloud-to-local plan before any SDK/HTTP action. There is no implicit fallback.

The [local timed service](local-asr.md) uses `backend=faster_whisper` and an
explicit `ASR_SERVICE_JSON` profile with `protocol=faster_whisper_v1`, `local=true`,
`runtime_qualified=true` and a separately pinned `expected_descriptor_sha256`.
It runs in its own qualified environment and starts only through an operator's
explicit command. Core startup needs no model library. The service receives the
actual selected WAV with its SHA256 and forwards Dutch/English language and
glossary hints. The client verifies the returned descriptor/WAV identity, duration,
settings and typed word intervals before applying the existing absolute source
clock and export/readback path. All speakers remain unknown. Returned model and
runtime receipts are service assertions; accuracy and alignment still require
independent reference evidence. This backend has no cloud fallback.

The component distinguishes planned, complete, partial and failed states, with empty
and explicit abstained inference outcomes separate. A later-window failure retains
earlier records and every remaining planned window. Exact source-time/text/speaker/
word duplicates alone are deduplicated; phrases at different times and speaker
overlaps survive. This does not merge physical identities across windows.

The absent owned namespace contains `run-state.json`, selected caption/chunk evidence,
PCM observations, requested exports, `transcript-result.json` and finally
`receipt.json`. Dispatching state is fsynced before a provider window begins. Failures
and cancellation retain their state; cancellation propagates after joined cleanup.
An existing namespace is never regenerated or overwritten. The final receipt is
promoted only after snapshot exit checks and source/artifact rechecks. Restart requires
its independently retained SHA and rehashes originals, captions, chunks, results and
exports. Changed or interrupted evidence cannot be silently adopted as a complete run.

The remaining caller deadline covers export verification, original rehashing and
retained-file proof. Expiry prevents successful promotion. Failed finalization has
a separate ten-second asynchronous grace, and caller cancellation joins that owned
finalizer before propagating. No cancellable await separates the final result and
receipt writes; the result is synchronously rehashed before receipt promotion.
Bounded synchronous filesystem work does not provide a hard operating-system deadline.

Full JSON preserves numeric precision, complete supplied/inferred words and provenance.
Untimed backend text is retained in its explicit provenance field. Text exports lose
all timing/word/speaker/ID/provenance fields. SRT/VTT/TSV round endpoints to nearest
millisecond (half up, at most 0.5ms each); a collapsed interval refuses rather than
inventing duration. SRT/VTT lose original IDs/speakers/words/provenance, while TSV retains
IDs and speaker labels but loses words/provenance. These losses are recorded per export.

Bounds remain concrete: selection at most120 seconds, windows at most30 seconds and
four total, at most24 provider calls, 8MiB selected payload, 64MiB serialized submitted
content, 120-second caller deadline, finite128KiB Gemini answer per window, caption
files at most1MiB/512 cues, complete JSON at most4MiB and retained evidence at
most32files/20MiB. These limits can refuse larger jobs; results are not silently
truncated into apparent completion. Files use existing nofollow snapshot/path fences;
ordinary host/native execution is not an OS sandbox.

The independently authored requirements implementation is informed by
QwenLM/Qwen-MM-Plugins at `07736672525443c7f8a3f6405eed37d2236f023f` (Apache-2.0)
and guimatheus92/mcp-video-analyzer at `9e476c02f8426f5c277ed5e7f5729c1aee75b31a`
(MIT, copyright 2026 Guilherme). Original source remains unchanged and is not imported
or copied. The joined source packet retains 48 full bodies and two complete grants;
its broader foreign runtime closure exceeded the collection cap and remains
unqualified. No upstream modules, weights, models, assets or fonts are bundled.

Owned tests use synthetic text/PCM and mocked native/provider boundaries. They do not
prove real speech, speaker accuracy, service/model readiness or comparison acceptance.
Actual speech and reviewed speaker benchmarks remain `UNRUN_RESOURCE_UNQUALIFIED`,
with the human nine pending, heldout inputs unread and comparison/release acceptance
unaccepted. The existing joint AV and prior media APIs remain separate.
