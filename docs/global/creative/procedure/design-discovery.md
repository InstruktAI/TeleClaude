---
id: 'creative/procedure/design-discovery'
type: 'procedure'
domain: 'creative'
scope: 'global'
description: 'Translate human visual thinking into a grounded design spec through structured dialogue and reference analysis.'
---

# Design Discovery — Procedure

## Required reads

@~/.teleclaude/docs/creative/spec/design-spec.md

## Goal

Produce a concrete design spec (`design-spec.md`) as a todo artifact from human
visual intent. The document must be specific enough that any builder agent —
regardless of which AI model — produces a cohesive, distinctive result that the
human recognizes as *their* vision, not a generic interpretation.

This procedure bridges the gap between "I want something beautiful" and a language
artifact that constrains and guides implementation. It is the creative equivalent
of requirements discovery: the output is not code but the anchor that makes code
coherent.

## Preconditions

1. A todo exists with `input.md` containing the human's initial thinking.
2. The human is available for dialogue (this is an interactive procedure).
3. The design spec schema (`creative/spec/design-spec`) is loaded for reference.
4. If visual references exist (URLs, screenshots, repos), they are accessible.

## Steps

### 1. Read and absorb the input

Read `todos/{slug}/input.md` and any existing artifacts. Do not respond with
structure yet — absorb the intent, the energy, the aesthetic direction hinted at
in the human's words. Identify:

- What emotional register they are reaching for.
- What anti-references they name (what it should NOT be).
- What medium they describe (static site, app, scroll experience, etc.).
- What existing identity or brand elements exist to build on or depart from.

### 2. Ground in references

If the human provides visual references (URLs, screenshots, repos, existing
products), investigate them thoroughly:

- Fetch and analyze reference websites for layout patterns, color usage,
  typography choices, motion behavior, and spatial rhythm.
- Clone or read reference repos for implementation patterns and design tokens.
- Extract the *principles* behind what works in the references — not to copy
  but to understand the design language the human is responding to.

If no references are provided, ask for them. Even one reference dramatically
narrows the interpretation space. "Show me one website that feels like what
you want" is more productive than twenty questions about color preferences.

**Reference sourcing guidance for the human:**

When looking for visual references, use sites that curate specific design
dimensions rather than browsing generically:

- **Hero sections**: [Threed.ai](https://threed.ai) / similar hero-focused
  galleries — curated 3D and animated hero patterns.
- **Interaction design**: [Web Interactions Gallery](https://webinteractions.gallery)
  — motion, micro-interactions, scroll-driven animations.
- **Color-driven discovery**: [Realtime Colors](https://realtimecolors.com) —
  find real websites filtered by color palette, useful for matching brand
  direction to existing examples.
- **Component inspiration**: [CLUI](https://clui.com) — daily UI component
  updates and patterns.
- **Full-page screenshots**: GoFullPage (Chrome extension) — capture entire
  pages for reference analysis.

Keep references to 2-3 images maximum. More than three dramatically different
references confuse the synthesis — the agent cannot hold contradictory visual
languages and will average them into something generic. Pick references that
share a common thread (similar mood, spatial rhythm, or color temperature)
even if they differ in detail.

### 3. Dialogue: sense the vision

This is the creative core. The procedure is conversational, not mechanical.
Follow the breath:

**Inhale** — ask expansive questions that help the human articulate what they
see in their mind:

- "What's the first impression when someone lands? What do they *feel*?"
- "If this were a physical space, what would it look like? A gallery? A
  workshop? A rooftop at night?"
- "What's the one thing that makes someone stop scrolling and pay attention?"

**Hold** — sit with tensions. The human may want contradictory things
("retro but cutting-edge", "minimal but rich"). Name the tension, don't
resolve it prematurely. Often the tension IS the identity — the design
that holds both poles is the distinctive one.

**Exhale** — when the vision crystallizes, reflect it back in precise visual
language. Not "so you want something modern" but "dark background, monospace
type, neon accent on a single CTA, scroll reveals sections like terminal
output printing line by line." The human confirms or redirects.

Key areas to cover through dialogue:

- **Emotional register**: how the site should make someone feel.
- **Visual metaphor**: is there a spatial or physical analogy?
- **Color direction**: warm/cool, saturated/muted, monochrome/vibrant.
- **Typography feel**: technical/editorial/expressive, serif/sans/mono.
- **Motion intent**: how things move, how sections transition, scroll behavior.
- **Content arc**: for scroll-driven sites, the storytelling structure from
  top to bottom — what's the hook, what's the journey, what's the resolution.

### 4. Analyze and synthesize

After dialogue converges, synthesize the findings into structured design
decisions. For each section of the design spec schema:

- Map the human's expressed intent to concrete values.
- Where the human expressed a direction but not specifics (e.g., "warm colors"),
  propose concrete values with rationale.
- Mark all agent-proposed values as `[proposed]` so the human can distinguish
  their input from the agent's interpretation.
- Flag any sections where the human's intent is still ambiguous — these are
  explicit gaps, not things to silently fill.

### 5. Write the design spec

Write `todos/{slug}/design-spec.md` following the design spec schema.
Every canonical section must be present. The document must:

- Be self-contained: a builder reading only this document and `input.md` should
  produce a coherent result without needing the discovery conversation.
- Distinguish human-stated values from agent-proposed values (`[proposed]`).
- Include the reference analysis findings where they inform specific decisions.
- Be precise about motion and spatial behavior — these are the sections most
  likely to be underspecified and most critical for distinctive results.

### 6. Validate with the human

Present the complete design spec to the human. Walk through each
section, highlighting:

- Proposed values that need confirmation or revision.
- Tensions that were resolved — confirm the resolution landed right.
- Gaps that remain — agree on whether to fill them now or defer.

Iterate until the human confirms the document captures their vision.

### 7. Update todo state

Once the design spec is confirmed:

- The `design-spec.md` artifact exists in the todo folder.
- Update `input.md` if the discovery dialogue surfaced new intent that
  supersedes the original input.
- The todo is now ready for requirements discovery, which can reference
  the design spec as a grounding artifact.

## Outputs

1. `todos/{slug}/design-spec.md` — the concrete design spec instance,
   following the `creative/spec/design-spec` schema.
2. Updated `todos/{slug}/input.md` if discovery surfaced new or revised intent.
3. Human confirmation that the design spec captures their vision.

## Recovery

1. If the human cannot articulate their vision, shift to reference-driven
   discovery: show them 3-5 real websites spanning different aesthetics and
   ask "which of these feels closest?" Triangulate from their reactions.
2. If dialogue stalls on a specific section (e.g., motion), skip it and
   return after other sections crystallize — adjacent decisions often resolve
   the stalled one.
3. If the human and agent disagree on a proposed value, the human's preference
   wins unconditionally. The agent's role is to articulate options with
   rationale, not to override aesthetic judgment.
4. If no visual references are available and the human's description is too
   abstract for concrete values, write the design spec with explicit
   `[TBD — needs reference]` markers rather than inventing values that may
   miss the mark.
