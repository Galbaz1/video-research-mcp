#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
mkdir -p .codex

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user uv
  export PATH="$HOME/.local/bin:$PATH"
fi

# Persist non-secret defaults for the agent phase. Codex setup runs in a
# separate shell, so exports alone do not survive into later task shells.
python3 - <<'PY'
from pathlib import Path

bashrc = Path.home() / ".bashrc"
start = "# >>> video-research-mcp codex defaults >>>"
end = "# <<< video-research-mcp codex defaults <<<"
block = f"""{start}
export GEMINI_SESSION_DB="${{GEMINI_SESSION_DB:-/workspace/video-research-mcp/.codex/gemini_sessions.db}}"
export GEMINI_MODEL="${{GEMINI_MODEL:-gemini-3.1-pro-preview}}"
export GEMINI_FLASH_MODEL="${{GEMINI_FLASH_MODEL:-gemini-3-flash-preview}}"
export DEEP_RESEARCH_AGENT="${{DEEP_RESEARCH_AGENT:-deep-research-pro-preview-12-2025}}"
export GEMINI_THINKING_LEVEL="${{GEMINI_THINKING_LEVEL:-high}}"
export GEMINI_TEMPERATURE="${{GEMINI_TEMPERATURE:-1.0}}"
export FLASH_SUMMARIZE="${{FLASH_SUMMARIZE:-true}}"
{end}
"""

text = bashrc.read_text() if bashrc.exists() else ""
if start in text and end in text:
    prefix = text.split(start, 1)[0].rstrip()
    suffix = text.split(end, 1)[1].lstrip()
    pieces = [part for part in (prefix, block, suffix) if part]
    bashrc.write_text("\n\n".join(pieces) + "\n")
else:
    prefix = text.rstrip()
    pieces = [part for part in (prefix, block) if part]
    bashrc.write_text("\n\n".join(pieces) + "\n")
PY

uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
