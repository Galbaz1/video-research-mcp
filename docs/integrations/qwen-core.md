# Optional original core preview session

The optional session keeps QwenLM/Qwen-MM-Plugins' seven original tool names and
input schemas at revision `07736672525443c7f8a3f6405eed37d2236f023f`. The original
source remains external and unchanged. The source grant is Apache-2.0; retain its
complete LICENSE and applicable attribution/notices when providing that source.
The owned admission, file-copy and worker code is independently authored. No
original distribution, native binary, font, model or asset is bundled here.

The checked-in `integrations/qwen/core.json` is deliberately source-only blocked.
It records 40 selected Python bodies, the grant and project declaration, seven
schemas, all 75 extension spellings (74 lowercase spellings) and the 62-entry
renderer registry. These are source contracts. Actual foreign startup, MCP
discovery and preview acceptance remain separate checks. Ordinary root-server
startup does not import this source or its optional dependencies.

## Read-only admission

Supply an independently trusted descriptor SHA and input-authority SHA. Input
authority has exactly this shape:

```json
{
  "schema_version": 1,
  "files": [
    {"path": "/absolute/canonical/operator.py", "bytes": 20, "sha256": "FULL_SHA256"}
  ]
}
```

Paths must be canonical absolute regular files, with no URL, symlink, traversal
or alias. Admission reads complete bytes and joins file identity around each
read. The authority admits 1–32 nonempty files of at most 8 MiB each and is at most
128 KiB. Originals and authority are rechecked before and after each call.

```bash
SELECTED_PYTHON -I -B -X pycache_prefix=/absolute/absent/private-bytecode \
  scripts/core_session.py \
  --source-root /absolute/unchanged/qwen-source \
  --manifest /absolute/operator-selected-profile.json \
  --manifest-sha256 FULL_DESCRIPTOR_SHA256 \
  --inputs /absolute/operator-inputs.json \
  --inputs-sha256 FULL_INPUTS_SHA256 \
  --output /absolute/absent/owned-session --check
```

`--check` never creates output, imports foreign code, launches native processes,
installs packages or contacts a provider. A blocked profile reports source/input
admission and per-family prerequisite state, then exits 2. This is useful source
readiness evidence; it is not preview completion. Omit `--check` only for an
explicitly qualified selected profile; a blocked profile refuses before import.
An existing output directory is refused. Restart does not silently resume workers,
regenerate products or trust an editable prior receipt.

## Selected profile and actual startup

The operator-selected private descriptor retains the portable source descriptor
and sets `runtime_clearance` to `verified-selected-runtime-grants` only after
qualification. `runtime_fields` supplies `python_executable`, `python_prefix`,
`python_binary` (`path`, `bytes`, `sha256`), three exact `bootstrap_sources`, and
`runtime_manifest` / `runtime_grants` references (`path`, `bytes`, `sha256`). The
runtime manifest is bounded to 1 MiB and contains `schema_version: 1`, all 2,157
selected installed-file rows and all 36 package versions. The grant manifest
contains all 40 qualified grant-body `rows`; it is also bounded to 1 MiB. No
machine-specific paths or cleared runtime are selected by the packaged default.

The current candidate base uses Python 3.12.13 and MCP 1.30.0, Pillow 11.3.0,
OpenAI 1.109.1, AnyIO 4.15.1, Pydantic 2.13.5 and docstring-parser 0.18.0, plus
the complete selected transitive population. These versions alone do not qualify
execution. The actual interpreter prefix, binary, bootstrap, every runtime file,
grant and direct/transitive version must join the private profile. Parent and
each child require `-I -B` and an absolute **absent** `pycache_prefix`, so existing
unadmitted cached bytecode is not read. Existing caches are preserved.

Actual startup compares all original schemas and lazy registry exports, without
loading heavy renderers. `loaded-startup.json` retains actual full normalized
specs, descriptions, supplied annotations/output schemas, all extension exports,
registry entries and the full loaded file footprint, including stdlib/bootstrap
bytes beyond the static original-source upper bound. Each child also retains its
loaded footprint. Source eligibility and installed-distribution completion are
separate; the original distribution installation criterion remains unaccepted.

Format admission is separate from base runtime admission. Only code, subtitle
and PNG image paths may be selected by this component, with each explicit
`format_clearance` state `verified-selected-format-profile`. All other backends
remain refused before the original handler. `read_video`, `media_info` and
`save_view` require unqualified native/materialized backends. `draw_bbox` loads
an unqualified font even with empty labels, so it also refuses before dispatch.
All seven schemas remain discoverable. No new format-clearing machinery is
advertised by this component.

## Calls, files and receipts

Each call runs in one fresh owned process group using a byte-identical private
copy of its admitted source. Crop output and returned images belong to that
call's separate products directory; originals cannot be output destinations.
Explicit output paths must be fresh leaf names within the owned namespace.
There is one common 30-second call deadline and one admission/handler/readback
lock. Result blocks and returned metadata are bounded to 4 MiB; exceeding a cap
is a refusal, never a truncated complete result. Logs are bounded and kept in
the owned call directory.

PNG admission bounds the source grid before metadata decoding and the actual
planned 32-pixel preview grid before the original resize. EXIF orientation and
crop coordinates are included. Code coverage uses the original renderer's
universal-newline physical lines; Unicode separators inside strings do not imply
skipped lines.

`visualize` retains the original schema's `max_pages` default of 20. For this
bounded session, callers must explicitly choose an integer from 1 through 4.
Explicit ranges cannot exceed that cap. The selected code, subtitle and image
branches ignore original page selection; only an omitted range or page 1 is
admitted. The original code renderer's 500-line limit is disclosed with retained
and skipped line counts and `partial` status. Subtitle cues are original text
extraction; timestamp alignment and spoken-content meaning are unvalidated.
Original image/text blocks and their labels are retained as actual evidence.
Warnings, failures and partial results are not promoted into complete rendering.

Each call persists a pending receipt before execution, an early PID/group record,
the complete result and terminal source/copy/derived identities. Interrupted,
refused and failed calls remain present. EOF, deadline and signals stop and reap
only the owned worker group; EOF cleanup starts before the upstream framework
joins its cancellation-shielded calling thread. Late work is refused. Shared EOF
cleanup is reused from adjacent `blender_stdio.py` in a checkout and from
`blender/scripts` in the current wheel resource layout.

HOME and CODEX_HOME are preserved. The child receives an explicit small environment
without credentials or unowned Python module paths, an empty owned Qwen config,
owned cache/cwd/tmp and native mode enabled. Python audit checks deny network,
provider, unselected heavy imports, native subprocess branches and writes outside
the owned session; a swallowed denial still fails the call. This is a controlled
ordinary-host process, not an OS sandbox. The unread `shared.api_openai` caption
branch is forbidden and no readiness result authorizes provider submission.

## Completion boundary

The fixed workflow denominator remains PDF, Office, tables, HTML, diagrams,
notebooks, code, subtitles, 3D, GIS and NIfTI, plus ancillary image operations.
Heavy/native/font/viz formats remain unqualified. Their schema or extension
inventory, code fences, text fallbacks, a successful source check or a cleared
base runtime cannot establish actual rendering across those families. GIS labels
do not establish CRS/measurement accuracy, NIfTI center slices do not establish
clinical geometry, and diagrams do not establish topology equivalence. Semantic
accuracy, visual acceptance and whole-leaf completion remain unverified.

The primary verification uses first-party file and image fixtures plus original
handler/process contracts. Actual foreign-runtime/MCP/fixture and packaged
acceptance belong to the separate root gate; this document records no successful
actual preview journey.
