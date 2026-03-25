# Skill Audit — e1l.1

**Datum:** 2026-03-25 | **Epic:** `newton-v2-build-codex-e1l`

## Inventaris

### Global (`~/.claude/skills/`) — 13 skills, 3.648 regels

| # | Skill | Regels | Wat het doet | Deps |
|---|-------|--------|--------------|------|
| 1 | ffmpeg | 603 | Video/audio processing reference: format conversie, compressie, platform-optimalisatie, post-processing filterorde | FFmpeg CLI |
| 2 | ai-video-pipeline | 313 | End-to-end orchestrator: image-gen → provider selectie → ffmpeg → QA gates | Veo, Sora, mcp-image, FFmpeg |
| 3 | cinematic-iteration | 363 | Frame-by-frame QA: extract 10fps printscreens, inspecteer visueel, itereer | mcp-image, Veo, FFmpeg |
| 4 | chained-video-production | 263 | Anchor-first multi-shot: hero still → propagate → assemble. 4 patronen | mcp-image, Veo, Sora, FFmpeg |
| 5 | design-to-video | 378 | Stitch UI + photorealistisch → consistent montage. 6 fasen, 2 modi | Stitch MCP, mcp-image, Veo, Sora, FFmpeg |
| 6 | image-generation | 145 | mcp-image prompt optimalisatie: Subject-Context-Style, video style anchors | mcp-image (Gemini) |
| 7 | sora | 218 | OpenAI Sora Videos API wrapper: T2V, I2V, extend. Draft→finalize workflow | OPENAI_API_KEY, Python script |
| 8 | veo-video-generation | 158 | Google Veo 3.1/3.0/2.0 MCP reference: 4 tools, camera reliability tabel | Veo MCP server |
| 9 | remotion | 394 | Stitch screens → Remotion React video compositie met transities | Stitch MCP, Remotion CLI, Node.js |
| 10 | enhance-prompt | 205 | Vage UI ideeën → Stitch-geoptimaliseerde prompts via DESIGN.md | Stitch kennis |
| 11 | stitch-init | 171 | `.stitch/` directory + DESIGN.md + Tailwind v4 setup | Stitch MCP |
| 12 | hub-transcribe | 140 | Audio → transcript + NL vergaderrapport via Gemini 2.5 Pro | Gemini API |
| 13 | agents (ElevenLabs) | 297 | Voice AI agents bouwen: init → add → push. Twilio, widgets | ElevenLabs CLI/SDK |

### Newton project (`newton-v2-build-codex/.claude/skills/`) — 2 skills, 289 regels

| # | Skill | Regels | Wat het doet | Deps |
|---|-------|--------|--------------|------|
| 14 | elevenlabs-tts | 128 | TTS productie: API patterns (curl), voice settings, FFmpeg post-processing, ducking | ElevenLabs API, FFmpeg |
| 15 | newton-voice-over | 161 | Newton-specifiek: 4 VO blokken, timing, SFX sync, cosine-ease ducking, 7-element mix | ElevenLabs API, FFmpeg |

**PRODUCTION-LOG key learnings:** MCP geeft 404 (gebruik curl), `eleven_multilingual_v2` enige productiemodel, cosine-ease ducking ipv hard step, atempo >1.35 onnatuurlijk, 10fps frame extractie voor QA.

### Al in plugin (`skills/`) — 7 skills, 1.072 regels

| # | Skill | Regels | Status |
|---|-------|--------|--------|
| 16 | video-research | 353 | Blijft — 28 tools reference |
| 17 | weaviate-setup | 194 | Blijft — onboarding guide |
| 18 | mlflow-traces | 168 | Blijft — tracing reference |
| 19 | video-explainer | 139 | Blijft — explainer pipeline |
| 20 | gemini-visualize | 109 | Blijft — HTML visualisatie |
| 21 | research-brief-builder | 60 | Blijft — interview template |
| 22 | gr-advisor | 49 | Blijft — command routing |

**Totaal: 22 skills, 5.009 regels**

---

## Analyse: overlap en dedup

### Zware overlap (>50% gedeelde content)

| Cluster | Skills | Overlap |
|---------|--------|---------|
| **Video workflows** | ai-video-pipeline, cinematic-iteration, chained-video-production | Alle drie beschrijven style anchors, multi-take protocol, QA gates. ai-video-pipeline is de meta-orchestrator, andere twee zijn specifieke patronen |
| **Video providers** | sora, veo-video-generation | Beide T2V/I2V met provider-specifieke settings. Selectielogica zit verspreid over ai-video-pipeline en chained-video-production |
| **TTS/Voice** | elevenlabs-tts, newton-voice-over | newton-voice-over bevat Newton-specifieke timing maar ook generieke ducking/mixing patterns die in elevenlabs-tts ontbreken |
| **Stitch-family** | enhance-prompt, stitch-init, design-to-video, remotion | Allemaal Stitch-afhankelijk, maar design-to-video mixt ook met video productie |

### Geen overlap (uniek)

| Skill | Reden |
|-------|-------|
| ffmpeg | Standalone reference, wordt gerefereerd door 6+ andere skills |
| image-generation | Specifiek mcp-image prompt engineering |
| hub-transcribe | Audio→text, ander domein |
| agents (ElevenLabs) | Voice bots bouwen, niet media produceren |

---

## Consolidatieplan

### IN de plugin (5 nieuwe skills)

| Nieuwe skill | Bron(nen) | Geschatte regels | Maps naar Beads taak |
|-------------|-----------|-------------------|---------------------|
| **`tts-production`** | elevenlabs-tts + generieke delen newton-voice-over | ~200 | e1l.2 |
| **`video-generation`** | sora + veo-video-generation + provider-selectie uit ai-video-pipeline | ~250 | e1l.4 |
| **`video-production`** | ai-video-pipeline + cinematic-iteration + chained-video-production (dedup) | ~300 | e1l.4 |
| **`ffmpeg-production`** | ffmpeg (trim ~50%: drop Remotion-specifiek, drop obsolete codecs) | ~300 | e1l.3 |
| **`image-generation`** | image-generation (move as-is) | ~150 | e1l.4 |

**Totaal nieuw:** ~1.200 regels (was 2.581 verspreid → 53% reductie)

#### Detail per skill

**`tts-production`** — Voice-over productie met ElevenLabs
- API patterns (curl, niet MCP — MCP geeft 404)
- Model selectie: `eleven_multilingual_v2` voor productie
- Voice settings tuning (mild vs aggressive per context)
- FFmpeg post-processing: speed adjust, loudness normalize (EBU R128)
- Ducking patterns: cosine-ease transitions (0.5s ramps, 55% reductie)
- Multi-element mixing: adelay positioning, filter_complex
- Drop: Newton-specifieke timing, asset paths, blok-specifieke settings

**`video-generation`** — Provider-onafhankelijke video generatie
- Provider selectie matrix: wanneer Veo vs Sora
- Veo: 4 tools, camera reliability tabel, negative prompt block, duration defaults
- Sora: T2V, I2V, extend, draft→finalize, auto resize/crop
- Generatie defaults: resolution, duration, aspect ratio per use case
- Drop: dubbele provider-selectie uit ai-video-pipeline

**`video-production`** — Cinematic video productie workflows
- Style anchor systeem (uit ai-video-pipeline)
- 4 chaining patronen: Animate&Propagate, Frame-Forward, Parallel Variants, Extend (uit chained)
- Multi-take protocol met variant selectie (uit ai-video-pipeline)
- QA gates: technical + rationality + visual (uit ai-video-pipeline + cinematic)
- Frame extraction QA: 10fps printscreens, inspectie checklist (uit cinematic)
- Assembly: crossfade, timing, platform export
- Drop: overlappende style anchor beschrijvingen, dubbele QA secties

**`ffmpeg-production`** — FFmpeg voor media productie
- Post-processing filterorde: denoise → scale → sharpen → color grade → grain → encode
- Platform-specifiek: YouTube, TikTok, Instagram presets
- Audio: loudness normalization, ducking, mixing, delay positioning
- Format conversie: codec selectie, bitrate targets
- Drop: Remotion-specifieke sectie (zit in remotion skill), obsolete codec info

**`image-generation`** — Style anchors en prompt optimalisatie
- Subject-Context-Style structuur
- Video style anchor pipeline (quality: "quality", 4K, purpose)
- Character consistency via `inputImagePath` iteratie
- Composite anchors, text preservation
- Move as-is, minimale edits

### BLIJFT GLOBAL (niet in plugin)

| Skill | Reden |
|-------|-------|
| design-to-video | Stitch MCP dependency — plugin heeft geen Stitch. Eventueel later als Stitch support komt |
| enhance-prompt | Stitch-specifiek |
| stitch-init | Stitch-specifiek |
| remotion | Stitch→Remotion, Node.js dependency. Past niet in Python MCP monorepo |
| agents (ElevenLabs) | Voice bot builder, niet media productie. Ander domein |
| hub-transcribe | Audio transcriptie, niet productie. Werkt standalone |

### ARCHIVEER (na extractie)

| Skill | Reden |
|-------|-------|
| newton-voice-over | Newton-specifiek. Generieke patterns → `tts-production`. Rest is project-local |

---

## Implementatievolgorde (maps naar Beads taken)

```
e1l.2: tts-production
  └─ Schrijf skill, test triggering, update FILE_MAP

e1l.3: ffmpeg-production
  └─ Schrijf skill, trim content, test triggering, update FILE_MAP

e1l.4: video-generation + video-production + image-generation
  └─ Schrijf 3 skills, test triggering, update FILE_MAP
  └─ Zwaarste taak: meeste dedup werk in video-production

e1l.5: production-logging
  └─ Ontwerp logging pattern (geïnspireerd door Newton PRODUCTION-LOG)
  └─ Implementeer als plugin component (skill of command)
```

**Kritisch pad:** e1l.2 en e1l.3 zijn onafhankelijk en kunnen parallel. e1l.4 hangt af van image-generation (style anchors). e1l.5 is onafhankelijk.

---

## Architectuurbeslissing: één plugin (vastgesteld)

**Besluit:** Eén plugin, token-bewust ontworpen. Niet splitsen.

**Onderbouwing (deep research 2026-03-25):**

- Token budget: 140 skills over 25 plugins = 37.108 chars (186% van ~20.000 soft budget). 5 nieuwe skills voegen ~1.250 chars toe (+6%) — niet significant
- Precedent: GSD (38 commands + 15 agents) en claude-api (17 skills) werken als monoliet
- Splitsen kost: twee npm packages, geen dependency declaration, dubbele install, versie sync probleem, bridge agent toewijzing
- MCP tools zijn globaal toegankelijk — splitsen geeft geen isolatie voordeel
- Progressive disclosure (Level 1/2/3) maakt skillcount beheersbaar mits descriptions kort en bodies onder 2.000 woorden

**Token-optimalisatie regels voor nieuwe skills:**

1. Description max 200 chars, met negatieve qualifiers
2. SKILL.md body max 2.000 woorden — zware content in `references/`
3. Dedup mlflow-traces / mlflow-mcp-traces
4. Trim video-research SKILL.md: tool-per-tool details naar references/

---

## Beslispunten (open)

1. **design-to-video** — in plugin of global houden? Mixt Stitch met video productie. Als het in de plugin komt: Stitch MCP als optionele dependency
2. **hub-transcribe** — past bij "media production" maar draait standalone. Verplaatsen of laten?
3. **agents (ElevenLabs)** — voice bots ≠ media productie, maar ElevenLabs overlap met tts-production
4. **PRODUCTION-LOG (e1l.5)** — skill, command (`/gr:production-log`), of beide?
