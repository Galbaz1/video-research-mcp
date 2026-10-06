# Bounded live evidence

The `live-evidence` subserver imports and reads supplied replay events without
recording, parsing media, running models, or calling a provider. It preserves
speech, OCR, frame and browser events on one declared media clock. Optional
screen/window capture is an explicit operator workflow in a separate process.

Replay observations remain supplied evidence. An `observed` label describes the
producer's declared basis; replay cannot authenticate the producer or establish
that a physical acquisition happened. Speech recognition and OCR remain inference,
supplied captions remain source assertions, and timestamp co-occurrence establishes
correlation rather than causation. Source qualification and native acceptance are
separate.

## Replay and read

Call `live_replay` with a `ReplayRequest`. Supply a local `store_dir`, stable
`session_id`/`revision`, `clock_id`, integer `tolerance_us`, exact local originals,
and 1–100 typed events. Each source has its original ID, revision, SHA-256,
positive rational `time_base` such as `1/48000`, integer `offset_us`, and an
`observed` or `inferred` clock basis with its description. Each event binds a
source ID and preserves its original integer `timestamp_ticks` and
`duration_ticks`. Its `reference_us` is the declared alignment reference.

The mapping is exact rational arithmetic:

```
common_seconds = timestamp_ticks * time_base + offset_us / 1000000
```

The mapping must fall within the declared tolerance of `reference_us`. This checks
the supplied clock contract; it does not measure physical synchronization. Clocks
are bounded to a 24-hour common timeline. Event kinds are:

| Kind | Evidence basis | Additional data |
|---|---|---|
| `speech` | `inferred` or `source_assertion` | Exact supplied text |
| `OCR` | `inferred` | Exact supplied recognized text |
| `frame` | `observed` | Supplied frame observation text |
| `browser` | `observed` | `navigation`, `console`, `network`, or `DOM` category |

Browser text is data. It never starts navigation, runs a script, or changes
configuration. A source may be a captured artifact or a producer evidence record;
the adapter hashes and retains its bytes without interpreting its media format.

Replay retains up to eight original regular files, at most 2 MiB each and 8 MiB
in aggregate. The archive is at most 2 MiB. Every source must be used, all IDs must
be unique within their namespace, and a session revision cannot be overwritten.
The existing regular-file and configured `LOCAL_FILE_ACCESS_ROOT` fences apply.
URIs, symlinks, substituted nonregular files, changed bytes and digest mismatches
are refused. Source artifacts and lifecycle metadata use the existing atomic
publication helper.

The returned `SessionPin` binds the archive's path, session, revision and SHA-256.
Use it with `live_read`. The cursor binds both archive bytes and page size.
Repeating a cursor returns identical events; `next_cursor` advances without
filtering away intervening events. EOF returns an empty page and an unchanged
cursor. Reads work after process restart because the archive owns all event data.
Changing the page size requires starting a new read at the beginning.

There is no background capture queue in replay. Each page reports its exact
`remaining_events` and the frozen producer `queue` telemetry. `depth`,
`dropped_frames`, and `dropped_events` can be null. Supplied counters require
`source_reported` basis; absent counters have `unknown` basis. A reported zero is
not inferred from missing telemetry. Producer queue state is historical metadata.

## Monitor, stop and ordinary library finalization

`live_monitor` checks a literal event kind, optional text substring and minimum
match count. It scans at most `max_checks` pages under one monotonic
`deadline_seconds`, capped at 100 checks and 30 seconds. It reports
`condition_met` or `condition_unmet`, with the reason `max_checks`, `deadline`, or
`end_of_replay` for unmet conditions. A page that finishes after the deadline does
not advance the returned cursor. Returned matches retain their source hashes,
original ticks and observation/inference basis. A monitor call does not capture
new material or execute a proposed correction.

`live_stop` publishes a durable seal adjacent to the archive. `live_finalize`
seals the session, verifies retained original bytes and indexes supplied
observations into the existing ordinary corpus SQLite library. Provide
`index_path` ending in `.sqlite3`, the collection and its `expected_revision`.
The parent directory must already exist. Existing library application identity,
transaction, revision, immutable observation and size checks remain in force.

Speech and OCR keep their existing corpus kinds. Frame and browser observations
use the library's `description` kind, while their original typed kind and basis
remain in the pinned archive. Library intervals use its existing seconds fields;
the archive retains exact rational common times and original integer source
timestamps without rounding or rewriting them. Each library observation references
both its retained original and the immutable replay archive. Stable observation
IDs include the session, replay revision and event ID through a content hash.
New replay revisions therefore retain separate library epochs.

Finalization calls the existing corpus index directly with supplied observations.
It never invokes ingestion, OCR, ASR, embeddings or another media processor.
It retains a durable destination/revision intent before the index mutation. A
receipt interrupted after commit is recovered by comparing exact library payloads.
An occupied intent with no confirmed effect returns `unresolved` and does not
resubmit. Concurrent calls cannot obtain a second mutation allowance. Changing a
durable finalization destination is refused. An unresolved intent needs explicit
Root reconciliation; deleting its intent to retry is unsafe.
Saved receipt bytes are compared to the expected source/destination receipt and
the library payloads are read back again. A missing or changed library leaves the
original receipt intact and returns `unresolved`; a corrupt receipt is refused.

## Capability probe and optional isolated capture

`live_capability_probe` uses executable lookup and filesystem metadata only. It
does not run FFmpeg, enumerate a device through a recording API, request a
permission, install a dependency, or start recording. Explicit device-node paths
report existence and filesystem readability. OS recording permission remains
`UNKNOWN`; filesystem readability does not establish camera, microphone or screen
recording permission. Executable presence does not establish version, device
support or runtime qualification.

An optional `companion_root` must contain the exact five source/license files
pinned below. Their digests are checked before an optional foreign import. Core
startup has no watch-skill dependency. Transitive runtime dependencies and assets
remain separately unqualified.

`live_capture_prepare` accepts an explicit caller-declared operation ID,
screen/window target, exact window title when applicable, finite duration of at
most 30 seconds, retention description and a new output directory. It returns
`unsupported` when the source/runtime prerequisites are unavailable, or an explicit
operator handoff. It never starts recording. These scope fields are declarations;
they do not authenticate a principal or grant an OS permission.

The inspected `watch_skill.loop.capture.capture_screen` uses Windows FFmpeg
`gdigrab`. The adapter reports this route unsupported on macOS/Linux before output
allocation or foreign import. It does not infer support for a different capture
backend. Missing companion dependencies also return unsupported before output
allocation. Actual Windows runtime and device acceptance remain required.

After the operator has separately authorized the exact recording and qualified
the isolated runtime, the operator entry point is:

```sh
python -m video_research_mcp.live_companion --record REQUEST.json
```

Run it in the separately configured companion environment. `REQUEST.json` uses
the `CaptureRequest` schema. The command requires an explicit recording invocation,
imports the pinned companion only in that process, and calls its actual
`capture_screen(out_dir, duration_seconds=..., window_title=...)` API. It refuses an
existing output directory, preserves failures without automatic retry and bounds
artifact readback to 8 MiB. The inspected source bounds its FFmpeg subprocess to
duration plus 120 seconds, at most 150 seconds for this adapter. Artifact production
returns `captured_unqualified`; decode, acquisition fidelity, runtime custody and
native acceptance are still unverified. No microphone, camera, model inference,
permission grant or provider call is introduced by this adapter.

The companion's other source-defined workflows remain available in the separately
operated pinned project: live session start/read/status/aligned evidence/stop,
file adoption and browser capture, observer budgets and event-trigger evaluation.
They are not silently activated by replay. Browser navigation, scripts and other
side effects need their own exact operation authority and runtime qualification.
The local implementation adopts immutable cursor replay, declared clock alignment,
bounded literal monitoring and finalization; it does not dispatch foreign observer
corrections or trigger actions from untrusted evidence text.

## Registration and source checks

The root server already imports and mounts the subserver in `server.py`:

```python
from .tools.live import live_server

app.mount(live_server)
```

The seven tools are
`live_replay`, `live_read`, `live_monitor`, `live_stop`, `live_finalize`,
`live_capability_probe`, and `live_capture_prepare`. Replay adds no core dependency
or configuration field. The optional capture process retains its separate runtime
and recording prerequisites.

Focused source checks are:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest tests/test_live_replay.py tests/test_live_companion.py -q -p no:cacheprovider
.venv/bin/ruff check --no-cache src/video_research_mcp/models/live.py src/video_research_mcp/tools/live.py src/video_research_mcp/live_*.py tests/test_live_*.py
```

These tests use fixed local originals, a fresh Python readback subprocess, actual
ordinary-library transactions, injected clock boundaries and mocked external
capture/OS availability. The dummy companion artifact is not recorded media.
Companion tests use self-contained dummy source bytes and fixture-specific hash
commitments; production pins are unchanged and the actual upstream source/license
byte join is retained separately in the private primary receipt.
Passing these checks establishes source behavior only. Native capture, device
permissions, provider behavior and human acceptance require separate evidence;
registration alone establishes none of them.

## Primary provenance

Independent implementation informed by `oxbshw/watch-skill` at
`f1317c8fe64744a606c31867b05fbbe3144268c6`:

| Mapped source | SHA-256 | Adopted boundary |
|---|---|---|
| `src/watch_skill/live/session.py` | `42a3114b58d611d7fc5244030b7f0cf59d79610a5bd590108de21bb835994304` | Common clock, readback cursor, aligned evidence, explicit stop |
| `src/watch_skill/loop/capture.py` | `1348ec2149176962a45cccfd24b891ba10d1c96a96113d5ee686e9a7d9ca3dde` | Optional isolated source-defined capture API; platform refusal |
| `src/watch_skill/observer/loop.py` | `c9bca2b90e9a2bd47370c28f6a63afc1e8a98c9378e6e1bd1328c8a533f019dd` | Finite budget/deadline and unmet condition |
| `src/watch_skill/triggers/engine.py` | `83ba974c622d41ce524fc8afc02fa2e560004a8da70f400cfde68d53fa86cc71` | Bounded cursor consumption and literal event/count condition |

The exact [MIT code grant](https://github.com/oxbshw/watch-skill/blob/f1317c8fe64744a606c31867b05fbbe3144268c6/LICENSE)
is copyright (c) 2026 oxbshw, 1,063 bytes, SHA-256
`eebd1fe1e58c6555775697c05bdec184584aeeb0ae11b18fcb5403c2ebc4d1ad`.
It was retained with the five exact cached primary files and separately hash-joined
by Root. Production replay code is independently authored. The optional companion
loads the operator's separately installed source; no foreign runtime is vendored
or installed by this feature. Code licensing does not clear assets, model weights,
devices or capture runtime dependencies.
