# Isolated pinned Qwen API

The programme source is QwenLM/Qwen-MM-Plugins at
`07736672525443c7f8a3f6405eed37d2236f023f`. Its unmodified console entry is
`qwen-mm-plugins-api`, resolving `qwen_mm_plugins_api.__main__:main` over stdio.
The actual pinned source process initialized and advertised all13 API operations,
including `vision_chat`, `ocr` and `grounding`. Four public calls passed against
the real OpenAI SDK with a mocked transport: one zero-completion dry run, then
chat, OCR and grounding. All33 loaded upstream bodies and2,157 installed RECORD
files were read back. The exact private runtime receipt is bound in the manifest.
The original pre-initialize harness failure and its one controlled correction are
retained; a blocked ancillary process attempt had unknown argv and executed
nothing. No live provider, upload or OS-wide network result is claimed.

The API distribution declares MCP v1 and Pillow<12; the core environment uses
MCP v2 and Pillow12. It must remain a separately selected runtime. Core tools
`vision_chat`, `vision_ocr` and `vision_grounding` independently implement the
[bounded vision workflow](IMAGE_VISION.md); no compatibility shim or foreign
source/dependency is installed into core.

The [API manifest](../../integrations/qwen/api.json) records the selected source,
entry point and evidence boundary. The optional foreign process stays disabled
for ordinary onboarding. Manual local discovery uses a private compatible
runtime, exact source/lock/grant receipts and isolated configuration; provider
calls require separately bounded account, source-upload and spending authority.
Readiness cannot activate the process or download a model.

The pinned upstream accepts explicit endpoints/credentials and implements lazy
uploads, permissive box parsing and retries. It supplies no dry run on its OCR
and grounding tools. A live external call therefore requires an external
operation-specific guard; its successful discovery/mocked requests do not
establish equivalent core budget, strict geometry or privacy controls. Local
installation does not establish local inference, model quality or weight rights.
Temporary upload expiry does not prove deletion. No foreign assets or weights
are bundled with this integration descriptor.

For a manually selected external source checkout and compatible environment, the
entry point is executable without installing the entire upstream distribution:

```bash
PYTHONPATH="/selected/qwen/src:/selected/qwen/src/capabilities/api" \
  /selected/qwen-runtime/bin/python -m qwen_mm_plugins_api
```

Select the exact source revision above and verify the API/shared bytes and root
Apache grant. The development runtime recipe uses CPython3.12 with MCP1.30.0,
Pillow11.3.0, OpenAI1.109.1, AnyIO4.15.1, Pydantic2.13.5 and
docstring-parser0.18.0 plus the36-package selected transitive cohort. This is a
manual selection, not an upstream author lock; reproduce installed bytes and
all grant bodies before use. DashScope/OSS/SOCKS call-time extras were absent
from the selected mocked VL verification. Advertising their schemas does not
establish that those operations can execute. The private test environment is
kept out of the core package and installer.
