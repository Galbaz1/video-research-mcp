# Local extractive synthesis

`synthesis_manage` supports `cross_video`, `chapters`, and `bug_report`. It reuses the canonical corpus or wiki selector. Caller fixture records are labelled `caller_fixture`; they cannot claim canonical origin. The tool does not invoke a provider, modify the corpus, or generate factual prose.

Each request supplies `instruction`, `source`, and an action. A corpus source wraps the existing corpus query request with its index path, collection, source revisions and retrieval bounds. A wiki source wraps context-only wiki retrieval. The instruction becomes the actual retrieval question. Up to 50 selected records and a caller-selected output bound are permitted.

Cross-video results quote retrieved observations and preserve video, revision, media digest, citation and interval. Conflicting quotations remain separately attributed. No matching evidence yields abstention. Quotations and keyword relevance do not establish truth or semantic completeness.

Chapters additionally require video ID, source revision and caller-declared duration. Ordered equal-duration bins retain exact observation intervals and label their method as a heuristic. The tool does not probe media duration or invent aligned word times.

Bug reports additionally require a selected time. Reported OCR, frame references, preceding speech and explicitly selected action observation IDs occupy separate channels. Inferred context and caller-supplied causes remain separate and unverified. Missing channels are explicit; frame references are not decoded by this tool.

R362 passed 18 source checks. Independent review R375 found two faults: stored metadata could differ from the admitted identity, and an opposing quotation could be dropped when it used a pronoun. R378 preserved five failing regressions, repaired both faults, and passed 192 affected checks. R379 independently reviewed the repair with no material findings. The root server mounts the tool. R417 completed the installed DEV metadata journey; R422 independently verified the original citation, conflict, chapter and bug-channel clauses. The synthesis Bead is accepted for this extractive metadata behavior. The authored transcript and frame references do not establish real-media extraction, semantic quality, grounding, human evaluation or release acceptance.
