---
description: Analyze a video (YouTube URL, local file, or directory)
argument-hint: <youtube-url-or-file-path>
allowed-tools: mcp__video-research__video_analyze, mcp__video-research__video_batch_analyze, mcp__video-research__video_create_session, mcp__video-research__video_continue_session, mcp__video-research__video_metadata, mcp__video-research__video_playlist, Write, Glob, Read, Bash
---

# Video Analysis: $ARGUMENTS

Analyze the provided video source with progressive memory saving and automatic visualization.

## Phase 1: Analyze

1. Determine the input type from "$ARGUMENTS":
   - If it starts with `http://` or `https://`: use `video_analyze` with `url` parameter
   - If it's a directory path (ends with `/` or is a known directory): use `video_batch_analyze` with `directory` parameter
   - Otherwise (file path): use `video_analyze` with `file_path` parameter
2. For single video analysis, use this instruction (append the screenshot marker block for **local files only**):

   **Base instruction** (always):
   `instruction="Provide a comprehensive analysis including title, summary, key points, timestamps of important moments, main topics, and overall sentiment."`

   **Screenshot markers** (append when input is a local file, NOT a YouTube URL):
   ```
   Also place inline screenshot markers at visually important moments using this format:
   [SCREENSHOT:MM:SS:brief description of what is shown on screen]

   Rules:
   - Place 8-15 markers spread across the video
   - Capture: screen shares, diagrams, slides, demos, key visual moments
   - Skip: webcam-only talking heads, transitions, blank screens
   - Description should explain what is visible (e.g., "architecture diagram showing data flow")
   ```

3. For batch (directory) analysis, use instruction="Provide a comprehensive analysis of this video."

## Phase 1.5: Download to Memory (YouTube only)

If the source is a YouTube URL, persist a local copy for reuse.

1. Compute `video_id` from the URL and set target path: `<memory-dir>/gr/media/videos/<video_id>.mp4`
2. If the target file is missing, download with:
   ```bash
   yt-dlp --no-playlist -q -f "mp4[height<=720]/mp4/best[ext=mp4]" \
     -o "<memory-dir>/gr/media/videos/<video_id>.mp4" \
     "https://youtube.com/watch?v=<video_id>"
   ```
3. Update `<memory-dir>/gr/media/videos/.manifest.json` with title, source_url, size_mb, downloaded_at.
4. If download fails or `yt-dlp` is unavailable, continue analysis without local media.

## Phase 2: Present & Save Initial Results

1. Present the structured results clearly:
   - **Title and Overview**
   - **Key Points** (bulleted)
   - **Timestamps** (notable moments)
   - **Topics and Sentiment**

2. **Immediately save initial results** — don't wait until the end:
   a. Determine the memory directory: find the `.claude/` project memory path for the current working directory. Use `Glob` on `~/.claude/projects/*/memory/` to find the active project memory path if needed.
   b. Generate a slug from the video title: lowercase, hyphens, no special chars, max 50 chars (e.g., "Mastering Claude Code Skills" → `mastering-claude-code-skills`)
   c. Use `Write` to save at `<memory-dir>/gr/video/<slug>/analysis.md`:

```markdown
---
source: <youtube-url-or-file-path>
analyzed: <ISO 8601 timestamp>
updated: <ISO 8601 timestamp>
concepts: []
---

# <Video Title>

> Source: <url-or-path>
> First analyzed: <YYYY-MM-DD HH:MM>

## Summary  <!-- <YYYY-MM-DD HH:MM> -->

<Overview paragraph>

## Key Points  <!-- <YYYY-MM-DD HH:MM> -->

<Bulleted key points>

## Timestamps  <!-- <YYYY-MM-DD HH:MM> -->

| Time | Moment |
|------|--------|
| ... | ... |

## Topics  <!-- <YYYY-MM-DD HH:MM> -->

<Comma-separated topics>
```

   d. Retain screenshot markers in the saved analysis for Phase 2.5. Tell the user: **Saved initial analysis to `gr/video/<slug>/`**

   e. **YouTube URLs only**: Now spawn the `comment-analyst` agent in the background:
      ```
      video_url: <the YouTube URL>
      video_title: <extracted video title>
      analysis_path: <memory-dir>/gr/video/<slug>/analysis.md
      ```
      The comment-analyst runs alongside Phases 2.5-4 and returns `community-reaction.md`. The parent merges it after joining required workers and finishing its own edits. Skip for local files.

## Phase 2.5: Extract Video Frames

Extract shared screenshots into `gr/media/screenshots/<content_id>/` when a local video file is available.

1. Determine video source path:
   - Local input file: use that path directly.
   - YouTube input: use `<memory-dir>/gr/media/videos/<video_id>.mp4` if it exists.
   - If no local file exists, skip frame extraction gracefully.
2. Parse analysis results for `[SCREENSHOT:MM:SS:description]` markers.
3. For each marker, extract a frame using ffmpeg:

```
Bash: python3 -c "
import subprocess, os, re

video_path = '<absolute-path-to-video>'
frames_dir = '<memory-dir>/gr/media/screenshots/<content_id>'
os.makedirs(frames_dir, exist_ok=True)

analysis = open('<memory-dir>/gr/video/<slug>/analysis.md').read()
markers = re.findall(r'\[SCREENSHOT:([\d:]+):(.*?)\]', analysis)
extracted = 0

for ts, desc in markers:
    parts = ts.split(':')
    if len(parts) == 2:
        ffmpeg_ts = f'00:{parts[0].zfill(2)}:{parts[1]}'
    elif len(parts) == 3:
        ffmpeg_ts = f'{parts[0].zfill(2)}:{parts[1]}:{parts[2]}'
    else:
        continue
    safe_ts = ts.replace(':', '')
    out = os.path.join(frames_dir, f'frame_{safe_ts}.png')
    result = subprocess.run(['ffmpeg', '-y', '-ss', ffmpeg_ts, '-i', video_path, '-frames:v', '1', '-q:v', '2', out], capture_output=True)
    if result.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
        extracted += 1
        print(f'  {ts} — {desc}: {out}')
    else:
        print(f'  {ts} — extraction failed; retain the text marker')
print(f'Extracted {extracted}/{len(markers)} frames')
"
```

4. Write `<memory-dir>/gr/media/screenshots/<content_id>/manifest.json` with timestamp, description, and filename entries only for successfully extracted non-empty files. Retain failed markers as text.
5. Replace markers in `analysis.md` with embedded images:
   - `[SCREENSHOT:12:44:SAP scherm]` becomes:
   ```markdown
   ![SAP scherm](../../media/screenshots/<content_id>/frame_1244.png)
   *12:44 — SAP scherm*
   ```

6. If ffmpeg is not installed or extraction fails, keep markers as timestamped text references.

## Phase 3: Enrich with Relationships

1. Extract concepts, relationships, and categories from the analysis results:
   - Identify 8-20 key concepts from key_points, topics, and timestamps
   - Infer relationships between concepts (builds on, example of, enables, contradicts, related to)
   - Cluster concepts into 3-7 categories by topic
   - Assign initial knowledge states: all `unknown`

2. Append a Relationship Map section to `analysis.md` using `Write` (re-read and rewrite):

```markdown
## Relationship Map  <!-- <YYYY-MM-DD HH:MM> -->

### Concepts
- **<Concept 1>** (<category>) — <one-line description>. Timestamp: <time>
- **<Concept 2>** (<category>) — <one-line description>. Timestamp: <time>

### Relationships
- <Concept 1> → *enables* → <Concept 2>
- <Concept 3> → *example of* → <Concept 1>
```

3. Update the YAML frontmatter `concepts` array:

```yaml
concepts:
  - name: <Concept 1>
    state: unknown
    timestamp: "<time>"
  - name: <Concept 2>
    state: unknown
    timestamp: "<time>"
```

4. Update the `updated` timestamp in frontmatter.

## Phase 4: Background Visualization (optional)

Ask the user with `AskUserQuestion`:
- Question: "Generate interactive concept map visualization? (runs in background)"
- Option 1: "Yes (Recommended)" — description: "HTML visualization + screenshot + workspace copy, runs asynchronously"
- Option 2: "Skip" — description: "Finish now with analysis only"

**If yes**: Spawn the `visualizer` agent in the background with this prompt:
```
analysis_path: <memory-dir>/gr/video/<slug>/analysis.md
template_name: video-concept-map
slug: <slug>
content_type: video
```

**Do NOT wait** for the visualizer. Continue immediately to Deeper Exploration below. The user will be notified when visualization is done.

**If skip**: Confirm: **Analysis complete — saved to `gr/video/<slug>/`**
- `analysis.md` — timestamped analysis with relationship map

## Deeper Exploration

After presenting results, ask if the user wants to dive deeper:
- Commands/tools shown: `instruction="Extract every CLI command with flags and arguments"`
- Workflow/steps: `instruction="Extract the step-by-step workflow with timestamps"`
- Transcript: `instruction="Transcribe with timestamps for each speaker change"`
- Start a chat session: suggest `/gr:video-chat <same-url>`

For iterative Q&A, create a session with `video_create_session` and use `video_continue_session` for follow-ups. Any deeper analysis should be appended to the existing `analysis.md` with new timestamps.
