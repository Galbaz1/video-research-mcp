# Optional Qwen spatial source component

This component admits the unmodified Qwen-MM-Plugins spatial source at revision
`07736672525443c7f8a3f6405eed37d2236f023f` and provides an owned boundary around its
19 original tool specifications. Its current state is **source component only,
runtime not activated**. It is disabled in the core server and has no core dependency
or tool-registry changes.

The original twelve-package
profile retained its OpenCV/FFmpeg license contradiction. The narrower
ten-package profile retained 41 Matplotlib legacy AFM fonts without a mapped
grant. The descriptor records `blocked-missing-font-grant`, a null selected
Python executable and no runtime bootstrap selection. Neither profile has been
installed or imported for this component. A separate AFM-free candidate has passed
static qualification with the corrections below and has been installed privately
with byte readback. Admission and native loading remain separate steps. The fixed 28-control geometry plan and
eight authorized PNGs are **UNRUN**. Source hashes and owned unit checks do not
constitute component, geometry, model, physical, hardware or release acceptance.

The external source has its complete Apache-2.0 grant. This repository ships
first-party adapters and a descriptor, with upstream attribution in
`THIRD_PARTY_NOTICES.md`; it does not copy the external source or assets. The
descriptor selects 54 complete execution-source bodies, one `LICENSE` grant,
all 19 original tools and the mandatory 16-tool subset. Those 54 files are the
static upper bound, not a claim about the actual imported footprint.

## Source-only check

Run the owned script with an explicit isolated Python interpreter. `--check`
uses stdlib only: it hashes the independently selected descriptor, every
selected source and grant, and the authorized input manifest and files. It
refuses extra entries in upstream tool or expert discovery directories, changed
bytes, symlink paths, unknown scene/frame paths, malformed scenes and output
directories that already exist. It does not create output, import Qwen or a
scientific package, launch a process, install packages or contact a provider.

```sh
/absolute/python -I -B /absolute/repository/scripts/spatial_session.py \
  --source-root /absolute/qualified/Qwen-MM-Plugins \
  --manifest /absolute/repository/integrations/qwen/video-spatio.json \
  --manifest-sha256 INDEPENDENTLY_TRUSTED_DESCRIPTOR_SHA256 \
  --inputs /absolute/authorized/inputs.json \
  --inputs-sha256 INDEPENDENTLY_TRUSTED_INPUTS_SHA256 \
  --output /absolute/absent/spatial-session \
  --check
```

The present result has `sources_admitted: true`, `inputs_admitted: true`,
`state: "source-only-runtime-blocked"`, `ready: false` and
`foreign_imports: 0`; its exit code is 2. A serving invocation also exits 2
before any foreign import and before output creation. A successful source check
does not clear the dependency-grant block.

Future serving eligibility requires the exact descriptor value
`verified-selected-runtime-grants`, its explicitly selected Python 3.12.13
venv-prefix executable, admitted bootstrap files, and exact installed metadata
for MCP 1.30.0, Pillow 11.3.0, OpenAI 1.109.1, AnyIO 4.15.1, Pydantic 2.13.5,
docstring-parser 0.18.0, NumPy 2.4.4 and Matplotlib 3.10.9. The adapter does not
create, install or substitute that runtime. It preserves the venv-prefix
executable path rather than resolving it into the base interpreter.

## Admit an installed runtime before launch

For an eligible private descriptor, start `scripts/spatial_launch.py` with a
trusted interpreter and `-I -S -B`, using the same source, manifest, input,
output and digest arguments above. The launcher checks the descriptor digest,
exact CPython executable and libpython bytes, direct venv-prefix symlink,
`pyvenv.cfg`, selected bootstrap files and complete installed site-packages
inventory before starting the selected interpreter. Missing, changed, extra,
linked or nonregular package files are refused. The concrete runtime uses
Python's standard `venv --without-pip`; every `.pth`, `sitecustomize` and
`usercustomize` entry is refused.

After admission the launcher replaces itself with the selected interpreter,
preserving one supervised PID for cancellation. The selected process runs with
`-I -S -B` and repeats admission before adding the
selected site-packages directory. It verifies installed versions and reads
back source, input and runtime bytes around each handler. Admission assumes
trusted owned scripts and an independently trusted descriptor digest; the
process retains host privileges. It copies exactly the 54 admitted source bodies
and their grant into a fresh private import tree. Ambient upstream modules and
bytecode are excluded. The complete copied inventory and original selected bytes
are rehashed before imports and around each handler.

The selected Agg/PNG route seeds an empty cache for the pinned Matplotlib font
manager before import, then initializes only the 38 admitted bundled TTFs.
Font discovery and font requests are confined to those paths; receipts record
initialized fonts and successful font requests separately from imported
modules. A request receipt alone does not verify glyph selection or pixels.

The private installation retained all 2,157 base files: 2,147 site-packages
files and ten console wrappers. The wrappers retain their original bytes and
old-prefix references; they are unused artifacts. This route invokes only the
explicit selected `bin/python3.12`. Its ten additional wheels use exact local
archive URLs, enforced hashes, no dependency installation and copied payloads.
Installer-generated metadata and RECORD updates are recorded separately from
unchanged wheel payload bytes. No private machine paths or active selection are
written into the shipped descriptor.

## Authorized inputs and output boundaries

An input manifest has this explicit shape. `path` values select absolute regular
files; `bytes` and lowercase SHA256 bind their exact contents.

```json
{
  "schema_version": 1,
  "source": {"sha256": "SOURCE_DIGEST", "revision": "explicit source revision"},
  "frames": [{
    "path": "/absolute/frame.png",
    "sha256": "PNG_DIGEST",
    "bytes": 123,
    "source_frame_id": 101,
    "pts": 25,
    "time_base": [1, 25]
  }],
  "scenes": [{"path": "/absolute/scene.json", "sha256": "SCENE_DIGEST", "bytes": 456}]
}
```

Frames must have unique paths and IDs, finite strictly increasing actual
PTS/time-base clocks, at most 64 frames and at most 16 million pixels per PNG.
These clocks preserve source timing; they do not infer a constant frame rate.
Only these image paths and scene files are available to handlers. The selected
scene route refuses legacy NPY and base64 point/mask inputs.

Scenes retain the original `video-spatio/scene@1` format. Their frame indices,
image paths, camera/instance keys and instance references must match admitted
source IDs. Numeric fields must be finite; dimensions, depth, scale and focal
lengths must be positive, bounding boxes ordered and contained, and camera FOV
between zero and 180 degrees. Instance IDs must be unique within each frame;
the same ID cannot carry conflicting labels across frames. Provided persistent
IDs remain caller assertions. Generated IDs become
`frame:<source_frame_id>:instance:<position>` and cannot imply tracked identity.

The optional serving route would create one exclusive output directory with
owned cwd, configuration, cache, Matplotlib and temporary directories, and an
empty owned Qwen configuration. It preserves `HOME` and `CODEX_HOME` through an
explicit environment whitelist, drops credentials, selects native image mode
and disables automatic launch/install behavior. This is an admission and
provider boundary running with host privileges; it is **not a sandbox**.

Every handler shares one lock through source/input admission, original expert
execution, result handling, readback and evidence writing. Changed source or
input bytes and exceptions yield explicit refusal JSON. A serving session would
retain `loaded-startup.json` and `calls.jsonl`, including hashes of actual loaded
module/bytecode paths, stdlib files and runtime bootstrap files beyond the
54-file static upper bound. No actual imported spatial footprint exists while
the runtime is blocked.

## Original tools and owned corrections

The adapter preserves the original input schemas and registry discovery for
`assess_coverage`, `assess_reachable`, `build_scene`, `calibrate_scale`,
`camera_motion`, `count_objects`, `match_entities`, `mobile_manip`, `motion`,
`object_world_motion`, `orient_facing`, `plan_exploration`, `render_scene_views`,
`scene_map`, `select_keyframes`, `triangulate`, `verify_grounding`, `view_reason`
and `visualize_bev`.

All actual `VLMShim._dispatch` attempts are denied. A per-thread marker survives
upstream error swallowing: a caught provider error cannot become a false
“absent” or “not found” result. `orient_facing` and `verify_grounding` retain their
advertised specifications and return `provider_unavailable`. Visibility and
line-of-sight operations receive the same explicit provider refusal.

The deterministic `view_reason` layout/projection operations delegate the
original `ViewExpert` using reconstruction without images. Outputs explicitly
label `geometry_assumed_facing` and `model_orientation_unverified`. Virtual BEV
viewpoints require explicit valid origins and facing directions. Frame-specific
object origins are resolved through the original geometry helper; missing or
ambiguous targets cannot silently become the origin. Unknown frames, operations
and keyframe strategies are refused.

Mobile dispatch uses the actual original target/frame/images signatures,
including `suggest_approach`, `check_object_in_view` and
`search_object_across_frames`. Cross-frame search/trajectory operations refuse
a frame selection they would otherwise ignore. Geometric targets must exist
unambiguously. Missing object-world-motion evidence remains `unknown`, with
`is_moving: null`. Uniform keyframe positions map back to original source IDs.

Cross-view counts and matching remain heuristics. An owned conservative guard
refuses a proximity component that could merge two distinct same-frame
sightings, including transitive collisions. Same-frame count operations retain
both sightings. These checks do not establish physical object identity.

Owned appearance segmentation converts PNGs through Pillow `L`, resizes mixed
dimensions using Pillow `BILINEAR`, then computes float32 mean absolute change
divided by 255. It uses the original automatic threshold formula
`max(0.02, percentile60 * 0.5)`, strict `>`, inclusive runs of at least two frames,
and an initial still frame in the moving-ratio denominator. Outputs retain
source frame IDs and explicitly declare the Pillow/OpenCV resampling difference.
Appearance change may arise from the camera, lighting or objects; it proves no
physical motion. Point prediction delegates the original polynomial expert,
returns its flat result dictionary and requires finite consistent 2D/3D input
and complete finite outputs, with at most 32 future steps and polynomial order 5.

All results carry provenance for source clocks, unverified persistent identity,
caller depth/camera estimates, assumed generated FOV60/pinhole optics and the
declared metric scale that downstream experts do not consistently apply. Unit
tests use original-expert/provider stubs; first-party motion units may use the
already qualified root NumPy/Pillow dependencies. That root unit environment
does not qualify or replace the blocked selected spatial profile.

## Prepare a separate PNG payload

`vrm-0e8.9.12` provides a stdlib-only builder for the exact pinned Matplotlib
3.10.9 macOS ARM64 CPython 3.12 wheel. It removes its 60 AFM metric files, retains
all 38 TTF fonts and every other payload byte, and rebuilds RECORD with change
attribution. The current spatial callers select Agg/PNG, whose text and mathtext
paths use TTF/FreeType. PDF/PostScript AFM modes are outside this selected PNG route.

```sh
python3 -I -B scripts/spatial_png_payload.py \
  /absolute/qualified/matplotlib-3.10.9-cp312-cp312-macosx_11_0_arm64.whl \
  /absolute/existing-parent/absent-png-payload
```

The input archive must match its pinned SHA256. The absent output directory
receives a derivative wheel with the original basename and `receipt.json`; use
its derivative hash to distinguish it from upstream. The receipt binds retained,
removed, added and rebuilt members. Existing output, symlink paths and untrusted
input are refused. No original archive or installed package is edited.

This builds an alternate payload; it does not install or import Matplotlib,
activate fonts, select a third runtime or qualify pixels/geometry. Original
rejected profiles and all 28 UNRUN controls remain retained. Whole-runtime grant,
bootstrap, actual load and geometry evidence are still required before serving.

## Static qualification of the PNG runtime

`vrm-0e8.9.13` qualifies one exact candidate for a later isolated installation:
the same ten wheel versions and unchanged 36-package base, substituting only
the derivative Matplotlib wheel with SHA256
`4c8dcf94bd4e5065322673b6ec5e6a500520653e4f852ce10276119cdfbe30a6`.
Independent checks cover 1,921 selected wheel members, 2,157 preserved base
files, 38 TTF fonts, 67 native files, and 66 active dependency edges. This is
publisher-byte and component-family evidence. It does not certify a reproducible
binary build, exact compiled dependency revisions or actual loading.

The independent review re-derived the static packet and required five metadata
corrections. The corrected packet records that reproducibility evidence rather
than claiming its original checker generates every grant map. ContourPy's
native extension now carries its pybind11 family binding. Static markers imply
pybind11 3.0 or later; the exact compiled revision remains unknown. The retained
[v3.0.1 license](https://github.com/pybind/pybind11/blob/v3.0.1/LICENSE) is byte-identical
to the earlier v2.13.2 family text. Non-font Matplotlib files no longer inherit
unrelated font notices. The Adobe notice is retained with zero shipped AFM
subjects; sample-data and image assets have top-level license evidence only,
with per-asset provenance explicitly unknown.

Admission must use explicit archive paths and enforced hashes, with no dependency
resolution or filename-based wheel substitution. Create a separate environment
from the exact realpath Python 3.12.13 executable, rehash its executable and
libpython, and admit its new prefix link and bootstrap. Copy the 2,157 qualified
base files to corresponding paths and verify every destination byte before
installing the ten disjoint wheels. Retain the full grant directory, notices and
corrected maps. Before activation, verify the complete installed file inventory,
the preserved base and fresh bootstrap again.

The checked-in descriptor remains disabled. Neither historical rejection is
reclassified, and all 28 frozen geometry controls remain UNRUN until the actual
candidate installation and serving journey are evaluated.
