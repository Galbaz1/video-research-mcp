# Source-linked movie commentary with frozen execution shards

The package `video_explainer_mcp.commentary` and the server `tools/commentary.py` (`commentary_server`,
seven tools) manage one durable commentary project per fixed source movie. They reuse the explainer's
existing helpers:

- `render_artifacts.file_revision` for bounded hashing;
- `render_validation.codec_executables` for pinned ffprobe/ffmpeg with their byte identities;
- `media_process.run_media_process` for bounded, owned subprocesses;
- `evidence.atomic_write` and `narration_pcm.atomic_bytes`;
- `make_tool_error`.

They add no dependency, pipeline framework or agent spawning.

## Provenance and licence

This is an independent reimplementation of the movie-commentary contract in
`QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f`, located at
`src/capabilities/omni-chatcut/qwen_mm_plugins_omni_chatcut/movie_commentary/`, together with its skill and
executor agent. That repository is under Apache-2.0, and no upstream code is copied or imported.

The design changes are:

- every artifact is bound to the source SHA256 and a pinned ffprobe receipt;
- shard sets are content-addressed by the plan, script, facts and evidence digests;
- host execution needs an explicit, immutable approval for each shard;
- delivery re-hashes every input and output.

## Tools

| Tool | Effect |
|---|---|
| `commentary_prepare` | Creates `<projects>/.movie-commentary/<project_id>` after the source bytes match `expected_source_sha256` (see below). |
| `commentary_inspect` | Read-only state, source freshness and recommended stage. |
| `commentary_validate_plan` | Reports every plan error in one pass; writes nothing. |
| `commentary_freeze_shards` | Validates first, then writes write-once `shards/<set_id>/shard_NN.json` and `index.json`. |
| `commentary_approve_shard` | Records a write-once approval and returns the exact execution scope; executes nothing. |
| `commentary_assemble` | ffmpeg concat (stream copy), full decode with `-xerror`, ffprobe duration, then write-once `full/qa.json`. |
| `commentary_validate_delivery` | Re-verifies everything and refuses delivery on any missing or changed byte. |

`commentary_prepare` also runs one pinned ffprobe and records its argv, the executable's identity and the
output digest. It writes write-once `project.json` and `plan/execution_facts.json`. `source_cut_max_sec`
defaults to the probed duration; when the caller supplies it, it is recorded as caller-asserted.

Source probing accepts direct MOV/MP4 (including 3GP/MJ2), Matroska/WebM, AVI, MPEG-PS/TS,
Ogg, ASF and FLV containers, with the `file` input protocol only. Indirect inputs such as
HLS, DASH, SDP and concat playlists are refused even when renamed as movie files.
Assembly retains absolute shard paths (`-safe 0`) and stream-copy concat, but each shard
is restricted to the MOV/MP4 demuxer and `file` protocol. Final decode and probing also
force MOV/MP4. These command restrictions do not establish native media qualification.

## Contracts

**Plan** (`vrm/movie-commentary-plan/v1`):

- It is bound to the project `source_sha256`.
- Segment IDs run `SEG_0001` onward, with at most 2000 segments.
- `narration.text` must appear verbatim, together with its segment ID, in `plan/narration_script.md`.
- `rough_interval_sec` must be ordered and at most `source_cut_max_sec`.
- Each segment has 1–16 evidence refs. They must be regular files under `plan/watch_notes/`; absolute paths, `..`
  traversal and symlinks are refused.
- `source_audio_mode` is `ducked_bed` or `muted`. `bgm_mode` is `none`, or `licensed` only with a BGM manifest.

**Shard set:**

- `set_id` is the first 16 hex characters of the SHA256 over the plan, script, facts and evidence digests.
- Consecutive segments are copied unchanged into the shards, each bound to the source and facts digests.
- Freezing again with identical inputs is idempotent. Changing `segments_per_shard` for the same plan is refused.
- Changing the plan, facts or evidence produces a different set, so approvals and outputs for the old set no
  longer apply.

**Approval:** approver, shard SHA256, source SHA256, a caller media-authority statement and the scope
`render_frozen_shard_only`. It is recorded with `authority_basis=caller_asserted_not_verified` and
`rights_inferred=false`. It authenticates no principal, and nothing is executed by the tool.

**Execution report:** `vrm/movie-commentary-exec-report/v1`. It names the shard SHA256 and approval SHA256 and
has status `success`. It lists exactly the frozen segment IDs, each `resolved` with `understanding_mode`
`grounded` or `degraded_local_repin`. It also carries:

- `output_video`, equal to the current MP4 sha256/size;
- a finite `duration_sec`;
- `qa_checks`, all true;
- an empty `unresolved`.

**Final QA:** `vrm/movie-commentary-final-qa/v1`. It contains:

- the shard lineage (MP4 revision and duration per shard, in order);
- the final MP4 revision;
- the executables and commands;
- the decode stderr digest;
- the timing within `tolerance_sec` of the summed shard durations;
- `overall_pass`.

A failed concat, decode or probe removes the unqualified final MP4.

## Status

- Unit tests mock only the native ffprobe/ffmpeg boundary and use caller-authored dummy bytes, not media.
- All four acceptance criteria remain **native OPEN**: there has been no actual movie, decode, playback,
  render or host shard execution.
- `commentary_server` is mounted, and a private installed candidate exposes all 26 companion tools.
- The installer includes the commentary skill and support document; all 51 installer checks pass.
- Source review, canonical manifest/reuse-ledger updates and the installed public journey remain open.
