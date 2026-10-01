---
name: hardware-evidence-capture
description: Inspect controlled simulated hardware and retain explicit command and observation provenance.
---

# Hardware evidence capture

Use `mhs_discover` and `mhs_meta_info` to inspect the named device and current
capabilities, directions and limits. All currently supported devices are
simulated. Preserve that label in every result; never infer physical state,
calibration, safety or camera coverage.

Read sensors or images with `mhs_read` and retain the returned original artifact
path, byte count, SHA256, command/state identity, method and units. Generated
simulator images are synthetic data and cannot become factual original evidence.
Do not upload or publish observations without separate authority.

For a write, provide one explicit command ID and exact parameters. Hard limits
cannot be overridden. `confirm=true` cannot approve a soft override or a
confirmation-required operation. Return the full approval proposal for an
operator's review; only the separately configured host file can authorize it.
Do not write that file on the operator's behalf without an explicit instruction.
An awaiting proposal has not attempted its action. A terminal command ID replays
its receipt and never re-executes.

After a failed write, inspect `mhs_health_check` before any new write. Inspect
the executed command, effective limits and resulting state in its receipt.
Emergency stop latches the simulator off. Soft recovery needs its own exact host
approval. Neither outcome proves physical stop or recovery effectiveness.

Physical adapters are unavailable pending named owner qualification. Stop on
missing authority or an unknown result; preserve the error and receipt rather
than inventing a device observation or automatically retrying.
