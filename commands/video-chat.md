---
description: Multi-turn video Q&A session
argument-hint: <youtube-url-or-file-path>
allowed-tools: mcp__video-research__video_create_session, mcp__video-research__video_continue_session, Write, Read, Edit, Glob, Bash
---

# Video Chat: $ARGUMENTS

Start an interactive Q&A session with a video, progressively building knowledge.

## Session Setup

1. Determine the input type from "$ARGUMENTS":
   - If it starts with `http://` or `https://`: use `video_create_session` with `url` parameter
   - Otherwise (file path): use `video_create_session` with `file_path` parameter

2. **For YouTube URLs**: check `<memory-dir>/gr/media/videos/<video_id>.mp4` first.
   - If present: call `video_create_session(file_path="<that local path>")` for fastest local reuse.
   - If missing: ask user whether to download via `video_create_session(download=true)` or stream directly.
   - For local files, call `video_create_session(file_path=...)` directly.

3. Use description="Interactive Q&A session" for the session creation
4. Present the video title and session info. If `download_status` is present, explain:
   - `"downloaded"` + `cache_status="cached"`: "Video downloaded and cached — each turn will be fast and cost-efficient."
   - `"downloaded"` + `cache_status="uncached"`: "Video downloaded but cache creation failed — still faster than streaming (no re-fetch per turn)."
   - `"unavailable"`: "yt-dlp not found. Install it with `brew install yt-dlp` for cached sessions. Continuing with streaming."
   - `"failed"`: "Download failed. Continuing with streaming."

## Initialize Memory

1. Determine the memory directory: find the `.claude/` project memory path for the current working directory. Use `Glob` on `~/.claude/projects/*/memory/` to find the active project memory path if needed.
2. Generate a slug from the video title: lowercase, hyphens, no special chars, max 50 chars
3. Check if a prior analysis exists at `<memory-dir>/gr/video/<slug>/analysis.md`
   - If yes: read it, note existing concepts and knowledge states. The chat builds on prior analysis.
   - If no: this chat creates a fresh knowledge entry.

4. Use `Write` to create `<memory-dir>/gr/video-chat/<slug>/analysis.md`:

```markdown
---
source: <youtube-url-or-file-path>
analyzed: <ISO 8601 timestamp>
updated: <ISO 8601 timestamp>
session_id: <session_id>
concepts: []
---

# <Video Title> — Chat Session

> Source: <url-or-path>
> Session started: <YYYY-MM-DD HH:MM>

## Q&A
```

5. Tell the user: **Session notes auto-saving to `gr/video-chat/<slug>/`**
6. Invite the user to ask questions about the video.

## Frame Extraction Support

When a local video file is available (direct local input or downloaded YouTube copy), the agent can extract frames at specific timestamps.

When a question or answer references a specific visual moment (screen share, diagram, demo), the agent should:

1. Note the timestamp from the `video_continue_session` response
2. Extract the frame using ffmpeg:
   ```
   Bash: ffmpeg -y -ss 00:MM:SS -i <video-path> -frames:v 1 -q:v 2 <memory-dir>/gr/media/screenshots/<content_id>/frame_MMSS.png
   ```
3. Embed in the Q&A entry: `![description](../../media/screenshots/<content_id>/frame_MMSS.png)`

Create the shared screenshot directory on first extraction:
```
Bash: mkdir -p <memory-dir>/gr/media/screenshots/<content_id>
```

**When to extract frames:**
- User asks "what was on screen at...?" — extract that moment
- Answer describes a visual element (diagram, slide, demo) — extract it
- User asks for a summary with visuals — extract key moments (5-10 frames)
- After session end — extract frames for the most important moments discussed

If ffmpeg is not installed, skip gracefully and note timestamps as text.

## Conversation Loop

For each follow-up question:

1. Use `video_continue_session` with the session_id and the user's prompt
2. Present the answer conversationally, citing timestamps when available
3. **Extract frames** if the answer references visual moments (local files only, see above)
4. **Append to analysis.md** using `Edit` — add a timestamped Q&A entry (include frame embeds if extracted):

```markdown

### Q: <user's question>  <!-- <YYYY-MM-DD HH:MM> -->

<Summarized answer with key timestamps>
```

5. **Track new concepts**: If the answer introduces new concepts not already in the YAML frontmatter:
   - Add them to the `concepts` array with `state: unknown`
   - Update the `updated` timestamp

6. After every 3-5 Q&A exchanges, briefly note if new concepts have accumulated that would enrich a visualization update. Don't generate the viz mid-conversation — just track.

## Session End

When the user is done (says "done", "thanks", changes topic, or explicitly ends):

### 1. Concept Extraction

Review all Q&A entries and extract:
- All concepts discussed (with timestamps where available)
- Relationships between concepts discovered during Q&A
- Any concepts the user seemed unclear on (mark as `fuzzy`) vs. ones they grasped (mark as `know`)

Update the YAML frontmatter with the complete concepts list and knowledge states.

### 2. Append Relationship Map

Add a summary section to analysis.md:

```markdown
## Session Summary  <!-- <YYYY-MM-DD HH:MM> -->

### Concepts Explored
- **<Concept 1>** — <brief description from Q&A context>
- **<Concept 2>** — <brief description>

### Relationships Discovered
- <Concept 1> → *clarified by* → <Concept 2>

### Knowledge Gaps
- <Concept X> — user seemed unsure about this (state: fuzzy)
```

### 3. Background Visualization (optional)

Ask the user with `AskUserQuestion`:
- Question: "Generate interactive concept map from this session? (runs in background)"
- Option 1: "Yes (Recommended)" — description: "HTML visualization + screenshot + workspace copy, runs asynchronously"
- Option 2: "Skip" — description: "Finish now with session notes only"

**If yes**: Spawn the `visualizer` agent in the background with this prompt:
```
analysis_path: <memory-dir>/gr/video-chat/<slug>/analysis.md
template_name: video-concept-map
slug: <slug>
content_type: video-chat
```

**Do NOT wait** for the visualizer. Continue to confirmation immediately.

**If skip**: No visualization generated.

### 4. Confirm

Tell the user: **Session complete — saved to `gr/video-chat/<slug>/`**
- `analysis.md` — timestamped Q&A with concept tracking
- If visualization was requested: concept map + screenshot generating in background — you'll be notified when done

Suggest: browse past sessions with `/gr:recall video-chat`

## Cross-Referencing

If a prior `/gr:video` analysis exists for the same video (check `<memory-dir>/gr/video/<slug>/`):
- Note this in the session summary: "See also: full video analysis at `gr/video/<slug>/`"
- Consider concepts from the prior analysis when building the concept map — merge, don't duplicate
