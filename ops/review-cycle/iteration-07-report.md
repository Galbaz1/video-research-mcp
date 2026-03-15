# Iteration 07 Security Review Report

Date: 2026-03-01T16:03:02Z  
Focus: Prompt injection and tool misuse resistance

## Scope Detection Snapshots
- Before branch transition:
  - `{"mode":"none","reason":"No local changes and no ahead commits to review.","branch":"HEAD","base_branch":"main","uncommitted_files":0,"ahead_commits":0,"pr_context":false,"pr_url":null}`
- After creating `codex/review/i07` from `codex/review-mainline`:
  - `{"mode":"commits","reason":"Branch is ahead of base with no local unstaged/uncommitted files.","branch":"codex/review/i07","base_branch":"main","uncommitted_files":0,"ahead_commits":12,"pr_context":false,"pr_url":null}`

## EARS Run Requirements (Concise)
1. When iteration state is `7`, the run shall review prompt-injection/tool-misuse surfaces.
2. If iteration 6 lessons require explicit integrity boundaries, iteration 7 shall apply that rule to untrusted prompt payloads.
3. When untrusted query/result text is inserted into prompts, the system shall delimit it and instruct the model to ignore embedded instructions.
4. If injection-like strings are present, regression tests shall verify hardened prompt constraints are included.
5. The run shall persist findings, fixes, lessons, and confidence deltas into review-cycle artifacts.

## Findings By Severity
### Medium
- ID: I07-F1
- Area: Prompt injection in knowledge summarization
- Evidence:
  - Prior `_build_prompt` interpolated raw query/properties into free-form prompt text without untrusted markers.
  - Hardened implementation now at [`src/video_research_mcp/tools/knowledge/summarize.py:22`](/Users/fausto/.codex/worktrees/174b/gemini-research-mcp/src/video_research_mcp/tools/knowledge/summarize.py:22).
- Exploit reasoning: Retrieved content can include instruction-smuggling strings ("ignore prior rules", "call tool X"), which may bias summarization outputs and degrade trustworthiness of downstream retrieval context.
- Fix status: Implemented + tested in this iteration.

### Medium (Patch-ready, not implemented)
- ID: I07-F2
- Area: Second-pass content reshaping prompt boundary
- Evidence:
  - Untrusted text is interpolated directly in second-pass prompt reshaping at [`src/video_research_mcp/tools/content.py:208`](/Users/fausto/.codex/worktrees/174b/gemini-research-mcp/src/video_research_mcp/tools/content.py:208) and [`src/video_research_mcp/tools/content.py:216`](/Users/fausto/.codex/worktrees/174b/gemini-research-mcp/src/video_research_mcp/tools/content.py:216).
- Exploit reasoning: Adversarial instructions embedded in fetched content can influence the schema-reshaping model call and reduce extraction reliability.
- Fix status: Logged in risk register for iteration 8 follow-up.

## Implemented Changes
- Hardened prompt contract in `knowledge` Flash summarizer:
  - Added explicit security rules.
  - Wrapped query and hit payloads in `<UNTRUSTED_QUERY>` / `<UNTRUSTED_HIT>` delimiters.
  - Serialized payloads via JSON for deterministic formatting.
- Added adversarial regression test:
  - [`tests/test_knowledge_summarize.py`](/Users/fausto/.codex/worktrees/174b/gemini-research-mcp/tests/test_knowledge_summarize.py)
  - `test_prompt_hardens_untrusted_query_and_properties`

## Validation
- `uv run ruff check src/video_research_mcp/tools/knowledge/summarize.py tests/test_knowledge_summarize.py`
- `PYTHONPATH=src uv run pytest tests/test_knowledge_summarize.py -q`
- Result: pass (`8 passed`)

## Reflective Self-Learning Loop
- Observe: Prompt inputs in summarization path were untrusted but not explicitly delimited.
- Infer root cause: Earlier hardening focused on URL/path/infra boundaries, leaving prompt-boundary contracts implicit.
- Propose strategy: Reuse iteration 6 "explicit integrity contract" pattern for model prompt boundaries.
- Validate: Added hardened prompt plus adversarial test proving required constraints are present.
- Confidence delta: 0.58 -> 0.81 (technical) and 0.81 -> 0.86 (delivery after tests).

## Lessons Learned
- Prompt construction should treat retrieved/query text as untrusted input, just like URL/file ingress.
- Explicit boundary signaling (metadata/delimiters/rules) is reusable across data integrity and prompt integrity domains.

## Next-Iteration Hypotheses (Iteration 8)
1. Add bounded concurrency controls in high fan-out async paths (download/upload/batch analyze) to reduce resource exhaustion risk.
2. Extend prompt-boundary hardening to second-pass reshaping in content analysis (`_reshape_to_schema`).
