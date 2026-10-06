# Offline local audio mixing

`explainer_audio_mix` combines pinned local WAV narration, music and sound effects in an existing project. Cue intervals join a pinned storyboard. Source and rights records must match their recorded byte identities; commercial requests require explicit commercial status. FFmpeg uses local WAV inputs only. No music model or provider is invoked.

The output is a stereo PCM WAV and a receipt containing source and rights identities, the exact filter recipe, independent levels and fades, cache identity and measured duration/peak/clipping/edge levels. Music uses a level-dependent sidechain compressor; its requested setting does not guarantee a fixed measured attenuation. Repeated requests revalidate metadata, source bytes and output QA before reusing the output.

The 64 MiB output bound applies before the WAV read loop to declared PCM extent and during cumulative reads. A held regular-file stream prevents FIFO substitution; actual PCM frames must match the header. Cleanup failures preserve the original failure or cancellation and remove only known owned published output.

R369/R383/R387/R390/R393 original failures remain retained. R397 repairs the remaining size defect: one causal failing test precedes 88 passing affected tests. R400 independently accepted this causal delta at source level. Actual offline mixing, level/ducking/click tolerances and listening acceptance remain unqualified until their installed journey is run.
