---
id: 'creative/spec/design-system'
type: 'spec'
domain: 'creative'
scope: 'global'
description: 'Schema for design system documents that anchor visual identity and constrain agent-generated UI.'
---

# Design System — Spec

## What it is

A design system document is the authoritative visual anchor for a product or website.
It captures the complete visual language — identity, tokens, motion, spatial rhythm,
and content tone — in prose and structured values that any agent can build from without
guessing.

The design system is not a wireframe, not code, and not a mood board. It is a language
artifact that sits between human visual intent and implementation. It is the hard
constraint: every generated UI variation must stay within its boundaries. An agent that
invents colors, fonts, or motion patterns not in the design system is violating the
contract.

In the todo workflow, a concrete design system instance lives as a todo artifact
(e.g., `todos/{slug}/design-system.md`) alongside `input.md` and `requirements.md`.
The design discovery procedure produces it; the builder consumes it.

## Canonical fields

Every design system document must include the following sections. Sections may be
minimal for early-stage projects but must never be omitted — an explicit "TBD" is
better than a missing section.

### 1. Product context

- **What it is**: one-paragraph description of the product/site and its purpose.
- **Target audience**: who will see and use this. Demographics, technical level,
  expectations.
- **Core value proposition**: the single sentence that justifies the product's
  existence.
- **Emotional register**: how the product should make someone *feel*. Not
  "professional" — specific: "confident and slightly awed" or "playful but not
  childish" or "like discovering something underground."

### 2. Visual identity

- **Mood / aesthetic direction**: the overall visual feel described in language.
  Reference points (existing sites, art movements, physical objects) are encouraged.
  "Retro-futuristic terminal" or "brutalist with warmth" — not "modern and clean."
- **What it is NOT**: explicit anti-references. "Not generic SaaS." "Not a docs site."
  "Not Material Design." These constraints prevent drift toward safe defaults.
- **Logo and brand marks**: description or reference to existing assets.
- **Photography / illustration direction**: if applicable, the style of imagery.

### 3. Color system

- **Primary palette**: the dominant colors with hex values and semantic names.
- **Accent palette**: secondary colors for highlights, CTAs, interactive states.
- **Neutral palette**: grays, backgrounds, text colors.
- **Semantic colors**: success, warning, error, info.
- **Dark/light mode**: whether supported, and how palettes adapt.
- **Usage rules**: which colors are used where. "Primary is never used for
  backgrounds." "Accent appears only on interactive elements."

### 4. Typography

- **Font families**: primary (headings), secondary (body), monospace (code/accents).
  Include fallback stacks.
- **Type scale**: sizes for H1 through body, small, and caption. Can be a ratio
  (1.25 major third) or explicit pixel/rem values.
- **Weight usage**: which weights for which contexts. "Bold only for H1 and CTAs."
- **Line height and letter spacing**: defaults and any exceptions.
- **Content tone**: how the text *reads*. "Short, punchy sentences." "Technical
  but accessible." "First person plural." This bridges visual and editorial.

### 5. Spacing and layout

- **Spacing scale**: the base unit and scale (4px base, 8/12/16/24/32/48/64).
- **Grid system**: columns, gutters, max-width, breakpoints.
- **Spatial rhythm**: how whitespace is used to create breathing room between
  sections. "Generous — sections float in space" vs "Dense — information-rich."
- **Responsive behavior**: how the layout adapts across breakpoints. Key
  transformation points (e.g., "navigation collapses to hamburger at 768px").

### 6. Motion and animation

- **Motion philosophy**: "Everything animates" vs "Animation is rare and
  meaningful" vs "Physics-based, organic movement."
- **Transition vocabulary**: the specific motion patterns used. Fade, slide,
  scale, morph, parallax, reveal-on-scroll. Each with duration ranges and
  easing curves.
- **Scroll behavior**: for scroll-driven sites — how sections enter and exit.
  "Sections fade in from below with 20% opacity at viewport edge, reaching
  full opacity at 30% viewport." Be specific enough for implementation.
- **Micro-interactions**: hover states, button feedback, loading states.
- **Performance constraints**: "No animation on reduced-motion preference."
  "All animations under 300ms." "GPU-accelerated transforms only."

### 7. Component patterns

- **Component vocabulary**: the UI primitives this design system uses.
  Buttons, cards, navigation, forms, modals — with their visual treatment
  described (not implemented).
- **State treatments**: how components look in hover, active, disabled, focus,
  error states.
- **Iconography**: icon style (outline, filled, duotone), size conventions,
  source library if applicable.

### 8. Constraints and boundaries

- **Technology constraints**: "Must be static-deployable." "No JavaScript
  framework lock-in." "Must work without a backend."
- **Performance budget**: target load time, bundle size limits, Lighthouse
  score targets.
- **Accessibility requirements**: WCAG level, contrast ratios, keyboard
  navigation, screen reader considerations.
- **Browser/device support**: minimum supported browsers and viewport sizes.

## Allowed values

- `domain`: always `creative` for design system specs.
- `scope`: `global` for the schema itself; concrete instances are todo artifacts
  (not snippets) scoped to their work item.
- Sections may contain subsections beyond what is listed here — the canonical
  fields are the minimum, not the ceiling.

## Known caveats

- A design system document is a living artifact during the design discovery phase.
  It stabilizes before implementation begins but may evolve across product iterations.
- The design system constrains visual output but does not prescribe implementation
  technology. A builder may implement the same design system in React, Astro, vanilla
  HTML, or any other stack.
- Color values in the design system are the source of truth. If code diverges from
  the documented values, the design system wins and the code is the bug.
- For scroll-driven or animation-heavy sites, section 6 (Motion and animation) is
  the most critical section. Underspecifying motion produces generic parallax instead
  of distinctive spatial storytelling.
