"""Source-linked movie commentary projects with frozen execution shards.

Independent reimplementation of the movie-commentary contract in
QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f
(src/capabilities/omni-chatcut, Apache-2.0; no upstream code is imported or copied).
Changes: every artifact is bound to the source SHA256 and ffprobe receipt, shard sets
are content-addressed by the plan/facts/evidence digests, host execution needs an
explicit per-shard approval, and delivery re-verifies all bytes. No agent is spawned.
"""
