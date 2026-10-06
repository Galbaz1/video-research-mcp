# Optional local timed ASR service

`scripts/local_asr_service.py` is an explicitly launched, serial HTTP service.
`scripts/local_asr_worker.py` performs one bounded faster-whisper inference per
request in an already installed optional environment. Neither installs packages,
downloads models, starts automatically, calls a provider, nor changes core
dependencies. The worker exits after each request and releases its model.

Qualification includes real service/worker startup, Dutch and English word output,
exact PCM preservation, five exports and durable readback. Initial HTTP timeouts
and interval-type refusals are retained. The worker converts real NumPy timestamp
scalars to Python floats without changing their values; boolean, nonfinite and
out-of-range timestamps still refuse. Acoustic, word-alignment and speaker
accuracy remain unverified. Each optional installation requires its own exact
descriptor and runtime qualification; this source component is not a new release.

The service accepts only literal `127.0.0.1` or `::1`. Its 60-second worker
deadline includes worker admission, but starts after HTTP body intake and the
service's admission recheck. The 10-second socket timeout bounds an idle read;
a client sending bytes slowly can prolong intake. There is no shared deadline
for headers, body intake, service admission and inference. Whole-request intake
remains unqualified, and the serial service can be occupied before a worker starts.

During inference, a client disconnect, worker deadline, SIGINT or parent-only
SIGTERM kills the active worker process group and joins the direct child. SIGKILL
cannot run cleanup; use SIGTERM for operator cancellation. Keep the client
connection open while waiting, including its write side. Exact Host checks and
rejection of browser Origin headers restrict the loopback service; they do not
repair the intake deadline gap.

The already bounded request is passed through an anonymous temporary file to the
worker's stdin. This avoids an observed CPython 3.12 pipe-transfer stall when a
short `communicate()` timeout occurs before the worker finishes admission. The
temporary file is closed in the parent after spawn and disappears when the child
exits; retained source WAVs and runtime files are unchanged.

## Exact admission and supported launch

Use a trusted Python with `-I -S -B` to run `scripts/local_asr_launch.py`.
The launcher verifies the independently pinned **schema version 2** descriptor
before starting the optional Python, then replaces itself with `execve`. The
supervised PID remains the service PID. Direct execution of service/worker files
refuses. Each inference child uses this same trusted launcher with `--entry worker`.

The descriptor binds these concrete identities:

- `sources.launch`, `sources.service`, `sources.worker`: absolute source paths,
  byte counts and SHA256 values; `script_sha256` and `worker_sha256` retain the
  wire receipt identities. Bootstrap compiles the exact verified source bytes.
- `runtime.python`, `python_sha256`, `lineage`: selected executable, resolved
  binary and every symlink in its selection, including ancestor links.
- `runtime.base_directory`, `libpython`, `pyvenv`: canonical base installation,
  exact libpython and pyvenv configuration records. Bootstrap checks the effective
  Python version, base prefix and prefix under site-disabled startup.
- `runtime.base_inventory` and `runtime.inventory`, each with its independent
  `_sha256`: complete base and optional runtime populations, including directories,
  native libraries, symlinks, metadata and bytecode. Inventory rows record `path`
  relative to the root, `kind` and exact file size/hash or link target/realpath.
  Both full populations are compared; new files, links and specials refuse.
- `runtime.stdlib_paths`, `site_packages`, `absent_paths`: the exact cold stdlib
  import path, one verified optional package path, and absent bootstrap/zip paths.
  The initial import path must match before the optional package path is appended.
  CPython 3.12 uses the pinned pyvenv `home` spelling for `lib-dynload`; its uv
  alias is accepted only through the already pinned executable link lineage.
- `runtime.versions`: Python, faster-whisper, CTranslate2 and NumPy identities.
  Metadata is read without importing model libraries.
- `models.en` and `models.multilingual`: absolute directories, source repositories,
  revisions and exactly four sized/hashed files each: `config.json`, `model.bin`,
  `tokenizer.json`, `vocabulary.txt`. The entire directory populations must match.

The bytecode policy is `complete-inventory`: dependency `.pyc` files are expressly
admitted bytes. `-B` prevents writes; it does not disable reading bytecode.
Adjacent scripts and their caches never enter `sys.path`; service and worker are
compiled from verified source, independent of sibling `.pyc` or source shadows.
A configured external bytecode prefix refuses. The complete base inventory also
covers the stdlib/native extension bytes used during optional startup.

The `.pth` policy is `inactive-exact-virtualenv-only`. The existing
`lib/python3.12/site-packages/_virtualenv.pth` containing exactly
`import _virtualenv` (SHA256
`69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d`)
is retained as inactive bytes. `-S` prevents `.pth` processing and `site` startup.
Other `.pth`, `sitecustomize` and `usercustomize` files refuse even when inventoried.
No hooks or packages are removed, installed or rewritten.

Readiness executes the actual optional bootstrap and exact entry sources without
listening or importing models:

```bash
/absolute/trusted/python -I -S -B /absolute/scripts/local_asr_launch.py \
  --descriptor /absolute/new-descriptor.json \
  --expected-descriptor-sha256 EXACT_NEW_DESCRIPTOR_SHA256 \
  --entry service --check
```

Use `--entry worker --check` to qualify the worker entry. For an authorized service
launch, remove `--check` and specify `--host 127.0.0.1 --port 8766` (or literal `::1`).
Port zero chooses an ephemeral port. Startup emits the actual address, service PID,
protocol and descriptor digest. `GET /healthz` returns the admitted identity and
`inference:false`. Readiness and health do not qualify native inference.

The trusted Python, owned launcher/bootstrap source and independently supplied
descriptor digest are the trusted boundary. Admission assumes these and the
admitted trees remain under operator control between reads and execution. macOS,
its loader and system framework libraries remain host trust. This is not an OS
sandbox or protection against concurrent hostile filesystem replacement. Environment
selection removes ambient Python/dynamic-loader overrides. No ambient script directory
or user/site startup path is admitted.

The repaired descriptor and new inventories live in the private
`continuation-2026-10-04/local-asr-admission-repair` packet. Prior descriptors,
HTTP timeouts, source WAVs and model/runtime trees remain unchanged. An altered
runtime requires explicit fresh qualification and a new descriptor.

## Wire contract

`POST /v1/transcribe` requires `Content-Type: application/json`, exactly one
positive Content-Length no greater than 2 MiB, no Transfer-Encoding and a Host
equal to the selected literal loopback address and port. The body has exactly four
fields:

```json
{
  "audio": "data:audio/wav;base64,<actual WAV bytes>",
  "audio_sha256": "SHA256 of the decoded WAV container bytes",
  "language": "nl",
  "glossary": ["kwadraat"]
}
```

WAV bytes must be at most 1 MiB, with an exact RIFF container extent and complete
uncompressed mono 16000 Hz signed 16-bit PCM, positive duration at most 30 seconds.
The digest identifies the submitted WAV bytes, including its header. File paths,
URLs, other audio formats, duplicate JSON fields and nonfinite JSON are refused.
Language is `null`, `en` or `nl`; glossary is a list of up to 32 nonempty strings,
each at most 128 characters. No unsupported hint is silently discarded.

`en` selects the pinned English model; `nl` and `null` select the pinned
multilingual model. Language is forwarded directly; glossary strings are joined
with spaces and passed as faster-whisper `hotwords`, with an empty list becoming
`null`. Hints do not constitute a reference transcript or a guaranteed correction.
Inference uses CPU, four threads, one worker, requested int8, beam size 5,
temperature 0, word timestamps enabled, VAD disabled and previous-text conditioning
disabled. PCM is normalized to a float32 array before inference, avoiding the
previously retained PyAV file-decoder incompatibility. No fallback is attempted.

A successful response is at most 128 KiB:

```json
{
  "protocol": "faster_whisper_v1",
  "answer": {
    "outcome": "transcript",
    "segments": [{
      "start_seconds": 0.125,
      "end_seconds": 0.875,
      "text": "Hallo wereld",
      "speaker_id": null,
      "words": [
        {"text": "Hallo", "start_seconds": 0.125, "end_seconds": 0.4},
        {"text": "wereld", "start_seconds": 0.45, "end_seconds": 0.875}
      ]
    }],
    "abstentions": []
  },
  "receipt": {"descriptor_sha256": "...", "audio_sha256": "..."}
}
```

`answer` is the existing `ASRAnswer` shape. Empty model output returns `empty` with
empty segments and abstentions. Segments and words are actual model results, with
finite positive intervals relative to the submitted PCM, ordered starts and
matching text; each segment contains at most 128 words and an answer at most 128
segments. Missing/invalid word output fails the request. Speakers are always null.
The receipt includes descriptor/service/runtime inventory hashes, selected model
repository/revision/file hashes, submitted audio digest/duration, exact inference
settings, observed language, effective compute type, inference elapsed time,
worker/service PIDs and peak RSS bytes on the qualified macOS host. Accuracy, word
alignment and speaker identity verification flags remain false.

Errors use `{error:{code:...}}`: 400 invalid body/audio, 403 nonliteral Host or
Origin, 404 unknown endpoint, 413 empty/oversized body, 415 content type or transfer
encoding, 503 changed admission, 504 inference deadline, and 502 failed/oversized
worker output. A disconnected client receives no answer. Errors never contain
fabricated partial transcripts or trigger a retry.

## Explicit MCP configuration and qualification boundary

The core already supports the explicit `faster_whisper` backend and
`faster_whisper_v1` protocol. Configure the actual chosen loopback address and
**new** descriptor digest through `ASR_SERVICE_JSON`:

```bash
export ASR_SERVICE_JSON='{"base_url":"http://127.0.0.1:8766","local":true,"runtime_qualified":true,"protocol":"faster_whisper_v1","expected_descriptor_sha256":"EXACT_NEW_DESCRIPTOR_SHA256"}'
```

`runtime_qualified` is an operator assertion. Select `backend: "faster_whisper"`
in the transcript request. The core sends the selected WAV/digest and hints,
checks the protocol, descriptor identity, audio duration and inference settings,
validates `answer` with the existing `ASRAnswer`, and retains attempts, costs,
serialized bytes and timing. Configuration and wire semantics are included in
its task/request digest. Its existing window projection/export/readback adds the
actual source-window origin; the service returns submitted-PCM-relative times.
The Qwen `/asr` path retains its separate untimed contract and required-option
refusals. Model libraries remain outside core dependencies.

The original two raw HTTP attempts timed out before model import; their failure
evidence and sole temporary-file IPC correction are preserved. Root separately
owns binding and running the reserved corrected actual NL/EN MCP trial after
source/package admission. This repair qualifies source/runtime admission with
inert checks only; it runs no model or native service listener. Accuracy, exact
YouTube source origin, independent speaker attribution and original A19/A20 remain
unqualified. The original twenty-control cohort is not rerun. Native acceptance,
parent acceptance, package installation and release remain separate gates.
