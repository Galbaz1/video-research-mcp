---
name: image-generation
description: Enhances image generation prompts with Subject-Context-Style structure, style anchors, character consistency, and reference-based editing. Not for video generation, TTS, FFmpeg, audio, or design-to-code.
---

# Image Generation Prompt Best Practices

This plugin does not bundle an image-generation tool. Discover the active provider, inspect its schema, and confirm spend/attempt limits before requesting images. Provider-specific parameter names such as `inputImagePath` are not portable.

Verified on 2026-09-29: Google documents `gemini-3.1-flash-image` for general generation/editing, `gemini-3.1-flash-lite-image` for inexpensive 1K work, and `gemini-3-pro-image` for complex design. See [official image guidance](https://ai.google.dev/gemini-api/docs/image-generation) for exact API, supported references, sizes, and pricing; use the provider available to the session.

## Prompt Structure

Enhance every image generation prompt around three core elements:

### 1. SUBJECT (What)

The main focus of the image.

- Physical characteristics: textures, materials, colors, scale
- Actions, poses, expressions if applicable
- Distinctive features that define the subject

### 2. CONTEXT (Where/When)

The environment and conditions.

- Setting, background, spatial relationships (foreground, midground, background)
- Time of day, weather, atmospheric conditions
- Mood and emotional tone of the scene

### 3. STYLE (How)

The visual treatment.

- Artistic or photographic approach: reference specific artists, movements, or styles
- Lighting design: direction, quality, color temperature, shadows
- Camera/lens choices: specify focal length, aperture, and shooting angle when photographic

## Core Principles

- **Preserve intent** -- Enrich the user's original vision, never override it
- **Preserve constraints** -- Describe desired elements positively and retain explicit exclusions using supported instructions or a negative-prompt field
- **Specific over vague** -- "golden hour sunlight at 15 degree angle" beats "nice lighting"
- **Natural flow** -- Weave elements into a single flowing description, not a bullet list

## Enhancement Patterns

### Hyper-Specific Details

Add concrete visual details where the user left gaps:

- Lighting: direction, quality, color temperature, shadow behavior. **Always name the physical source** ("warm afternoon sun through west window", not "warm lighting") -- named sources produce consistent shadows
- Textures: surface materials, weathering, reflectivity
- Atmosphere: particulates, humidity, depth haze
- Scale: relative sizes, distances, proportions

### Camera Control Terminology

When a photographic look is appropriate:

- Lens type: "shot with 85mm portrait lens", "wide-angle 24mm"
- Aperture: "shallow depth of field at f/1.8", "deep focus at f/11"
- Angle: "low angle emphasizing height", "bird's eye view"
- Motion: "motion blur on the paws", "frozen mid-action"

### Atmospheric Enhancement

Convey mood through environmental details:

- Emotional tone: "serene", "ominous", "jubilant"
- Light quality: "dappled shadows", "harsh midday sun", "soft diffused overcast"
- Weather/air: "morning mist", "dust particles in a sunbeam"

### Text in Images

When the image should contain readable text (signs, labels, titles, typography):

- Specify the exact text content in quotes: `"OPEN 24 HOURS" in bold sans-serif`
- Describe visual treatment: font style, weight, size relative to the scene
- Define placement and integration: "centered on the storefront awning", "hand-lettered on the chalkboard"

## Feature Patterns

### Character Consistency

When the same character must be recognizable across multiple images:

- Include **at least 3 recognizable visual markers** (distinctive scar, signature clothing, unique hairstyle, characteristic accessory)
- Use anchoring words: "distinctive", "signature", "always wears", "always has"
- Be specific: "round tortoiseshell glasses" not just "glasses"
- Use the active provider's reference-image field to edit the base character image; inspect the resulting markers before using it as a reference

### Compositional Integration (Multi-Element Blending)

When combining multiple visual elements in one scene:

- Define spatial relationships with proportions: "foreground (40% of frame)", "midground", "background"
- Use integration language: "seamlessly blending", "harmoniously composed", "naturally integrated"
- Specify relative scale and interaction between elements

### Real-World Accuracy

When depicting real places, cultures, or historical elements:

- Use specific terminology: "traditional Edo-period architecture", "authentic Moroccan zellige tilework"
- Include culturally accurate details
- Reference geographical or historical specifics

### Purpose-Driven Enhancement

Tailor the prompt to the intended use:

| Purpose | Emphasis |
|---------|----------|
| Product photo | Clean background, studio lighting, commercial appeal |
| UI mockup | Flat design elements, consistent spacing, screen-appropriate |
| Presentation slide | Bold composition, clear focal point, text-friendly layout |
| Social media | Eye-catching, vibrant, crop-friendly aspect ratio |
| Book/album cover | Typography space, dramatic mood, symbolic elements |
| **Video style anchor** | Supported resolution sufficient for delivery, named physical light source, required surface/identity details, and inspected composition. Reuse the accepted reference downstream |

### Video Style Anchor Pipeline

When generating images that will serve as style references for AI video production:

1. **Match delivery needs**: choose a supported size that preserves the required details; use 4K only when its added cost serves the output
2. **Character consistency**: maintain character consistency when generating multiple hero images for the same scene or character
3. **Inspect before reuse**: verify lighting, texture, composition, and identity; allow one targeted repair within the authorized budget
4. **Blend for composites**: combine reference photography with branded elements when building composite anchors
5. **Match video prompt lighting**: use the exact same physical light source description in the image prompt that will appear in the video prompt -- shadow direction must be consistent across the chain

## Image Editing

When modifying an existing image:

- **Preserve** the original's core characteristics: color palette, lighting style, composition
- Use anchoring phrases: "maintain the existing...", "preserve the original...", "keep the same..."
- Be specific about what to change vs what to keep unchanged
- Describe modifications relative to the existing image, not from scratch

## Example

**Input:** "A happy dog in a park"

**Enhanced:** "Golden retriever mid-leap catching a red frisbee, ears flying, tongue out in joy, in a sunlit urban park. Soft morning light filtering through oak trees creates dappled shadows on emerald grass. Background shows families on picnic blankets, slightly out of focus. Shot from low angle emphasizing the dog's athletic movement, with motion blur on the paws suggesting speed."

## Completion

Inspect the actual image at full resolution for subject fidelity, text, required exclusions, and editing boundaries. Return its path, provider/model, reference provenance, and unresolved defects. A successful tool response or a larger requested resolution does not prove the image meets the brief.
