"""TypeScript templates for the Remotion scene infrastructure.

Ported from the video_explainer project (src/scenes/generator.py).
These templates are written directly to disk by the scene generator --
they are NOT sent through an LLM. STYLES_TEMPLATE and INDEX_TEMPLATE
are Python format strings (curly braces escaped for TypeScript);
REFERENCE_TEMPLATE uses raw single braces (JSX) and is written as-is.
"""

import json

# ---------------------------------------------------------------------------
# styles.ts template
# ---------------------------------------------------------------------------

STYLES_TEMPLATE = '''/**
 * Shared Style Constants
 *
 * Light theme with glow effects and dynamic layout system.
 * Uses Outfit font - modern geometric sans-serif for tech content.
 */

import React from "react";

// Outfit font family (loaded via @remotion/google-fonts in Root.tsx)
const outfitFont = '"Outfit", -apple-system, BlinkMacSystemFont, sans-serif';

// ===== COLOR PALETTE - LIGHT THEME WITH GLOW =====
export const COLORS = {{
  // Background colors
  background: "#FAFAFA",
  surface: "#FFFFFF",
  surfaceAlt: "#F5F5F7",

  // Text colors
  text: "#1A1A1A",
  textDim: "#555555",
  textMuted: "#888888",

  // Accent colors (optimized for glow effects)
  primary: "#0066FF",
  primaryGlow: "#0088FF",
  secondary: "#FF6600",
  secondaryGlow: "#FF8800",
  success: "#00AA55",
  successGlow: "#00DD77",
  warning: "#F5A623",
  warningGlow: "#FFB840",
  error: "#E53935",
  errorGlow: "#FF5555",
  purple: "#8844FF",
  purpleGlow: "#AA66FF",
  cyan: "#00BCD4",
  cyanGlow: "#00E5FF",
  pink: "#E91E63",
  pinkGlow: "#FF4081",
  lime: "#76B900",
  limeGlow: "#9BE000",

  // Layer visualization
  layerActive: "#0066FF",
  layerCompleted: "#00AA55",
  layerPending: "#E0E0E5",

  // Borders and shadows
  border: "#E0E0E5",
  borderLight: "#EEEEEE",
  shadow: "rgba(0, 0, 0, 0.08)",

  // Glow-specific
  glowSubtle: "rgba(0, 102, 255, 0.15)",
  glowMedium: "rgba(0, 102, 255, 0.3)",
  glowStrong: "rgba(0, 102, 255, 0.5)",
}};

// ===== FONTS =====
export const FONTS = {{
  primary: outfitFont,
  heading: outfitFont,
  mono: "SF Mono, Monaco, Consolas, monospace",
  system: outfitFont,
}};

// ===== SCENE INDICATOR =====
export const SCENE_INDICATOR = {{
  container: {{
    top: 24,
    left: 24,
    width: 44,
    height: 44,
    borderRadius: 10,
  }},
  text: {{
    fontSize: 16,
    fontWeight: 600 as const,
  }},
}};

// ===== SIDEBAR AREA =====
// Reserved space on the right for optional project-specific sidebars
// Set to 0 for full-width layouts (default), or 260 for layouts with a sidebar
export const SIDEBAR = {{
  width: {sidebar_width},
  padding: 16,
  gap: 4,
  borderRadius: 8,
}};

// ===== LAYOUT GRID SYSTEM =====
// Designed for 1920x1080 canvas
// When sidebar_width is 0, content uses full canvas width
// All values are CALCULATED from base constraints - no hardcoded positions

// Base constraints (these are the only "magic numbers")
const CANVAS_WIDTH = 1920;
const CANVAS_HEIGHT = 1080;
const SIDEBAR_WIDTH = {sidebar_width};  // Width of right sidebar area (0 = full width)
const SIDEBAR_GAP = {sidebar_width} > 0 ? 30 : 0;  // Gap only when sidebar exists
const MARGIN_LEFT = 60;
const MARGIN_RIGHT = 60;  // Symmetric with left margin
const TITLE_HEIGHT = 120;     // Space for title at top
const BOTTOM_MARGIN = 160;    // Space for references at bottom

// Derived values
const USABLE_LEFT = MARGIN_LEFT;
const USABLE_RIGHT = CANVAS_WIDTH - MARGIN_RIGHT - SIDEBAR_WIDTH - SIDEBAR_GAP;
const USABLE_WIDTH = USABLE_RIGHT - USABLE_LEFT;
const USABLE_TOP = TITLE_HEIGHT;
const USABLE_BOTTOM = CANVAS_HEIGHT - BOTTOM_MARGIN;
const USABLE_HEIGHT = USABLE_BOTTOM - USABLE_TOP;

// Quadrant calculations
const QUADRANT_WIDTH = USABLE_WIDTH / 2;
const QUADRANT_HEIGHT = USABLE_HEIGHT / 2;
const LEFT_CENTER_X = USABLE_LEFT + QUADRANT_WIDTH / 2;
const RIGHT_CENTER_X = USABLE_LEFT + QUADRANT_WIDTH + QUADRANT_WIDTH / 2;
const TOP_CENTER_Y = USABLE_TOP + QUADRANT_HEIGHT / 2;
const BOTTOM_CENTER_Y = USABLE_TOP + QUADRANT_HEIGHT + QUADRANT_HEIGHT / 2;

export const LAYOUT = {{
  // Canvas dimensions
  canvas: {{
    width: CANVAS_WIDTH,
    height: CANVAS_HEIGHT,
  }},

  // Margins from edges
  margin: {{
    left: MARGIN_LEFT,
    right: MARGIN_RIGHT,
    top: 40,
    bottom: 60,
  }},

  // Sidebar area (reserved for optional project-specific sidebars)
  sidebar: {{
    width: SIDEBAR_WIDTH,
    gap: SIDEBAR_GAP,
  }},

  // Content area bounds
  content: {{
    startX: USABLE_LEFT,
    endX: USABLE_RIGHT,
    width: USABLE_WIDTH,
    startY: USABLE_TOP,
    endY: USABLE_BOTTOM,
    height: USABLE_HEIGHT,
  }},

  // QUADRANT SYSTEM - dynamically calculated from constraints
  // Elements are CENTERED within their quadrant using transform: translate(-50%, -50%)
  quadrants: {{
    // Usable bounds
    bounds: {{
      left: USABLE_LEFT,
      right: USABLE_RIGHT,
      top: USABLE_TOP,
      bottom: USABLE_BOTTOM,
      width: USABLE_WIDTH,
      height: USABLE_HEIGHT,
    }},
    // Quadrant centers (for centering elements)
    topLeft: {{ cx: LEFT_CENTER_X, cy: TOP_CENTER_Y }},
    topRight: {{ cx: RIGHT_CENTER_X, cy: TOP_CENTER_Y }},
    bottomLeft: {{ cx: LEFT_CENTER_X, cy: BOTTOM_CENTER_Y }},
    bottomRight: {{ cx: RIGHT_CENTER_X, cy: BOTTOM_CENTER_Y }},
    // Quadrant dimensions
    quadrantWidth: QUADRANT_WIDTH,
    quadrantHeight: QUADRANT_HEIGHT,
  }},

  // Title area
  title: {{
    x: 80,
    y: 40,
    subtitleY: 90,
  }},
}};

// ===== ANIMATION =====
export const ANIMATION = {{
  fadeIn: 20,
  stagger: 5,
  spring: {{ damping: 20, stiffness: 120, mass: 1 }},
}};

// ===== FLEXIBLE LAYOUT HELPERS =====
// These functions dynamically calculate positions for any grid configuration

/**
 * Get layout positions for a flexible grid (any number of columns/rows)
 * Returns center positions for each cell, meant to be used with transform: translate(-50%, -50%)
 */
export const getFlexibleGrid = (
  cols: number,
  rows: number
): {{ cx: number; cy: number; width: number; height: number }}[] => {{
  const cellWidth = USABLE_WIDTH / cols;
  const cellHeight = USABLE_HEIGHT / rows;
  const positions: {{ cx: number; cy: number; width: number; height: number }}[] = [];

  for (let row = 0; row < rows; row++) {{
    for (let col = 0; col < cols; col++) {{
      positions.push({{
        cx: USABLE_LEFT + cellWidth * col + cellWidth / 2,
        cy: USABLE_TOP + cellHeight * row + cellHeight / 2,
        width: cellWidth,
        height: cellHeight,
      }});
    }}
  }}
  return positions;
}};

/**
 * Get a single centered position (for scenes with one main element)
 */
export const getCenteredPosition = (): {{ cx: number; cy: number; width: number; height: number }} => ({{
  cx: USABLE_LEFT + USABLE_WIDTH / 2,
  cy: USABLE_TOP + USABLE_HEIGHT / 2,
  width: USABLE_WIDTH,
  height: USABLE_HEIGHT,
}});

/**
 * Get 2-column layout (left and right halves)
 */
export const getTwoColumnLayout = (): {{
  left: {{ cx: number; cy: number; width: number; height: number }};
  right: {{ cx: number; cy: number; width: number; height: number }};
}} => {{
  const colWidth = USABLE_WIDTH / 2;
  return {{
    left: {{
      cx: USABLE_LEFT + colWidth / 2,
      cy: USABLE_TOP + USABLE_HEIGHT / 2,
      width: colWidth,
      height: USABLE_HEIGHT,
    }},
    right: {{
      cx: USABLE_LEFT + colWidth + colWidth / 2,
      cy: USABLE_TOP + USABLE_HEIGHT / 2,
      width: colWidth,
      height: USABLE_HEIGHT,
    }},
  }};
}};

/**
 * Get 3-column layout
 */
export const getThreeColumnLayout = (): {{
  left: {{ cx: number; cy: number; width: number; height: number }};
  center: {{ cx: number; cy: number; width: number; height: number }};
  right: {{ cx: number; cy: number; width: number; height: number }};
}} => {{
  const colWidth = USABLE_WIDTH / 3;
  return {{
    left: {{
      cx: USABLE_LEFT + colWidth / 2,
      cy: USABLE_TOP + USABLE_HEIGHT / 2,
      width: colWidth,
      height: USABLE_HEIGHT,
    }},
    center: {{
      cx: USABLE_LEFT + colWidth + colWidth / 2,
      cy: USABLE_TOP + USABLE_HEIGHT / 2,
      width: colWidth,
      height: USABLE_HEIGHT,
    }},
    right: {{
      cx: USABLE_LEFT + colWidth * 2 + colWidth / 2,
      cy: USABLE_TOP + USABLE_HEIGHT / 2,
      width: colWidth,
      height: USABLE_HEIGHT,
    }},
  }};
}};

/**
 * Get 2-row layout (top and bottom halves)
 */
export const getTwoRowLayout = (): {{
  top: {{ cx: number; cy: number; width: number; height: number }};
  bottom: {{ cx: number; cy: number; width: number; height: number }};
}} => {{
  const rowHeight = USABLE_HEIGHT / 2;
  return {{
    top: {{
      cx: USABLE_LEFT + USABLE_WIDTH / 2,
      cy: USABLE_TOP + rowHeight / 2,
      width: USABLE_WIDTH,
      height: rowHeight,
    }},
    bottom: {{
      cx: USABLE_LEFT + USABLE_WIDTH / 2,
      cy: USABLE_TOP + rowHeight + rowHeight / 2,
      width: USABLE_WIDTH,
      height: rowHeight,
    }},
  }};
}};

/**
 * Get style for centering an element at a position
 * Use with: left: pos.cx * scale, top: pos.cy * scale, transform: "translate(-50%, -50%)"
 */
export const getCenteredStyle = (
  pos: {{ cx: number; cy: number }},
  scale: number
): React.CSSProperties => ({{
  position: 'absolute',
  left: pos.cx * scale,
  top: pos.cy * scale,
  transform: 'translate(-50%, -50%)',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
}});

/**
 * Convert a position to scaled pixel values
 */
export const scalePosition = (
  pos: {{ cx: number; cy: number; width: number; height: number }},
  scale: number
): {{ cx: number; cy: number; width: number; height: number }} => ({{
  cx: pos.cx * scale,
  cy: pos.cy * scale,
  width: pos.width * scale,
  height: pos.height * scale,
}});

// ===== HELPER FUNCTIONS =====
export const getScale = (width: number, height: number): number => {{
  return Math.min(width / 1920, height / 1080);
}};

export const getSceneIndicatorStyle = (scale: number): React.CSSProperties => ({{
  position: "absolute",
  top: SCENE_INDICATOR.container.top * scale,
  left: SCENE_INDICATOR.container.left * scale,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: SCENE_INDICATOR.container.width * scale,
  height: SCENE_INDICATOR.container.height * scale,
  borderRadius: SCENE_INDICATOR.container.borderRadius * scale,
  backgroundColor: `${{COLORS.primary}}20`,
  border: `2px solid ${{COLORS.primary}}`,
  boxShadow: `0 2px 12px ${{COLORS.primary}}30`,
}});

export const getSceneIndicatorTextStyle = (scale: number): React.CSSProperties => ({{
  fontSize: SCENE_INDICATOR.text.fontSize * scale,
  fontWeight: SCENE_INDICATOR.text.fontWeight,
  color: COLORS.primary,
  fontFamily: FONTS.mono,
}});

export default {{ COLORS, FONTS, ANIMATION, SIDEBAR }};
'''

# ---------------------------------------------------------------------------
# index.ts template
# ---------------------------------------------------------------------------

INDEX_TEMPLATE = '''/**
 * Scene Registry
 *
 * Exports all scene components for the video.
 * Keys match scene_id suffixes in storyboard.json (e.g., "scene1_hook" -> "hook")
 */

import React from "react";

{imports}

export type SceneComponent = React.FC<{{ startFrame?: number }}>;

/**
 * Scene registry mapping storyboard scene types to components.
 * Keys must match the scene_id suffix in storyboard.json
 */
const SCENE_REGISTRY: Record<string, SceneComponent> = {{
{registry_entries}
}};

// Standard export name for the build system (required by remotion/src/scenes/index.ts)
export const PROJECT_SCENES = SCENE_REGISTRY;

{exports}

export function getScene(type: string): SceneComponent | undefined {{
  return SCENE_REGISTRY[type];
}}

export function getAvailableSceneTypes(): string[] {{
  return Object.keys(SCENE_REGISTRY);
}}
'''

# ---------------------------------------------------------------------------
# Reference.tsx template (NOT a format string -- single braces for JSX)
# ---------------------------------------------------------------------------

REFERENCE_TEMPLATE = '''/**
 * Reference Component
 *
 * Displays source references in the bottom-right corner of scenes.
 * Used to show citations, sources, and technical references.
 */

import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig, spring } from "remotion";
import { COLORS, FONTS } from "../styles";

interface ReferenceProps {
  sources: string[];
  startFrame?: number;
  delay?: number;
}

export const Reference: React.FC<ReferenceProps> = ({
  sources,
  startFrame = 0,
  delay = 60,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const localFrame = frame - startFrame;
  const scale = Math.min(width / 1920, height / 1080);

  // Fade in animation
  const opacity = spring({
    frame: localFrame - delay,
    fps,
    config: { damping: 20, stiffness: 80 },
  });

  if (sources.length === 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        right: 24 * scale,
        bottom: 24 * scale,
        maxWidth: 300 * scale,
        opacity,
        fontFamily: FONTS.system,
      }}
    >
      <div
        style={{
          backgroundColor: "rgba(255, 255, 255, 0.9)",
          borderRadius: 8 * scale,
          padding: `${8 * scale}px ${12 * scale}px`,
          border: `1px solid ${COLORS.border}`,
          boxShadow: `0 2px 8px rgba(0, 0, 0, 0.08)`,
        }}
      >
        <div
          style={{
            fontSize: 9 * scale,
            fontWeight: 600,
            color: COLORS.textMuted,
            textTransform: "uppercase",
            letterSpacing: 0.5 * scale,
            marginBottom: 4 * scale,
          }}
        >
          Sources
        </div>
        {sources.map((source, index) => (
          <div
            key={index}
            style={{
              fontSize: 9 * scale,
              color: COLORS.textDim,
              lineHeight: 1.4,
              marginTop: index > 0 ? 2 * scale : 0,
            }}
          >
            {source}
          </div>
        ))}
      </div>
    </div>
  );
};

export default Reference;
'''


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def generate_styles_content(
    project_title: str,
    sidebar_width: int = 0,
) -> str:
    """Format STYLES_TEMPLATE with the given sidebar width.

    Args:
        project_title: Accepted for compatibility with existing callers.
        sidebar_width: Right-side sidebar width in pixels (0 = full width).

    Returns:
        Formatted TypeScript source for ``styles.ts``.
    """
    return STYLES_TEMPLATE.format(
        sidebar_width=sidebar_width,
    )


def generate_index_content(
    scenes: list[dict],
    project_title: str,
) -> str:
    """Format INDEX_TEMPLATE from a list of scene descriptors.

    Each dict in *scenes* must contain:
      - ``component_name``: PascalCase React component name.
      - ``filename``: File name (with or without ``.tsx`` extension).
      - ``scene_key``: Registry key matching the storyboard scene_id suffix.

    Logic ported from ``SceneGenerator._generate_index()`` in the
    video_explainer project.

    Args:
        scenes: Ordered list of scene descriptors.
        project_title: Accepted for compatibility with existing callers.

    Returns:
        Formatted TypeScript source for ``index.ts``.
    """
    imports: list[str] = []
    exports: list[str] = []
    registry_entries: list[str] = []

    for scene in scenes:
        name = scene["component_name"]
        filename = scene["filename"].replace(".tsx", "")
        scene_key = scene["scene_key"]
        scene_key_literal = json.dumps(scene_key)

        imports.append(f'import {{ {name} }} from "./{filename}";')
        exports.append(f'export {{ {name} }} from "./{filename}";')
        registry_entries.append(f"  {scene_key_literal}: {name},")

    return INDEX_TEMPLATE.format(
        imports="\n".join(imports),
        exports="\n".join(exports),
        registry_entries="\n".join(registry_entries),
    )
