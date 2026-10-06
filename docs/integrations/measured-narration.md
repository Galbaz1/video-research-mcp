# Measured narration artifacts

The optional companion `explainer_narration` entrypoint produces a measured WAV
from the current approved, source-bound script. It runs inside the companion's
plan transaction and reads the actual script and source commitments again
before publishing an accepted artifact. It does not change the approved script,
storyboard durations, or the existing external render CLI's mock, ElevenLabs,
and Edge interfaces. Renderer consumption is a separate, unverified boundary.

The default provider is `mock`, voice `tone`, model `tone-v1`. It synthesizes
deterministic 440 Hz PCM tone segments at 24,000 Hz, mono, 16 bits: each
non-whitespace word contributes `round(0.2 / rate * 24000)` samples. Its word
events come from those actual synthesized segments. These tones are not speech,
and their events do not establish semantic alignment or spoken correctness.

## Request and admission

`NarrationRequest` accepts these explicit fields:

| Field | Supported values or meaning |
| --- | --- |
| `action` | `generate` (default), `preview`, or `custom` |
| `provider` | `mock` (default), `qwen`, or `minimax` |
| `voice` | `tone` by default; real voices must be operator-allowed |
| `model` | Mock resolves to fixed `tone-v1`; a real provider requires an explicit supported model |
| `language` | `English` by default; declared provider languages are validated |
| `region` | `global` (default) or `cn`, selecting the fixed official endpoint |
| `rate` | Finite value from 0.5 through 2, default 1 |
| `pause_seconds` | Finite value from 0 through 2, default 0.1 |
| `scene_id` | Optional preview scene; the first approved scene is the default |
| `custom_audio` | Required only for `custom`; a contained project-relative WAV path |

Missing approval, changed source bytes, a stale or changed bound script, an
unknown preview scene, or measured audio exceeding the approved scene or total
duration budget refuses acceptance. A performance change creates a fresh
artifact receipt rather than rewriting the approved timing budget. Sentence
partitioning preserves every transcript character, including whitespace and
punctuation; joining the sentence strings reproduces the approved transcript.

Generation concatenates compatible PCM16 mono sentence WAVs and quantizes each
pause to the actual sample rate, including the final pause. Captions end at the
sentence's measured audio end; the next sentence starts after the measured
silence. The full duration includes every audio and pause sample. Mixed sample
rates are refused rather than implicitly converted. RMS dBFS, peak amplitude,
and clipped-sample count are measured; this is not LUFS normalization. Corrupt,
truncated, empty, clipped, or silent/very quiet media (RMS below -60 dBFS) cannot
be promoted as accepted audio.

Custom audio uses a bounded regular-file snapshot, refuses traversal, absolute
paths, symlink components, FIFOs, and mutation, and measures the supplied WAV.
It keeps the approved transcript and discloses absent word and scene alignment.
The custom bytes are unaltered: pauses are not inserted, and only rate 1 is
supported. A rate change would require a separately qualified audio processor.

## Explicit optional REST providers

The HTTP path uses the separately declared companion `[narration]` extra and
loads `httpx` only when a real provider has been explicitly selected and enabled.
No SDK, foreign application, renderer, native process, or audio device is needed
for the owned PCM path. There is no silent provider fallback.

Operator configuration is deliberately small and environment-only:

| Provider | Enable flag | Allowed voices | Exact download hosts | Credential |
| --- | --- | --- | --- | --- |
| Qwen | `EXPLAINER_NARRATION_QWEN_ENABLED=1` | `EXPLAINER_NARRATION_QWEN_VOICES` | `EXPLAINER_NARRATION_QWEN_DOWNLOAD_HOSTS` | `DASHSCOPE_API_KEY` |
| MiniMax | `EXPLAINER_NARRATION_MINIMAX_ENABLED=1` | `EXPLAINER_NARRATION_MINIMAX_VOICES` | `EXPLAINER_NARRATION_MINIMAX_DOWNLOAD_HOSTS` | `MINIMAX_API_KEY` |

Voice and download-host values are comma-separated explicit allowlists.
Download hosts contain exact DNS hostnames, without schemes, ports, paths, or
wildcards. Missing configuration or credentials refuses the request before
network dispatch. Region selects Qwen's `dashscope-intl.aliyuncs.com` or
`dashscope.aliyuncs.com`, and MiniMax's `api.minimax.io` or `api.minimax.cn`.
Operator configuration and selected model, provider, region, voice, language,
rate, and pause participate in artifact/cache identity; credentials do not.

The selected Qwen HTTP contract supports `qwen3-tts-flash`. It has no numeric
speed field and no word timing contract, so rate other than 1 is refused and
word alignment remains absent. The selected MiniMax contract supports
`speech-2.8-hd`, `speech-2.8-turbo`, `speech-2.6-hd`, `speech-2.6-turbo`,
`speech-02-hd`, `speech-02-turbo`, `speech-01-hd`, and `speech-01-turbo`. It
requests non-streaming hex WAV, 24,000 Hz mono PCM16, and `subtitle_type=word`.
Success requires integer `base_resp.status_code=0`, integer `data.status=2`,
locally qualified audio, and independently downloaded word subtitles. Subtitle
text and offsets must match the exact transcript; finite ordered milliseconds
must lie within decoded samples. Provider-declared timing remains a provider
claim whose semantic correctness is unverified. No text-proportional timing is
invented. Numeric provider usage is retained separately from measured duration.

Every download requires HTTPS on an exact operator-allowed host. Authentication
is sent only to the fixed provider POST endpoint, never forwarded to downloads;
redirects are denied. Streamed responses have byte limits, HTTP operations have
a 30-second timeout, and the sentence request has a 60-second outer deadline.
Provider POST requests are not retried. Error receipts contain fixed local
reasons and safe numeric status/usage fields, without raw provider bodies,
credentials, bearer values, or signed URL query strings. URL-bearing `httpx`
request logs are suppressed within this owned request scope.

## Receipts, preview, and failure retention

Each configuration/script/text/commitment combination has an exclusive
`.narration/<cache-key>` directory. Binary artifacts and finite JSON receipts
are atomically written with `fsync` and replace; existing binary files are
preserved. The receipt keeps the full exact transcript, sentence population,
actual measurements, current `video_research_plan` metadata, source and parent
script commitments, and explicit semantic/render limitations. Both
`artifact.path` and returned `binding.audio_path` use the same project-relative
path, with exact audio SHA-256 and byte count.

Dispatch state is persisted before each POST, and returned candidate audio is
retained before local quality/alignment checks. Partial failures preserve
accepted sentence candidates, the failed or unknown sentence, and the remaining
unrun population. They produce no accepted final audio or narration binding.
Timeouts, ambiguous outcomes, and real-provider cancellation are retained as
unknown. Repeating an incomplete or ambiguous key refuses regeneration, avoiding
an automatic second charge after restart. Cancellation retains its receipt and
does not promote accepted audio.

Preview selects one approved scene. A cache hit requires the same configuration,
script, selected text, commitments, and verified final and sentence WAV bytes;
changed configuration creates a fresh key, and corrupted audio refuses reuse.
The accepted receipt digest is retained per cache key in the transactional plan
state, including previews. Changed or unanchored accepted receipts are refused
before issuing a new binding; editing timing or sentence metadata cannot be
legitimized by recalculating its hash. Failed or unknown runs remain unaccepted
and cannot be regenerated automatically.
The parent source/script commitments are rechecked after cache readback.
Preview does not replace the full narration binding in the plan database.

## Source credit and verification boundary

Requirements were independently adapted from
[Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins), revision
`07736672525443c7f8a3f6405eed37d2236f023f`, under Apache-2.0, and
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo), revision
`44e6d5e11832beccc2c3ce6b139bf437e920bb6a`, under MIT,
Copyright (c) 2024 Harry. The repository's `THIRD_PARTY_NOTICES.md` and reuse
ledger retain the grant and source qualification bindings. This implementation
does not import or copy their application, SDK, or renderer code.

Focused unit checks use stdlib PCM, actual companion source/plan/script bindings,
fake environment keys, and `httpx.MockTransport`. They perform no real provider
request, socket access, audio playback, native processing, or install. Root-owned
packaged acceptance and independent review are distinct gates; unit success
does not establish physical voice quality, spoken content truth, live provider
behavior, or renderer consumption.

## Recorded packaged acceptance

The frozen root-owned packaged journey passed all 16 offline controls on its first
run: 33 public calls, 36 mocked HTTP requests and no real provider or socket
requests. Both original review findings were reproduced and repaired: cached
receipt digest authority and self-contained companion source-archive rebuilding.
In that epoch, final verification passed 3,111 root tests and 388 companion tests; all 83 root
and 18 prior companion tool objects remained exact. Seven fresh distributions
and an independently rebuilt companion wheel passed source/resource byte
readback. These results accept the owned synthetic/mocked audio contracts;
real spoken quality, renderer consumption, human audit, comparisons and release
remain unverified.
