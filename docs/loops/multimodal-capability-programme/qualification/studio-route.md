# Mac Studio route for local model qualification

Fausto's recorded host instruction requires every local ASR, vision, embedding
and generation model to execute on the Mac Studio. The client may use the private
route or a qualified bounded loopback forward. Gemini cloud functionality remains
available under its own authority and qualification requirements.

On 2026-10-03 the coordinator performed a read-only SSH inventory with strict host
checking, an 8-second connection limit and a 25-second command limit. The configured
`mac-studio` alias reached `lab` on **Mac Studio van HVA**, running macOS 15.7.3,
with 256 GiB physical memory and 1,074,163,132 KiB available on the data volume.
Ollama reported version 0.34.2. One subsequent bounded inventory GET through SSH
returned these installed models:

| Model tag | Full inventory digest | Stored bytes |
| --- | --- | ---: |
| `qwen3.8-flash-next:125b-mlx` | `c7b96ffe21afe8c3dbb87d814b86bb5e89e622122f8613fb7acf4268a5bb85fa` | 104852026135 |
| `qwen3.8:27b-mlx` | `5642e97495e1a088883805981563dcdc4a040c2f53388b7a41d1f24d3622cf7e` | 18174721847 |

This proves SSH connectivity and the reported inventory. It does not establish
free runtime memory, idle runners, model licence eligibility, audio/vision/embedding
support, timestamped ASR, word alignment, task quality or an application connection.
Neither listed tag supplies an admitted timed-ASR route in this programme. Other
Studio installations and caches were not inventoried. No model was loaded, invoked,
downloaded, removed or reconfigured.

The ASR proposal in [audio-freecad.md](audio-freecad.md) therefore requires an exact
Studio runtime/checkpoint and permitted source/weight bytes, rights-cleared speech
references, the required word/time contract, server resource and deadline bounds,
and a private transport tested from the actual client. Its original A19/A20 cases
remain UNRUN. The same host rule applies to later OCR, vision, embedding and
generation proposals in [resources.md](resources.md). Client-side media decoding
and non-model native utilities remain subject to their existing contracts.

Private command, exit and inventory receipts are
`open-task-execution-2026-10-03/resources/mac-studio-readonly.json` and
`resources/mac-studio-model-tags.json` under the programme evidence directory.
They record zero inference and no installation or configuration changes. Refresh
live resources and exact model/runtime eligibility before any admitted execution.
