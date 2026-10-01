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

Own MIT test excerpts from experiment `000434257e09dfd4eef93546442de2d6c597a53d`
retain the original function bodies. Changes remove MCP decorators and add isolated
mock fixtures; no experimental implementation replaces the production route.
The root MIT License and Copyright (c) 2026 Fausto Albers apply. Exact source-file
and excerpt hashes appear in the reuse ledger.

Dependencies are resolved as separate packages from the three exact `uv.lock`
files. Their grants remain applicable to those packages; this project's MIT
license does not replace them. Commercial service, generated-output, recording,
model and media rights are separate from a Python/npm package's code license.

The optional `images` extra imports **Pillow 12.3.0**, licensed MIT-CMU, as a
separately installed dependency. Its exact registry artifact hashes are recorded
in the reuse ledger. Pillow's installed `dist-info/licenses/LICENSE` includes
the PIL/Pillow grant and the wheel's codec/library notices; those terms continue
to apply. No Pillow code, codec binary or font file is copied into this project's
archives. Image annotations use the font provided by that installed dependency.
The embedded Aileron Regular subset has an exact installed-byte receipt in the
ledger. Its [publisher](https://dotcolon.net/fonts/aileron/) declares “No Rights
Reserved” and permits use, modification and redistribution. This font remains
inside the separately installed Pillow package; no font bytes enter our archives.

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

## Configured vision workflow requirements (vrm-0e8.3.4)

The independently authored vision chat/comparison, OCR inference and strict
normalized-box-to-original-pixel crop workflow was informed by
QwenLM/Qwen-MM-Plugins at07736672525443c7f8a3f6405eed37d2236f023f
(Apache-2.0 original API/shared requirements) and alexlivre/omni-image-tools-mcp
at4d191573b7e459519c3ec9414ade744456115a5a (MIT image vision/compare/extract
requirements). Applicable grant bodies and copyright notices are retained above.
Change attribution: implementation uses own strict typed geometry, original/prepared
byte commitments, configured origins, explicit submission and no automatic retries,
fallbacks or answer cache; no source bodies were copied. The optional pinned
Qwen API is a separately receipted private process using its declared older MCP
and Pillow majors. Its dependencies, binaries, fonts, media and model weights
are absent from this core distribution. Private mocked process discovery does
not establish provider support, accuracy, charging, deletion or full optional
extra readiness. See integrations/qwen/api.json and docs/integrations/IMAGE_VISION.md.

## Local scene asset requirements (vrm-0e8.3.5)

The independently authored hard-cut partition, timestamped storyboard,
horizontal grayscale dHash, bounded audio MFCC similarity and extraction routes
were informed by QwenLM/Qwen-MM-Plugins at
07736672525443c7f8a3f6405eed37d2236f023f, under the original Apache-2.0 grant
retained above. Change attribution: source snapshots, actual presentation clocks,
bounded processes, complete candidate denominators, immutable export paths and
manifest readback use this project's own implementations. No foreign helper body,
font, model weight, media or executable is copied. Local FFmpeg remains external.

Audio MFCC uses NumPy 2.4.6 through the optional audio/dev extras. Its primary
BSD-3-Clause grant is pinned at
b832a09cf2a169c833dd2371e7c07aa00b293242; exact upstream LICENSE.txt matches
the sdist and the prefix of the selected wheel's complete appended license.
Selected macOS arm64 CPython 3.14 wheel SHA256:
d581b735e177fdcdce6fed8e7e8880a3fb6ee4e3653a3ac6af01c6f4c03effc5.
Source sdist SHA256:
f3a3570c4a2a16746ac2c31a7c7c7b0c186b95ce902e33db6f28094ed7387dda.
The exact artifact grants and embedded notices remain intact in the external
NumPy package; all 20 wheel and 32 source named license/notice files are separately
retained and dispositioned in the dependency clearance receipt.

The inspected wheel has 19 arm64 extensions and two static libraries, with only
system Accelerate, libSystem and libc++ dynamic links. It contains no OpenBLAS,
libgfortran, libgcc or libquadmath binaries. Its generic conditional native
notice templates remain intact; they are not assertions that these runtimes are
present. Other-platform native redistribution and source-build execution remain
uncleared by this selected-host receipt. NumPy and system binaries are not bundled
in this project's wheel. Registry provenance subjects match the artifact hashes;
cryptographic Sigstore verification was not performed.

## Tutorial PDF runtime (vrm-0e8.7.1)

The optional `tutorial` extra uses **fpdf2**, covered by **LGPL-3.0-only**,
through an ordinary import of a separately installed, unmodified library.
Full [GPL3](licenses/fpdf2/GPL-3.0.txt) and
[LGPL3](licenses/fpdf2/LGPL-3.0.txt) copies accompany this application.
Users may replace this dependency with an interface-compatible modified version,
modify its library portions, and reverse engineer the combined application to
debug those modifications. Our MIT terms do not restrict those permissions.
No fpdf2 library body is vendored, frozen or statically linked into our archives.
Library redistribution or modification must meet its own source and notice terms.

Its required fonttools and defusedxml dependencies retain their packaged MIT
(including external BSD3/Apache/MIT/OFL notices) and PSF2 grants. The selected
generic wheels contain no font binaries or native libraries; fpdf2 includes one
ICC profile under its adjacent permissive International Color Consortium grant.
The core Helvetica/WinAnsi route does not select custom fonts or PDF/A.
Ordinary authored PDF output and supplied content have separate rights.

The separately installed **pypdfium2** wrapper retains its Apache2/BSD3 notices
and the native PDFium build's bundled dependency notices. The source-only grant
receipt covers the selected macOS13+arm64 build; full native source/build closure
and other platform artifacts are not qualified by that receipt. No wrapper code,
native binary, ICC profile or font bytes are bundled in our distribution.

Tutorial requirements were inspected at QwenLM/Qwen-MM-Plugins
`07736672525443c7f8a3f6405eed37d2236f023f` (original Apache2 code).
The source plan, immutable illustration lineage, staged PDF validation and atomic
publication are independently authored. No Qwen code, font, model or demo is
copied or imported. ReportLab whole-wheel use remains withheld because seventeen
font permissions were unresolved; the font-free writer preserves the workflow.

## Optional Blender session integration

The owned startup/process adapter implements a local session policy around the
unmodified Qwen Blender tools/addon at revision
07736672525443c7f8a3f6405eed37d2236f023f. These external MIT-derived portions
retain Siddharth Ahuja (2025) attribution; Qwen project additions retain Apache-2.0
terms. Exact external source selection requires its full LICENSE, Blender NOTICE
and vendor/LICENSE. No external tool/addon code, Blender executable, provider
asset or model is redistributed by this descriptor and adapter.

Applicable upstream MIT grant:

MIT License

Copyright (c) 2025 Siddharth Ahuja

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
