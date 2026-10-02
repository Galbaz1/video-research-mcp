# Optional Qwen spatial source component

This component admits the unmodified Qwen-MM-Plugins spatial source at revision
`07736672525443c7f8a3f6405eed37d2236f023f` and provides an owned boundary around its
19 original tool specifications. Its current state is **source component only,
runtime blocked**. It is disabled in the core server and has no core dependency
or tool-registry changes.

The selected scientific runtime cannot activate. The original twelve-package
profile retained its OpenCV/FFmpeg license contradiction. The narrower
ten-package profile retained 41 Matplotlib legacy AFM fonts without a mapped
grant. The descriptor records `blocked-missing-font-grant`, a null selected
Python executable and no runtime bootstrap selection. Neither profile has been
installed or imported for this component. The fixed 28-control geometry plan and
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
