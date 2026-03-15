# Security Fix Playbook

## FP-001: Enforce URL Policy at Tool Ingress
- Context: Any tool accepting user URLs and triggering outbound fetch behavior.
- Rule: Validate URL with `validate_url()` before model/tool fetch.
- Why: Prevents non-HTTPS, credentialed URLs, and private-network SSRF targets from crossing trust boundary.
- Applied in iteration 1:
  - [`src/video_research_mcp/tools/content.py`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/src/video_research_mcp/tools/content.py)
- Regression coverage:
  - [`tests/test_content_tools.py`](/Users/fausto/.codex/worktrees/ec3f/gemini-research-mcp/tests/test_content_tools.py)

## FP-002: Architectural Control Surface Review (queued)
- Context: Runtime-mutating tools (`infra_cache`, `infra_configure`) are callable without explicit auth gating.
- Candidate mitigation: Introduce optional capability gate via config/environment and reject mutating actions when disabled.
- Status: queued for design and compatibility analysis.

## FP-003: Validate Redirect Hops Explicitly
- Context: Any safe downloader that follows user-controlled redirects.
- Rule: Disable automatic redirects; validate each hop URL and peer IP before continuing.
- Why: Initial/final validation is insufficient when intermediate hops can cross trust boundaries.
- Applied in iteration 2:
  - [`src/video_research_mcp/url_policy.py`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/url_policy.py)
- Regression coverage:
  - [`tests/test_url_policy.py`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/tests/test_url_policy.py)

## FP-004: Strict List-String Input Contracts
- Context: Tool params transmitted through JSON-RPC where list values may arrive malformed.
- Rule: Coerce then strictly validate `list[str]` at ingress; reject non-list and empty-string elements.
- Why: Prevents character-iteration fallbacks and resource fanout from malformed payloads.
- Applied in iteration 2:
  - [`src/video_research_mcp/types.py`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/types.py)
  - [`src/video_research_mcp/tools/research_document.py`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/research_document.py)
  - [`src/video_research_mcp/tools/research.py`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/research.py)
  - [`src/video_research_mcp/tools/content_batch.py`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/content_batch.py)
  - [`src/video_research_mcp/tools/knowledge/search.py`](/Users/fausto/.codex/worktrees/9f62/gemini-research-mcp/src/video_research_mcp/tools/knowledge/search.py)
