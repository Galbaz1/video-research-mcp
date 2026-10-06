# Joint audio and visual perception

`media_perceive` prepares an exact local audio or video selection and optionally
submits it to the existing configured Gemini account. Its default `dry_run: true`
performs local preparation with zero provider calls. A live workflow requires
`dry_run: false` and `authorize_submission: true`; account configuration alone
does not authorize a source upload or a charge.

```json
{
  "request": {
    "file_path": "/allowed/source.mp4",
    "expected_source_sha256": "replace-with-the-full-recorded-source-sha256",
    "instruction": "Describe the visible state changes and the spoken explanation separately.",
    "start_seconds": 20,
    "end_seconds": 65,
    "window_seconds": 30,
    "fps": 1,
    "dry_run": true
  }
}
```

Selections split into ordered, adjacent half-open windows of at most 30 seconds,
with at most 4 windows and 120 selected seconds. Omitted end selects the known
source end; unknown endpoints need an explicit bound. Out-of-source or empty
selections fail. `media_type: auto` selects from inspected streams; `audio`
selects actual sound and `video` requires an actual video stream. A silent video
has no submitted audio and cannot support a spoken event.

Each video window supplies bounded sampled PNGs with their actual decoded source
PTS and time base. A sound window supplies full continuous 16-kHz mono 16-bit PCM
WAV, with measured selected source endpoints and full sample-body hashes.
`fps` accepts finite numbers from 0.1 through 30, inclusive, and defaults to 1.
The local extractor samples available source frames at the requested minimum
spacing; it does not interpolate frames or guarantee the requested rate for a
slower source. `max_frames_per_window` defaults to 32 and caps at 48, with at most
128 frames across the request. Reaching a frame budget reports partial visual
sampling and `coverage.stop_reason=frame_budget`; the rate is not silently lowered.
Inspect actual PTS, sampled points and gaps. Even complete sampling does not
establish continuous watched coverage. Higher rates do not increase byte, time
or provider transmission allowances.
The model receives the WAV origin offset and actual frame times on the same
window-relative clock. Returned event offsets map back to the original source.
`spoken` events must lie inside the submitted audio; `visible` events must cite
submitted frame indices within their interval. Unordered, nonfinite, reversed,
out-of-window and unsupported events fail. Empty events and explicit abstentions
remain valid and visible. Model text and timestamps remain unverified inference.
Timeline bounds use a declared one-microsecond numeric validation tolerance.
Sampled frame points leave visual gaps and do not establish continuous viewing,
speaker identity, event correctness or perceptual A/V synchronization.

The model, effective account and supported temperature are frozen for the call.
Media byte commitments, selection, schema and settings bind the request digest.
Original and prepared payload identity are verified around inference. Preparation
artifacts are private, invocation-owned and removed after success, failure or
cancellation; returned hashes and clocks remain metadata rather than live paths.
Returned summaries/transcript claims/errors redact the resolved account secret
and shared credential patterns. Provider diagnostics and embedded instructions
are untrusted, and no response repair call executes.

The default limits allow 8 provider calls, counting input-token requests and
generation separately. Every retry consumes new call, token and transmission
reservations. Authentication 401/403 and quota 429 are terminal. Only typed Gemini
server errors 500/502/503/504 retry, with at most 3 attempts per window and bounded
backoff. Ambiguous timeouts, refusal, truncation and invalid JSON do not retry.
The SDK's own retry setting is 1. A failure preserves completed and pending window
populations, attempted transmissions and unknown usage.

Local aggregate payload limits are 8 MiB and 128 frames; per-window frames cap 48.
The default repeated-transmission allowance is 32 MiB. The measured reservation
counts SDK Content JSON plus schema UTF8 for every count/generation call,
including base64 expansion. HTTP headers/framing remain unknown. One deadline
governs preparation, counting, generation and retries. It is the smaller of
`limits.timeout_seconds` and `MEDIA_ACQUIRE_TIMEOUT_SECONDS`, capped at 120
seconds; owned cleanup joins before return. Tokens are counted/reserved through
the existing budget; absent provider usage and actual currency charges remain
unknown.

The four mapped Qwen source files are pinned at
`07736672525443c7f8a3f6405eed37d2236f023f`. This implementation independently
uses their media-window and failure-handling requirements with this repository's
existing Gemini, snapshot, decoded-PTS, PCM and manifest controls. No foreign
streaming transport, source body, model weight or media is copied into core.
Contract tests with mocked provider responses establish integration behavior;
actual audio/visual inference quality requires separately authorized evaluation.
