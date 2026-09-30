# Qwen onboarding reuse boundary

This leaf independently implements optional onboarding, diagnostics and recovery.
It uses the audited release/configuration discipline of
[Qwen-MM-Plugins at the exact source revision](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f)
and the audited provider-CLI requirements of
[vidlens-mcp](https://github.com/thatsrajan/vidlens-mcp/tree/edd1d9fba8cf2364343b4cbd07378a649f956f08).
No upstream code, assets or runtime is copied or imported.

The [manifest](../../integrations/qwen/manifest.json) accounts for every transferred
file with empty `copied_paths` and `imported_packages`, records the own target
files and carries notice receipts from the existing
[reuse ledger](reuse-ledger.json). The exact
[release index](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/plugin-versions.json)
contains fourteen capability versions. Each manifest entry names its declared tag;
that metadata does not prove a tagged release's commit or byte identity. No
foreign process, tagged release tree or dependency lock is adopted here.

Qwen original code uses Apache-2.0; its Blender/FreeCAD derived portions carry
separate MIT grants and copyright notices. Any later copied implementation must
retain the exact applicable copyright/license/change attribution. ChatCut and
selected video-edit fonts have separate OFL or MIT notices; their exact font-file
hashes and reserved-name terms must be cleared before redistribution. Smiley Sans
metadata has an unresolved license. Root Apache labeling supplies no blanket
asset, weight, executable or provider-service grant.

This distribution bundles no fonts, SFX, stock media, weights or optional foreign
binaries. System fonts are external references; original synthetic development
media provides an available fixture route. Smiley Sans, unattributed media,
unreceipted checkpoints and the grantless renderer remain absent. A future managed
binary manifest must identify version, platform, SHA256, source and executable
license notices and verify those fields before use. The current managed-binary
list is empty; PATH presence is only an offline prerequisite observation.

Foreign integrations stay in separately selected environments/processes and add
nothing to the locked core Python environment. Activation requires a complete
runtime/dependency/asset receipt and operation-specific authority. Read-only doctor
never installs, repairs, downloads a model, infers, records, controls a device or
publishes. Local processing and cloud payload submission are recorded separately;
an installed local plugin cannot establish local inference.
