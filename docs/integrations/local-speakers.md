# Local speaker records and explicit enrollment

`audio_speakers` supports anonymous diarization, recording-scoped relabels,
bounded cluster samples and read-only registry listings. `audio_speaker_enroll`
is the only operation that persists a voiceprint. This is an independently
authored adapter for the workflows mapped from
`sblattj/whosaid@f7e100d1f04b108b322378b6c43534e27a19eab2`; it bundles no upstream
implementation, model weights or native runtime.

The optional CPU runtime lives outside the plugin. Supply an absolute path and
SHA-256 for a `speaker-runtime/v1` descriptor. It names the interpreter,
site-packages, exact sherpa-onnx version, CPU thread count, segmentation model
and embedding model. Each model needs an absolute path, byte size, SHA-256 and
license statement; the embedding model also needs its actual dimension. The
adapter rechecks both model files before use. Core discovery needs none of those
optional packages. Installation and native qualification are separate checks.

Start with `dry_run=true`. A diarize request additionally supplies the exact
source path/hash, a selection of at most 120 seconds and a new output directory.
Execution exports a retained 16 kHz mono input, invokes one isolated worker and
writes `diarization.json`, optional RTTM and a receipt with output hashes. Turns
use source sample offsets. Anonymous cluster labels and cluster-similarity
scalars do not identify a person or express an identity probability.

Relabel and samples consume a record path plus its SHA-256. Relabel writes a new
record and optional RTTM from explicit assignments; roles only apply to names
assigned in that request. Registry matching requires a separate explicit request
and returns suggestions. Samples retain source/sample provenance and support at
most three clips per cluster, each between one and fifteen seconds. Existing
output directories and parent records are never overwritten.

Enrollment requires an explicit name, `consent_confirmed=true`, a registry path,
the runtime descriptor and either a source window or a bound diarized cluster.
The caller supplies the consent statement; the adapter does not establish it.
Entries are keyed by name and embedding-model SHA-256. Replacing an existing
entry requires `replace_existing=true`. Registry listings omit embeddings and
group entries by model. Ordinary diarize, relabel and sample operations do not
persist voiceprints. A dry run does not write a registry entry.

Source tests cover the schemas, SHA joins, sample boundaries, parent preservation,
model separation, consent refusal and atomic output behavior with mocked native
boundaries. Those tests do not establish acoustic speaker accuracy, consent,
model suitability or installed native operation. Programme acceptance must use
the original speaker criteria and retain failed or unrun cases.
