---
name: gemini-visualize
description: Generates interactive HTML visualizations (concept maps, evidence networks, knowledge graphs) from Gemini analysis results. Use when the user requests a concept map, evidence network, or knowledge graph from completed analysis.
---

# Gemini Visualize — Interactive Analysis Visualization

Generate a single-file interactive HTML visualization when requested or when it materially clarifies the completed analysis, then verify it in an available browser. The agent decides enrichment depth autonomously but respects user steering ("skip visualization", "deeper on X").

## Template Selection

| Source Command | Template | Visualization Type |
|---|---|---|
| `/gr:video`, `/gr:video-chat` | `video-concept-map` | Concept map with knowledge states |
| `/gr:research` | `research-evidence-net` | Evidence network with tier filtering |
| `/gr:analyze` | `content-knowledge-graph` | Knowledge graph with entity types |

Read the appropriate template from `skills/gemini-visualize/templates/` before generating.

## Core HTML Requirements

Every generated visualization MUST be a **single self-contained HTML file** with:

1. **No external dependencies** — all CSS, JS, SVG/Canvas inline
2. **Dark theme** — background `#0a0a0f`, nodes/text in light colors, high-contrast edges
3. **Canvas or SVG rendering** — prefer `<canvas>` for large graphs, `<svg>` for smaller ones
4. **State object pattern** — all app state in a single `state = {...}` object at the top of `<script>`
5. **Responsive layout** — works in both full-page browser and embedded views
6. **Smooth animations** — transitions on hover, click, filter changes (200-300ms)

## Data Mapping (Agent Decisions)

The agent autonomously decides:

- **Concept hierarchy depth** — based on content richness (3-8 top-level nodes typical, 15-25 total with children)
- **Which concepts become nodes** vs. which are properties of nodes — major themes → nodes, supporting details → node metadata
- **Relationship types** — derived from context (e.g., "enables", "contradicts", "builds on", "example of")
- **Initial knowledge states** — default to `unknown` unless the user has indicated familiarity
- **Category assignment** — cluster nodes by topic/theme, assign colors per category

## Visualization Features (All Templates)

### Required
- **Drag-and-drop** nodes with physics-based layout (spring simulation or force-directed)
- **Zoom and pan** via mouse wheel and drag on background
- **Node click** — shows detail panel with description, source timestamp/citation, related nodes
- **Category legend** — clickable to filter nodes by category
- **Search/filter** — text input to highlight matching nodes
- **Responsive sidebar** — detail panel slides in from right, doesn't overlap graph on wide screens

### Template-Specific
- **Concept maps**: Knowledge state cycling (Know → Fuzzy → Unknown → Know) on node click
- **Evidence networks**: Evidence tier filter (checkboxes per tier), source toggle
- **Knowledge graphs**: Entity type filter, importance threshold slider

## Prompt Output Generation

Every visualization includes a **"Generate Prompt"** button that:
1. Reads the current state (selected nodes, knowledge states, filters)
2. Generates a focused learning/research prompt based on the user's selections
3. Copies it to clipboard with a toast notification

This lets users cycle knowledge states, then generate a targeted prompt to paste back into Claude.

## Screenshot Workflow

After generating and saving the HTML file:

1. Start a loopback-only HTTP server on an available port, serving only the artifact directory; retain its PID. Do not kill another listener.
2. Navigate the available browser tool to the exact HTML file. Inspect rendering, source links, search, filters, and detail controls using its actual schema.
3. Capture and save `screenshot.png` only after rendering succeeds. Stop only the server process owned by this run.
4. Return the actual paths and browser-check result. If a browser is unavailable or fails, keep the HTML and mark it unverified; a saved file alone does not prove the interaction works.

Escape source text before inserting it into HTML/JavaScript. Inferred edges must be labeled and distinguishable from source-supported relationships. When running as a worker, write owned HTML/screenshot files and return the section to the parent; merge shared analysis notes only after workers join.

## Agent Autonomy & User Steering

### Autonomous (no user input needed)
- Template selection based on source command
- Concept/node extraction from analysis results
- Relationship inference between concepts
- Category clustering
- Knowledge state defaults (all `unknown`)
- Screenshot capture

### User can override
- **"skip visualization"** or **"no viz"** — suppress concept map generation entirely
- **"deeper on X"** — triggers enrichment of concept X with more detail nodes
- **"simpler"** — reduce node count, merge minor concepts into parent nodes
- **"focus on X and Y"** — filter visualization to show only selected concept clusters
- Cycling knowledge states in the playground and pasting the generated prompt back

## File Organization

All artifacts for one analysis live together:

```
gr/<category>/<slug>/
├── analysis.md          # Progressive markdown (timestamped entries)
├── concept-map.html     # Interactive visualization (or evidence-net.html, knowledge-graph.html)
└── screenshot.png       # Playwright capture of the visualization
```
