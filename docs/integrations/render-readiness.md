# Renderer readiness and MP4 qualification

The companion supports a separately configured external CLI and optional
[authored renderer entries](authored-renderer.md). This guide covers the external
CLI route. The companion ships first-party entry source, but no installed
Remotion modules, browser, fonts, foreign source or provider credentials.
The selected source contract is prajwal-y/video_explainer at
`c033e28d6eccae43c1762f4653f9c320b16b050e`. Its README/metadata state MIT but
the selected tree has no license grant file; copying/importing remains blocked.
Remotion has separate eligibility and distribution terms. Doctor certifies neither.

`explainer_doctor(project_id=None)` diagnoses the selected route locally. With
`EXPLAINER_RENDERER_ENTRY` unset, it checks actual
Node version (20 or newer), FFmpeg/ffprobe version commands, console executable,
ordinary Node installation of Remotion/renderer/bundler 4.0.242, platform-specific
cached headless-shell, and five exact mapped source bodies. It reports Claude
presence separately for generation and provider credentials only as presence.
Provider access, browser launch, renderer execution and audio provenance are
unverified. It executes no foreign CLI, provider request, download or installation.
PnP/system-Chrome installations are unsupported by this selected route.

With an authored entry selected, doctor checks its frozen source, runtime and
project descriptor instead. Those entries pin Remotion 4.0.532 independently of
the external CLI's 4.0.242 contract. Readiness does not establish a completed render.

For an optional project, doctor rejects mismatched storyboard paths before render
admission. The public CLI checks `paths.storyboard`, while its Node entry reads
`storyboard/storyboard.json`; both must select that canonical file. Public rendering
uses `render PROJECT -r RESOLUTION` and optional `--fast`, preceded by global
`--projects-dir`. It supports no wrapper-invented `--mock`, `--output` or `--timeout`
render flags. Wrapper timeouts supervise the owned process rather than CLI arguments.

The existing durable job freezes source, settings, adapter and console bytes.
Console and dispatch settings are checked after asynchronous readiness, immediately
before launch, after dispatch, and after output qualification. Replacement during
diagnostics cannot launch; replacement during rendering cannot complete the job.
Rendering rechecks mapped source, requires unchanged project inputs and a changed
expected output: 720p/4k select `output/final-{resolution}.mp4`; 1080p selects the
configured direct `paths.final_video` MP4 under `output/`. Another recent output cannot win by
timestamp. Full legacy generation prepares through storyboard and calls this exact
render route, avoiding upstream whole-pipeline mock fallback/old-output skipping.

Qualification copies the admitted bytes privately under a 512 MiB ceiling, checks
H264 and exact requested dimensions with bounded ffprobe, then decodes all video
frames and audio packets with FFmpeg. Duration must be finite, positive and at most
four hours. Limits are 10 seconds probe, 60 seconds decode, and 1 MiB per process
output stream. Owned process groups and drains join on timeout/cancellation.
Original media and codec executable hashes are read back before completion.

The existing result commitment retains policy, output SHA256/size, media metadata,
decode coverage, executable bodies and limits. Read-only poll verifies this receipt
and current bytes; legacy completed results without it become `unknown` without
launching codecs or replaying the renderer. `artifact_verified` measures byte
integrity; `playability_verified` measures the retained complete decode proof.
`real_renderer_verified` stays false, and content/visual/audio semantics are unknown.

The recorded external-CLI evaluation lacked configured modules and a browser.
Its deterministic FFmpeg and mocked controller controls establish local codec
and admission behavior. They do not complete the configured renderer journey or
verify source claims. Consult the selected runtime's qualification before using
that route; authored-fixture results do not qualify the external CLI.
