# Deterministic audio DSP and optional Rust workflows

`audio_dsp_analyze` measures a fenced local audio/video source and exports exact
result JSON, a readback manifest, selected PCM WAV, waveform and spectrogram PNGs.
It requires the existing optional `audio` and `images` extras and separately
installed FFmpeg. It makes no model/provider calls. Originals are preserved.

```json
{
  "request": {
    "file_path": "/allowed/audio.wav",
    "expected_source_sha256": "<full current lowercase SHA256>",
    "start_seconds": 1,
    "end_seconds": 3,
    "operation": "analyze",
    "job_id": "audio-example"
  },
  "include_image": true
}
```

Omitted endpoints select the whole or remaining track within the same limits.
Primary and optional reference selections together are limited to 30 seconds
of actual selected audio. A gap before the first audio sample is excluded.
The decoder selects the first audio stream, admits mono/stereo, and derives
48 kHz signed 16-bit PCM. The source file hash, derived file and PCM hashes,
actual decoded sample clocks, channels and transformations stay in the report.
The PCM measurements describe this derivation, rather than the original bit depth.

`operation="compare"` requires a `reference` with its own `file_path`,
`expected_source_sha256` and optional endpoints. Differences use
**reference minus primary**, with seconds, Hz, linear full scale, dBFS, LUFS and
LU fields. Unequal channel layouts are explicit; only corresponding channels
are paired. Perceptual quality equality remains unverified.

RMS and sample peaks use exact selected integer PCM. Spectrum uses a declared
2048-sample Hann FFT and 512-sample hop. Near-full-scale runs retain their complete
count and at most 128 absolute, half-open source intervals; this does not prove
analog clipping. Silence has null logarithmic measurements and an explicit state.
FFmpeg's completed `ebur128=peak=true` summary supplies loudness observations at
its displayed one-decimal precision. Its silence gate floor is explicit and
does not represent physical loudness. Independent EBU/ITU conformance is unknown.
The raw process-log digest is separate from reproducible numerical measurements.

The existing mean-MFCC method derives 8 kHz mono float PCM and a declared lossy
13-coefficient feature. Silence and too-short input retain an undefined result.
Cosine similarity does not establish equal speech, music, speaker or ordering.
Ferrous' perceptual hash is a separate native heuristic, with its own source.

Own waveform and spectrogram files use exact 512×128 and 256×128 PNG grids.
Each binds original source SHA, selected PCM SHA, source reference and actual
absolute horizontal interval. Artifact files have an 8 MiB aggregate ceiling;
result JSON and manifest each have a 128 KiB ceiling. A single operation has at
most the configured native-media deadline, capped at 120 seconds. Failed decode,
budget, source/readback or cancellation stages do not promote a complete result.
An expired local deadline returns a descriptive artifact failure after owned work
joins. It does not report a connectivity problem or recommend automatic retry.

## Optional pinned processes

No Rust server is installed, compiled or launched at startup or by doctor. Build
each separately from the exact source/lock, inspect its dependency grants and
build scripts, and set the operator profile to an absolute regular executable
path without symlinks plus its complete byte hash:

```bash
export AUDIO_DSP_JUZZY_PATH=/private/juzzy-target/release/mcp-server
export AUDIO_DSP_JUZZY_SHA256=<exact executable SHA256>
export AUDIO_DSP_FERROUS_PATH=/private/ferrous-target/release/mcp_server
export AUDIO_DSP_FERROUS_SHA256=<exact executable SHA256>
```

| Backend | Exact source | Operations |
|---|---|---|
| Juzzy | [audio-analyzer-rs at 0387fe1630ff0fc7f71bf656be81f3b1f400dda8](https://github.com/JuzzyDee/audio-analyzer-rs/tree/0387fe1630ff0fc7f71bf656be81f3b1f400dda8) | `audio_info`, `spectral_features`, `harmonic_analysis`, `rhythm_analysis`, `full_analysis`, `juzzy_compare` |
| Ferrous | [ferrous-waves at d28ec11361123eb3778454deddf164f1fb6d25e4](https://github.com/willibrandon/ferrous-waves/tree/d28ec11361123eb3778454deddf164f1fb6d25e4) | `ferrous_analyze`, `ferrous_compare`; analyze also reads `get_job_status` in the same native process |

The adapter discovers all six or three exact tool names before one fixed native
call. Only owned bounded PCM paths reach it. Juzzy receives original selected
mono/stereo; Ferrous receives an explicit mean-channel mono WAV because the pinned
decoder's planar layout conflicts with its downstream interleaved assumption.
The conversion and both input hashes remain in the report. Native zero maps to
the selected original source clock; native prose is preserved without rewriting
its relative timestamps as verified absolute events.

Juzzy adds harmonic, rhythm, HPSS, masking, section and stereo summaries. Its
results are text and TSV, including possible `Error:` text. Ferrous supports
`native_return_format="summary"` (default), `"full"` and `"visual_only"` for
`ferrous_analyze`. Summary exposes heuristic quality/content and perceptual hash
counts; full exposes its selected spectral/temporal arrays with a 128-point limit.
Neither exports all internal raw fingerprint, quality-event or classification
segment records. Native pagination and complete array coverage are not promised.
The visual workflow requires the waveform and spectrogram fields returned by
`visual_only`, decodes both 1920×600 PNGs, exports them with exact hashes, and
leaves native axis correctness unverified. The pinned server renders an internal
power curve but does not include it in this response.

The fixed programme journey qualified the core measurements and five Juzzy modes,
plus Ferrous summary, full, compare and silence-summary results with actual
process-local job readback. Juzzy `full_analysis` twice reached the 120-second
deadline on the selected two-second tone fixture. Ferrous `visual_only` failed
the protocol collector's line/closure check before any native image was exported.
These two workflows remain unqualified; their terminal errors and replay stay in
the acceptance denominator. The successful core plots do not qualify native plots.

Native text/JSON is retained as an attributed artifact under a 1 MiB protocol-line
and 4 MiB total/retained-response ceiling. Content remains untrusted data. The
client advertises no sampling capabilities and refuses server requests for client
operations. Each invocation uses a private cwd/TMP directory and an admitted
owned executable copy. Its process group and workers join before completion or
cancellation. Ferrous' cache remains enabled in that fresh private directory;
its metadata-based cache identity is not treated as content evidence. Temporary
cache, binary and request files are removed after collection.

Upstream confidence, music/key/mood/content, quality, SNR/THD, mastering advice and
fingerprint matches remain uncalibrated heuristics. Juzzy's linear-interpolated
peak and Ferrous' sample maximum do not establish inter-sample true peak or
standards conformance. An executable hash verifies bytes; the adapter does not
independently certify that an operator's binary was built from the declared source.
Private programme build receipts are separate evidence of exact source and build.
No foreign source, Rust binary, crate, font, weight or recording is redistributed
inside the Python package. Both selected root source grants are MIT; transitive
dependencies have their own terms.

## Durable completion and restart

The canonical JobStore commits source revisions, request, adapter/dependency
source bytes and numerical/native runtime identities before attempting analysis.
`job_status(job_id)` rehashes the result, manifest, originals and every retained
artifact. A complete status without verified byte attestation does not pass.

Reusing the same request and `job_id` reads that attested result. Changed source,
runtime or request rejects the old identity. An interrupted attempted operation
remains unknown and is never automatically resubmitted. Source and artifact
readbacks use joined workers with cooperative cancellation and deadline checks.
Both original inputs of a comparison are reverified under the input byte limit;
the separate output ceiling remains 8 MiB.

Caller cancellation joins owned work and records a terminal cancellation before
completion commits; an analysis error records failed state. If delivery is
interrupted after an exact result has already committed, that durable terminal
result remains available for verified replay. A restart never treats Ferrous'
process-local status as durable completion.
