# Optional authored renderer qualification

The companion provides a separately selected Remotion entry for the fixed local
qualification fixture. It renders one solid card with one second of original
48 kHz mono PCM16 audio at 1280×720 and 30 FPS. Other storyboards and resolutions
produce an explicit refusal. The existing external CLI remains separately
configured and subject to its recorded source and runtime requirements.

The companion wheel and source archive include the six first-party entry files,
including the exact npm lockfile. Copy these files into a private runtime
directory and install that lock with `npm ci --ignore-scripts --no-audit --no-fund`.
Node, Remotion and its browser remain separately installed runtimes. Their
licenses and eligibility must be checked for the intended use; the recorded
research evaluation does not establish commercial deployment eligibility.

Select the prepared entry with `EXPLAINER_RENDERER_ENTRY`, its absolute frozen
JSON descriptor with `EXPLAINER_RENDERER_SPEC`, and the descriptor's external
SHA256 with `EXPLAINER_RENDERER_SPEC_SHA256`. All three default to empty. The
descriptor binds the six entry files, complete installed module tree, package
versions, Node and browser executables, composition and three fixture inputs.
Readiness checks never install missing dependencies or download a browser.

Use the existing `explainer_render_start`, `explainer_render_poll` and
`explainer_render_cancel` tools. A request requires fresh output and preserves
the current input/runtime identities through execution and full media decoding.
The selected fixture has a 120-second render limit, a 180-second total limit,
concurrency one and a 16 MiB output bound. Completion requires its current
receipt and exact 30-frame H.264/AAC output. Actual browser playback and semantic
quality remain separate acceptance observations.

Mocked tests qualify admission, refusal and job behavior. A successful install
does not establish a native render. The frozen programme retains its original
failed and unrun cases until actual qualification and independent acceptance.

The authored entry pins Remotion, `@remotion/renderer`, and `@remotion/bundler`
to **4.0.532**, with React and React DOM **19.0.0**. The authored freeze checks reject
the former 4.0.242 install even though it shares the same major version. A new
lock and installed tree require fresh source/runtime seals and a browser selected
from this exact renderer version; prior wheel and browser pins do not qualify
the upgrade. Browser acquisition and a native render are separate root gates.

The separately mapped external CLI checks its selected 4.0.242 dependencies and
browser cache; the authored route has independent 4.0.532 package bindings.

The entry synchronizes Node builtin ESM exports while capturing the owned browser
process, then restores the original spawn binding. Rendering explicitly selects
`colorSpace: 'bt709'` and `pixelFormat: 'yuv420p'`; the receipt records both.
This avoids the default JPEG/full-range output observed with Remotion 4.0.532.

The October 4 local qualification rendered its selected companion wheel's fixed
fixture and decoded all video frames and audio packets. The 46,124-byte MP4 had
30 H.264 frames, 1280×720 dimensions, limited-range BT.709 `yuv420p`, 48 kHz stereo
AAC and a 1.003-second container duration. A separate browser observation loaded
the same SHA256 and played all 30 frames through the ended event without a media
error. The render reported 7.78 seconds; the complete native and playback epoch
took 130.68 seconds within its 180-second limit, with all registered process groups
absent after cleanup. Earlier failed attempts are retained in the programme
receipts. This qualifies the fixed fixture; production storyboards and general
visual/audio fidelity still require their own evidence. The job's conservative
`real_renderer_verified` field does not incorporate that separate UI observation.

For this fixture, `fast` remains a recorded request setting and does not alter
encoding quality. Qualification labels the selected route as
`authored fixed-fixture entry` and records `quality: fixed`, `fast_applied: false`.
The separately configured CLI continues to receive its supported `--fast` flag.

## Caller-authored production storyboard route

`production_entry.mjs` is a separate optional entry for a local production
storyboard. It uses the same pinned Remotion 4.0.532 runtime and does not change
the fixed-fixture entry or its evidence. The companion archives also include
the two production entry modules and four TypeScript/React sources.

Select it through the existing renderer settings, with an externally frozen
`vrm-authored-storyboard/r1` descriptor and `composition_id: Production`.
`entry_sha256` binds the eight production files: the existing package and lock
files, both production modules, and the four production sources.
`project_sha256` binds exactly `config.json`, `storyboard/storyboard.json`,
every regular `.ts`/`.tsx` file under `scenes/`, and the selected local audio.
The descriptor also pins installed modules, Node, browser resources and ffprobe.
Matching hashes establishes identity; Root admission must separately establish
the right to execute those sources and their dependencies.

The project declares `scenes/index.ts` with a `sceneRegistry` mapping each
storyboard type to its actual React component. Components receive the admitted
scene, including its explicit `props`. Missing types fail rather than selecting
a fallback picture. Each scene uses its declared audio and visual padding;
its duration is the ceiling of their combined seconds at 30 FPS, and start
frames accumulate those integer durations. The selected dimensions are 720p,
1080p or 4K. Inputs are bounded to 64 scenes and 1800 seconds. Nonempty background
music, SFX and global style controls are explicitly unsupported in this route.

The entry probes each selected audio before bundling, requires its duration to
agree within one frame, and confines the bundle to admitted scene sources and
the frozen installed dependencies. It stages audio locally and refuses external
media downloads. The runner supervises the current Node/browser process custody.
Output requires fresh `output/final-RESOLUTION.mp4` and its current receipt.
Production outputs are bounded to 512 MiB; the fixed fixture retains 16 MiB.
The existing render and total deadlines remain 120 and 180 seconds.

`fast=True` selects CRF 28 and the veryfast preset; `fast=False` selects CRF 18
and medium. The receipt records requested/applied quality, exact inputs,
composition, audio observations and output bytes. Qualification requires the
exact admitted H.264 frame count and dimensions, AAC 48 kHz stereo, the receipt,
and complete decoding. Playback and visual/audio semantics remain separate.
This new source route has not yet passed its actual native product journey.
Its tests and packaged sources do not close the original nine-tool,
three-workflow renderer acceptance or the programme's release gates.
