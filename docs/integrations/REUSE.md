# Reuse and optional runtime clearance

`vrm-0e8.2.6` provides the executable reuse gate for the multimodal programme.
The authority is the pinned [85-unit inventory](../research/2026-09-30-capability-transfer.json)
and [loop contract](../loops/multimodal-capability-programme/LOOP.md).
[reuse-ledger.json](reuse-ledger.json) records every source unit's component,
revision, exact audited paths and permitted operational route. Its source grants
were fetched from pinned upstream URLs on September 30, 2026; hashes identify the
observed bytes. The two missing grants were confirmed against complete recursive
Git trees. This gate does not repeat the landscape audit or certify a feature as
implemented.

No external programme source, executable, font, media or weight is adopted in
this leaf. Each unit remains `not-adopted` until its implementation records exact
transfers or package imports. `independent-implementation` means own code written
for the mapped requirements; `independent-adapter` means own code to a separately
permitted optional backend; `own-source` reconciles the existing MIT source refs.
These routes preserve functionality even when direct copying is blocked. A future
choice to copy a permitted component is explicit, with file receipts and notices;
a top-level repository grant alone never clears its assets or vendored files.

## Run the gate

```bash
uv run python scripts/check_reuse_ledger.py
uv run pytest tests/test_reuse_ledger.py -q
uv build --out-dir /tmp/vrm-reuse-build
npm pack --pack-destination /tmp/vrm-reuse-build --ignore-scripts
uv run python scripts/check_reuse_ledger.py --archive /tmp/vrm-reuse-build/video_research_mcp-0.7.1-py3-none-any.whl --archive /tmp/vrm-reuse-build/video_research_mcp-0.7.1.tar.gz --archive /tmp/vrm-reuse-build/video-research-mcp-0.7.1.tgz
```

The archive check reads actual tar/wheel bytes without extracting or executing
members. It rejects absolute/traversal paths, links, duplicate members, unreceipted
binary/media/font/model assets and missing or stale notices/ledger. An approved
asset requires a matching archive path/content hash, commercial redistribution
eligibility and a grant reproduced in the notices. A forged extension does not
turn binary content into cleared source. Companion archives must carry their own
MIT license and pass the same asset checks; root Python/npm archives also carry
the programme notices and ledger.

## Receipt required before adoption

A transferred file records its source path and SHA-256, target path and SHA-256,
component license, whether commercial redistribution is permitted, full grant text,
copyright and modification notice. The matching notice text must be present in
`THIRD_PARTY_NOTICES.md`. A package import records package name/version and the
specific lock receipt; code grants, models, assets and service terms remain
separate. Keep optional runtimes outside the core environment and disabled until
their executable/version/platform/hash, complete dependency lock, grants/notices,
weights/assets and service/output terms have their own receipt. Credentials and
weights stay external. Readiness never supplies spend, device or publication
authority.

The current three Python locks contain 114 distinct registry name/version pairs.
Their exact lock hashes, package identities and registry artifact hashes are
recorded. PyPI license expressions/classifiers are observed metadata, not a full
transitive source/asset audit. The optional `weaviate-agents` wheel's absent license
metadata is resolved with the exact tagged BSD-3-Clause source grant: all 28
package Python files match, and the grant is retained in the distributed notices.
No optional foreign runtime is selected by this ledger.

## Explicit dispositions

| Component | Blocked operation | Permitted operational alternative |
| --- | --- | --- |
| Pinned renderer without a grant | Source copy/import, automatic install, bundle | Own FFmpeg rendering and own adapters to a separately permitted backend |
| mcptube without a grant | Source copy/import, automatic install, bundle | Own SQLite/FTS wiki/index and existing knowledge store |
| VideoRAG integrated ImageBind | Commercial integrated code/weights and bundle | Own indexing and separately cleared text/visual embeddings |
| MusicGen weights | Commercial weight use, automatic download, bundle | Rights-cleared local music/SFX or permitted configured provider |
| Qwen Smiley Sans/unattributed assets | Font/media copy and bundle | System fonts or independently receipted OFL/owned assets |
| Qwen Blender/FreeCAD | Blanket root Apache clearance | Per-file vendor MIT grants/copyrights/notices, or own adapter |
| GPT Researcher metadata conflict | MIT attribution from package metadata | Root Apache-2.0 grant and change notices, or own implementation |
| Foreign/transitive runtimes | Implicit core install/download/unreceipted bundle | Own core path or isolated, fully receipted optional process/service |
| Community Qwen wrapper | Copy/import/default Modal endpoint | Own mapped Qwen/API implementations |

The ledger stores these dispositions and alternatives even when a related feature
is implemented later. Update the receipt after a real dependency or adoption
change; never edit the check to accept a previously failing unlicensed asset.

## Accepted independent requirements implementations

The frozen evaluation protocol and stronger root security boundaries now have
exact independently authored file-hash receipts for `adj_research_eval`,
`adj_video_eval`, `direct.security`, `own.strict-evidence-semantics` and
`adj_evidence_packet`, `qwen_reuse_manifest` and `direct.providers`.
The source/claim/production packet, controller-supplied
coverage and native/text crop extension now have exact own-source file receipts.
Offline doctor, atomic install/checkpoint/restore and the disabled Qwen capability
manifest also have exact implementation receipts. No managed binary or external
capability runtime is bundled or activated.
Their pinned external sources remain
design/evidence references. No upstream implementation, model weight, source
asset or optional runtime was copied or imported. Held-out fixture rights and
provider/model terms stay separate from source-code reuse clearance.

A later edit to a receipted implementation must refresh its target hash before
source/archive clearance. The ledger cannot treat an implementation plan as an
adoption receipt.
