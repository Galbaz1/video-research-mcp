# Correction lessons and replay history

`correction_manage` records reported corrections and evaluates supplied replay outcomes in an existing canonical workspace and collection. It supports `record`, `replay`, `list`, and `export`. Each write supplies the expected collection revision; retained case and replay identities cannot be rewritten through this interface.

A lesson preserves the original question, answer or failure, source revisions, exact observation snapshots, corrected answer and references, and reported authority. A replay supplies a new immutable ID, a change revision and an outcome. The fixed evaluator checks exact answer text and inclusion of the corrected references. Passing this rule does not verify factual truth. Reported authority remains unauthenticated, and all records retain `verified: false`.

Every admitted replay contributes to the denominator: pass, fail, error, provider error or abstention. Repeating an identical replay returns its existing record. Conflicting IDs, stale collection revisions and oversized writes refuse admission without claiming to have stored an attempt. Exports paginate retained history and include its denominator.

The canonical database retains up to 100 cases and 1,000 replays per collection, with 256 KiB payload and caller-selected response limits. Collection access and retirement follow the existing workspace boundary. No provider or model runs during recording or replay.

Recording a lesson commits its correction history, then invalidates matching entries in the existing result cache and local context-cache registry using the original and corrected source digests. A caller label does not select entries. The operation reports absent, complete, partial or failed invalidation, with counts and errors; repeating the same case reconciles invalidation without creating another lesson revision. Listing and replay report that invalidation was not checked for those operations. Local registry invalidation does not call a provider to delete remote caches.

R368 passed 12 source tests and Ruff, preserving its initial fixture failure. R384 independently reviewed the four source files and transaction boundary with no material findings. The root server mounts the tool. R401 adds bounded cache invalidation; R408 found an unrelated disk-reference overwrite, and R414 is the causal repair. R418 independently accepted R414 at source level; that checkpoint records a passing root suite. Positive installed cache-invalidation acceptance remains pending. The grounding prerequisite and final release remain open.
