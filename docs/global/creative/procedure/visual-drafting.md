---
id: 'creative/procedure/visual-drafting'
type: 'procedure'
domain: 'creative'
scope: 'global'
description: 'Produce self-contained HTML+CSS visual artifacts from a confirmed design system document.'
---

# Visual Drafting — Procedure

## Required reads

@~/.teleclaude/docs/creative/spec/visual-artifact.md
@~/.teleclaude/docs/creative/policy/visual-constraints.md
@~/.teleclaude/docs/creative/spec/design-system.md

## Goal

Produce visual artifacts — self-contained HTML+CSS files — that faithfully express
a confirmed design system for a specific project. The artifacts are visual references
that a builder will translate into the target framework.

The creative agent's job is visual thinking in code: layout, color, typography,
spatial rhythm, and motion. Not application logic, not component architecture,
not responsiveness. Pure visual expression within the design system's boundaries.

## Preconditions

1. `todos/{slug}/design-system.md` exists and is confirmed by the human.
2. `todos/{slug}/input.md` exists with project context.
3. Reference images or screenshots are available if the design system references them.
4. The visual artifact spec and visual constraints policy are loaded.

## Steps

### 1. Absorb the design system

Read `todos/{slug}/design-system.md` completely. Internalize:

- The CSS custom properties you will define (colors, fonts, spacing).
- The motion vocabulary — which animation techniques are specified, what
  easing curves and durations are prescribed.
- The content tone — how text should read, what voice to use for placeholder copy.
- The emotional register — this guides every micro-decision about spacing,
  contrast, and visual weight.

Read `todos/{slug}/input.md` for the content arc — what sections exist, what
the storytelling structure is, what the human wants the viewer to experience.

### 2. Plan the section breakdown

Before writing any HTML, list the sections you will produce as individual files.
For a one-page scroller, typical sections might be:

- `hero.html` — the first impression, the hook.
- `value-prop.html` — what the product does and why it matters.
- `features.html` — capabilities, demonstrated visually.
- `story.html` — the narrative, the journey, the deeper context.
- `social-proof.html` — testimonials, logos, numbers.
- `cta.html` — the call to action, the resolution.
- `footer.html` — navigation, links, legal.

The actual sections come from the input and design system. Do not invent sections
the human did not ask for. If the input says "three sections," produce three files.

### 3. Build the CSS foundation first

Start each file by defining the design system tokens as CSS custom properties:

```css
:root {
  /* Colors — from design-system.md section 3 */
  --primary: #...;
  --accent: #...;
  --bg: #...;
  --text: #...;

  /* Typography — from design-system.md section 4 */
  --font-heading: '...', sans-serif;
  --font-body: '...', sans-serif;
  --font-mono: '...', monospace;

  /* Spacing — from design-system.md section 5 */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 32px;
  --space-xl: 64px;

  /* Motion — from design-system.md section 6 */
  --ease-default: cubic-bezier(0.16, 1, 0.3, 1);
  --duration-fast: 150ms;
  --duration-normal: 300ms;
  --duration-slow: 600ms;
}
```

Every value here must be traceable to the design system document. Copy the exact
values — do not approximate, round, or "improve" them.

### 4. Layer the visual design

Build each section in this order:

1. **Structure**: semantic HTML elements, content hierarchy, placeholder copy
   that matches the design system's content tone.
2. **Typography**: apply font families, sizes, weights, line heights from the
   design system's type scale. Get the text feeling right before touching color.
3. **Spacing**: apply the spacing scale. Establish the spatial rhythm between
   elements. This is where the section starts to breathe (or feel dense, per
   the design system's intent).
4. **Color**: apply the palette. Background, text, accents, borders. Check
   contrast ratios as you go.
5. **Motion**: add CSS animations last. Scroll-driven reveals, hover transitions,
   decorative keyframe loops. Follow the design system's motion philosophy —
   if it says "animation is rare and meaningful," use restraint.

This layering order prevents the common failure where agents produce something
that looks flashy but has poor typographic hierarchy or broken spatial rhythm
because they started with effects instead of foundations.

### 5. Implement scroll-driven animations

For scroll-based sites, use CSS scroll-driven animations as the primary technique:

```css
.section {
  opacity: 0;
  transform: translateY(40px);
  animation: section-enter linear both;
  animation-timeline: view();
  animation-range: entry 0% entry 50%;
}

@keyframes section-enter {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

Each section's entrance animation should be distinct but cohesive — the design
system's transition vocabulary defines the available patterns. Do not invent
new motion patterns not in the vocabulary.

Add the `prefers-reduced-motion` override at the end of every file.

### 6. Annotate non-CSS motion

If the design system specifies motion that CSS cannot express, add `data-motion-*`
attributes to the relevant elements. Include the best possible CSS approximation
in the stylesheet so the artifact still demonstrates the intent visually.

### 7. Self-review

Before delivering, check each artifact against:

- [ ] Opens in browser via `file://` — no errors, no blank sections.
- [ ] Every color value matches a design system custom property.
- [ ] Every font, size, and weight matches the design system type scale.
- [ ] Spacing follows the design system scale — no magic numbers.
- [ ] Animations use only CSS — no `<script>` tags anywhere.
- [ ] `prefers-reduced-motion` media query present and functional.
- [ ] Semantic HTML — correct element choices, logical source order.
- [ ] Placeholder copy matches the design system's content tone.
- [ ] No external dependencies — no CDN links, no remote resources.
- [ ] File is under ~500 lines (split if larger).

### 8. Write to the todo folder

Place all artifacts in `todos/{slug}/visuals/`:

```
todos/{slug}/visuals/
  hero.html
  features.html
  story.html
  assets/
    logo.svg
```

If this is a multi-agent bake-off, place artifacts in a named subfolder:
`todos/{slug}/visuals/{agent-name}/`.

## Outputs

1. Visual artifact HTML files in `todos/{slug}/visuals/`.
2. Any generated or referenced assets in `todos/{slug}/visuals/assets/`.
3. All artifacts passing the self-review checklist.

## Recovery

1. If the design system lacks values needed for a section (e.g., no shadow
   definition but a card design implies shadows), mark the gap with
   `[proposed]` in a CSS comment and use a reasonable value. The human
   resolves whether to add it to the design system.
2. If CSS scroll-driven animations produce unexpected behavior in a specific
   browser, simplify to basic opacity/transform transitions as a fallback.
   Note the limitation in a comment.
3. If a section's visual design cannot be achieved within the CSS-only
   constraint, annotate with `data-motion-*` and produce the best CSS
   approximation. Do not silently add JavaScript.
4. If the input's content arc is ambiguous about a section's purpose, use
   placeholder content that clearly signals "this needs human input" rather
   than inventing a narrative the human did not intend.
