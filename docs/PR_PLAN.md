# PR & Distribution Plan

Last updated: 2026-03-05 20:09 CET

Generated 2026-03-05. v0.3.3 release.

## Directory listings

| Platform | Status | Link |
|----------|--------|------|
| awesome-mcp-servers | PR open | https://github.com/punkpeye/awesome-mcp-servers/pull/2772 |
| mcp.so | Live | https://mcp.so/server/video-research-mcp |
| glama.ai | Live + Claimed | https://glama.ai/mcp/servers/@Galbaz1/video-research-mcp |
| smithery.ai | Skipped | Requires remote HTTP endpoint (we run stdio) |

## Registries

| Registry | Version | Link |
|----------|---------|------|
| PyPI | 0.3.3 | https://pypi.org/project/video-research-mcp/0.3.3/ |
| npm | 0.3.3 | https://www.npmjs.com/package/video-research-mcp |
| GitHub | v0.3.3 | https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.3.3 |

## GitHub topics

Added: `model-context-protocol`, `weaviate`, `youtube`, `deep-research`, `claude`
(Already had: `ai-tools`, `claude-code`, `gemini`, `mcp`, `mcp-server`, `research`, `video-analysis`)

---

## Posts

### Reddit r/ClaudeAI

**Title:** I built a Claude Code plugin that lets Claude watch videos, research topics, create explainer videos, and recall everything weeks later

I've been building agents and training models since before anyone called it "vibe coding." The first version of this plugin was a weekend project. Make of that what you will.

It started because I wanted Claude to watch a video. Not read a transcript. Actually see what's on screen and answer questions about it. So I built an MCP server that hands video off to Gemini 3.1 Pro, which can process video natively, and pipes the results back to Claude. You point it at a YouTube URL or a local meeting recording, ask a question, and Gemini answers based on what it sees in the frames. The server caches the video context, so follow-up questions don't re-upload anything. You can have a back-and-forth conversation about a two-hour recording and it stays cheap and fast.

That part worked, so I kept going. The plugin now has 45 tools across two MCP servers, plus 16 slash commands, 6 skills, and 6 sub-agents that ship with it.

The research tools do web search with evidence grading. Every finding gets labeled: Confirmed, Strong Indicator, Inference, or Speculation. You can also point it at a folder of PDFs and get cross-referenced findings with page-level citations, every claim traced back to where it came from. Google's Deep Research Agent is in there too, for longer research jobs that run in the background.

It also creates videos. There are 17 tools for going from research to a rendered explainer video. Scriptwriting, scene generation (parallelized across agents using the Claude Agent SDK), text-to-speech via ElevenLabs or OpenAI, and final rendering through Remotion. It wraps the video_explainer library.

But the thing I actually care about most is the Weaviate integration. Every analysis, every research finding, every video breakdown gets stored automatically in one of 12 collections. I work on several research projects at the same time. Weeks later I type `/gr:recall "kubernetes"` and it finds relevant results even if the original analysis never used that word, because the search is semantic. The work I did in January is still there in March when a related question comes up. If you use AI tools for research or learning, you know the problem: everything disappears when you close the session. This fixes that. Your work accumulates.

```
npx video-research-mcp@latest
```

One command installs everything. You need a Gemini API key (free tier works for testing).

GitHub: https://github.com/Galbaz1/video-research-mcp

Questions welcome.

---

### Hacker News Show HN

**Title:** Show HN: Video-Research-MCP -- 45 tools for video analysis, research, and video creation

I've been building agents and training models since before anyone called it "vibe coding." The first version of this plugin was a weekend project.

It's a Claude Code plugin, though the MCP servers work with any client. Two servers: one for video analysis and research (28 tools), one for creating explainer videos (17 tools). There are also 16 slash commands, 6 skills, and 6 sub-agents that get installed alongside. Everything runs on Gemini 3.1 Pro.

The original problem was simple. I wanted Claude to watch a video and answer questions about what's in it. Not a transcript. The actual visual content. Gemini can do this natively, so the server hands the video to Gemini and brings the results back to Claude. When you analyze a video, the server keeps a cached context handle. Follow-up questions reuse it instead of re-uploading. This makes multi-turn Q&A over long recordings practical. For local files, ffmpeg extracts frames at visual transitions. I use it mostly for meeting recordings: `/gr:video-chat ~/recordings/call.mp4`, then ask for minutes in Dutch with screenshots of every shared screen.

The research tools run web search with evidence grading. Each finding is labeled Confirmed, Strong Indicator, Inference, or Speculation. There's also document research: give it a folder of PDFs and it cross-references findings with page-level citations. Google's Deep Research Agent, via the Interactions API, handles longer jobs that run in the background and return grounded reports.

It also creates videos. 17 tools cover the pipeline from research to rendered explainer video: scriptwriting, parallel scene generation using the Claude Agent SDK, TTS with word-level timestamps (ElevenLabs, OpenAI, or edge), and Remotion for final rendering. It wraps the video_explainer library.

The part that matters most to me in practice is the Weaviate knowledge store. Every tool result gets written to one of 12 collections. I run several research projects at once. Weeks later I can search across all of them with semantic matching. `/gr:recall "gradient descent"` returns results from an analysis that used the phrase "ML optimization." The work accumulates across projects and sessions instead of disappearing. If you do any kind of research with AI tools, you know the problem. This fixes it.

Caveats: alpha software. Gemini hallucinates on video timestamps sometimes. Weaviate adds operational complexity you might not want yet. The Deep Research API is a Google preview. And 45 tools is a lot for MCP clients with small context windows.

Install: `npx video-research-mcp@latest`
Or standalone: `uvx video-research-mcp`

724 tests, all mocked. Python, MIT license.

https://github.com/Galbaz1/video-research-mcp

---

### X/Twitter Thread (6 tweets)

**1.**
I wanted Claude to watch a video. Not read a transcript. See what's on screen.

So I built a plugin that connects it to Gemini 3.1 Pro. 45 tools, two MCP servers, 16 slash commands.

npx video-research-mcp@latest

**2.**
Point it at a YouTube URL or a local meeting recording. Gemini sees the frames and answers questions about them.

The server caches video context so follow-ups don't re-upload. You can interrogate a two-hour recording and it stays fast and cheap.

**3.**
The research tools grade every finding: Confirmed, Strong Indicator, Inference, or Speculation.

Give it a folder of PDFs and it cross-references with page-level citations. Google's Deep Research Agent handles longer jobs in the background.

Built for @AnthropicAI Claude Code. #MCP

**4.**
It also creates explainer videos.

17 tools. Scriptwriting, parallel scene generation via the Claude Agent SDK, TTS, Remotion rendering. Research in, video out.

**5.**
The thing I care about most: Weaviate stores everything automatically. Every video analysis, every research finding, across 12 collections.

I work on multiple projects. Weeks later I search across all of them. The work from January is still there in March. Your research stops being disposable.

**6.**
I've been building agents and training models since before anyone called it "vibe coding." The first version of this was a weekend project.

724 tests. MIT license.

https://github.com/Galbaz1/video-research-mcp

---

## Next steps

- [ ] Post Reddit r/ClaudeAI
- [ ] Post Reddit r/MCP (same post, slightly shorter)
- [ ] Submit Hacker News Show HN
- [ ] Post X/Twitter thread
- [ ] Monitor awesome-mcp-servers PR for review feedback
- [ ] Check glama.ai listing once review completes
