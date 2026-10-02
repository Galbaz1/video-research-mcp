# Controlled hardware simulation

The six `mhs_*` tools provide independently authored lamp and camera simulations.
Set `MHS_MODE=simulator` in the host environment to enable them. The default is
`disabled`. Device values, health gates and command receipts persist in private
SQLite storage under `GEMINI_CACHE_DIR/hardware`. No hardware, adapter server,
Qwen process, provider or network endpoint is contacted.

`mhs_discover` lists the two registered device IDs, types and tags.
`mhs_meta_info` returns fresh capabilities, directions, values and effective
limits. `mhs_health_check` returns current simulated health and acknowledges
the separate health gate after a failed write. `mhs_read` reads declared sensors
or exports owned simulated image bytes. `mhs_write` applies validated atomic
changes. `mhs_reset` latches an emergency stop or requests soft recovery.
Every observation identifies its simulated origin; physical calibration,
coverage and stop effectiveness remain unknown.

Writes and resets require an explicit `command_id`. A terminal command ID
returns its recorded outcome on repetition without executing again. Reusing it
for a different intent is rejected. A command awaiting host authority has not
attempted its action; an explicit same-ID call can resume that proposal after
approval only while its state and effective limits still match. No automatic
retry occurs. New writes after a failed known-device write require fresh health
evidence. That audit gate does not change the device's values.

Hard limits, unknown parameters, wrong directions, invalid types and nonfinite
numbers are rejected before value mutation. Soft-limit overrides and
confirmation-required writes need separate host approval. The model's
`confirm=true` is only caller acknowledgement and grants no authority.
Emergency stop latches output off and blocks writes and image capture. Soft
recovery requires separate approval and restores safe defaults.
The store retains at most 512 command receipts and reserves one stop receipt
per online device. Ordinary admission can therefore stop before 512; recovery
is refused if it would consume the room needed for that device's next stop.

For an approval-required proposal, inspect its full command, state commitment
and effective limits. The host operator may add that exact returned commitment
to a separately configured private file:

```json
{"approved_commands": ["<exact returned 64-character commitment>"]}
```

Set `MHS_AUTHORITY_FILE` to this operator-owned regular file, with permissions
`0600`. The file admits at most 64 commitments and is read without following a
symlink. It is neither a public tool parameter nor writable through these
tools. The command binds its ID, exact intent, device revision and effective
limits; a stale proposal cannot authorize changed state. The executed command
receipt prevents approval replay. This boundary assumes the operator controls
the process environment and approval file; it is not a multiuser authentication
system. The runtime configuration response omits the approval-file path.

The example at `integrations/qwen/mhs.json` documents host configuration; it is
not automatically loaded and does not register a physical adapter. Physical
transport is unavailable in this implementation. A future physical deployment
must qualify named owner-approved adapters, exact operation authority, transport
and media boundaries, effective limits, acknowledgement/recovery, and hardware
enforcement. A simulated result supplies none of that proof.

Qwen MHS contracts and their Apache-2.0 grant were inspected at pinned revision
`07736672525443c7f8a3f6405eed37d2236f023f`. No upstream code, runtime, driver,
camera bytes or model assets are copied, imported or bundled. The implementation
uses first-party requirements and standard-library simulation; future adapter
and hardware licenses remain separate.
