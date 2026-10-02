# Published baseline and boundary protection

The frozen [baseline](public-baseline.json) names the actual published source and
locked environments. [Tool contracts](public-baseline-tool-contracts.json) protect
existing input validation/defaults, output schemas and MCP annotations across all
three servers. Additive optional inputs and new tools remain possible. Installed
client files and registry releases are separate identities.

Run `uv run python scripts/check_public_baseline.py` before accepting extensions.
The command verifies the frozen source/lock receipts, current tool compatibility
and the original checkout's protected files. Required final commands stay frozen
in the baseline manifest; this check does not substitute for executing them.

## Current boundaries

URL adapters retain HTTPS, credential rejection, public DNS and redirect checks,
post-connect private-peer checks and streamed document byte limits. Local adapters
resolve paths at the fence and reject URI input, parent traversal and symlink
escapes. New adapters must invoke these boundaries before reading or requesting
user-supplied resources.

Local video intake enforces `MEDIA_MAX_INPUT_BYTES` (default 512 MiB, positive)
before hashing, inline allocation or File API upload. YouTube intake accepts only
an eleven-character ID, ignores external yt-dlp configuration, and every format
branch requires known dimensions at most 1280 × 720. It passes the byte ceiling to
yt-dlp and checks cached/downloaded bytes before use. Oversized input fails with a
bounded-window instruction. These limits establish intake bounds, not decoded
media correctness or proof of observed coverage.

The published baseline has no root native image decoding or cropping operation.
The implementation adds `image_ops.inspect_png` and `crop_png`: header CRC, byte,
8-million input pixel, 4-million output pixel and integer crop-bound checks run
before decoding. The optional installed FFmpeg is restricted to one PNG frame,
one thread, 64 MiB per decoder allocation, the same input pixel cap and 30 seconds.
A bounded private source snapshot binds the header and decoder bytes. Only a
checked, fresh crop is atomically promoted, with source/output digests and
coordinates. A rights-owned four-pixel result is decoded and pixel-checked in the
local integration test; no provider call or runtime installation is involved.

These library operations are not yet MCP registrations. The native-media leaf
must carry their limits into its actual image blocks/frame operations and add
negative tests for other supported codecs. Existing companion render presets are
typed and bounded; arbitrary generated scene behavior requires its later
production acceptance.

The legacy analysis cache has no trusted artifact receipt or artifact scope.
It therefore declines artifact-bearing results and treats historical entries with
proof paths, errors, malformed types or empty analysis as misses. Strict artifacts
must be nonempty regular files within their staging directory; failed checks
expose no promoted paths. HTML syntax, factual source support, timestamp accuracy,
decoding and human review remain separate dimensions.

Root and companion error/diagnostic boundaries remove known credential values,
authorization/cookie fields and URL userinfo/query/fragment values. Root config
exports omit secret fields and redact endpoint credentials while preserving the
resource host/path and nonsecret operational settings. Companion subprocess logs
and SDK errors are redacted before returning diagnostic text.
