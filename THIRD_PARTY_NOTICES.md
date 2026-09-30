# Third-party notices

The project software is licensed under the root [MIT license](LICENSE), copyright
(c) 2026 Fausto Albers. Programme code changes are independently authored unless
an exact transferred-file receipt says otherwise.

The multimodal programme currently vendors **no external programme source code,
fonts, stock media, model weights or foreign executables**. Audited projects are
requirements/source references, not redistributed libraries. The component grants,
source revisions, selected routes, blocked operations and locked Python dependency
receipts are recorded in `docs/integrations/reuse-ledger.json`. A planned route is
not an imported-file receipt.

Dependencies are resolved as separate packages from the three exact `uv.lock`
files. Their grants remain applicable to those packages; this project's MIT
license does not replace them. Commercial service, generated-output, recording,
model and media rights are separate from a Python/npm package's code license.

## A distribution omission with verified source terms

The optional dependency **weaviate-agents 1.8.0** omits license metadata and a
license file in its PyPI wheel. The tagged upstream source `v1.8.0`, commit
`35ac1ebc11dd71b7df38a76cfe8d0a2782f30524`, supplies the following BSD-3-Clause
grant. All 28 `weaviate_agents/*.py` files in that wheel match the pinned source.
The wheel and source hashes and matched paths are in the reuse ledger. Its cloud
agent service terms and usage authority still require separate verification.

Source: <https://github.com/weaviate/weaviate-agents-python-client/blob/35ac1ebc11dd71b7df38a76cfe8d0a2782f30524/LICENSE>

BSD 3-Clause License

Copyright (c) 2025, Weaviate

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Rights that are not cleared by repository metadata

- **Qwen-MM-Plugins**: original code has Apache-2.0 terms. Blender and FreeCAD
  vendored/derived portions have their own MIT copyrights, permission grants and
  notices. Font grants vary by directory. Verified OFL fonts require the exact
  font-file receipt, copyright, full OFL grant and reserved-name terms when
  redistributed. Smiley Sans metadata declares an unknown license. No Qwen fonts,
  sound effects or other assets are bundled here.
- **GPT Researcher**: the pinned root grant is Apache-2.0; its MIT package metadata
  does not establish MIT eligibility. No GPT Researcher code is copied here.
  Any future adaptation must retain its source notices, a full Apache grant and
  prominent modified-file notices before distribution.
- **video_explainer and mcptube**: their pinned trees have no LICENSE, COPYING or
  NOTICE grant despite permissive declarations. Their source copying, imports,
  automatic installation and redistribution remain blocked. Own implementations
  and separately permitted external backends retain the useful capabilities.
- **VideoRAG/ImageBind and MusicGen**: the integrated VideoRAG algorithm restricts
  use to noncommercial research; AudioCraft model weights use CC-BY-NC-4.0. These
  code/weight routes are blocked for commercial integration and are not bundled.
  Own indexing, separately cleared embeddings and rights-cleared local audio or
  permitted provider services are the operational alternatives.
- **Optional runtimes and assets**: parser/OCR, ASR/diarization, CAD/Blender/FEM,
  hardware, Rust DSP, GPU/embedding models, JS renderers, stock media and cloud
  services require separate version/platform/hash, dependency, grant, asset,
  model and service receipts. The root code license supplies none of those rights.

A new copied/adapted file must add its exact source/target hashes, component grant,
copyright, full license text and change notice to the ledger and this notice file
before it enters a built archive. An external asset must add its own receipt.
