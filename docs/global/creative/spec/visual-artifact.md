---
id: 'creative/spec/visual-artifact'
type: 'spec'
domain: 'creative'
scope: 'global'
description: 'Interchange format for visual artifacts: self-contained HTML+CSS files with CSS-only animations, constrained by a design spec.'
---

# Visual Artifact — Spec

## Required reads

@~/.teleclaude/docs/creative/spec/design-spec.md

## What it is

A visual artifact is a self-contained HTML file with embedded CSS that represents
a section, page, or component of a visual design. It is the interchange format
between creative agents and builders — produced during the creative phase, consumed
during implementation.

Visual artifacts are references, not production code. A builder reads the artifact,
sees what the human approved, and translates it into the target framework (React,
Astro, Next.js, etc.). The artifact captures what things look like and how they move.
The builder adds the wiring: routing, data, state, server rendering.

Visual artifacts live in `todos/{slug}/html/` alongside other todo artifacts.
They are constrained by `todos/{slug}/design-spec.md` — every visual choice in
the artifact must trace back to the design spec.

## Canonical fields

### File structure

Each visual artifact is a single `.html` file:

```
todos/{slug}/html/
  hero.html
  features.html
  story.html
  footer.html
  assets/
    logo.svg
    hero-bg.png
    ...
```

- One file per logical section or page.
- File names are lowercase, hyphenated, descriptive (`hero.html`, not `section-1.html`).
- The `assets/` subfolder holds images, SVGs, and other static resources referenced
  by the HTML files. Assets are referenced via relative paths (`assets/logo.svg`).

### HTML requirements

Every visual artifact file must include:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{Section Name} — {Project Name} Visual Draft</title>
  <style>
    /* All CSS embedded here — no external stylesheets */
  </style>
</head>
<body>
  <!-- Section content -->
</body>
</html>
```

- No external stylesheet links. All CSS is embedded in `<style>`.
- No `<script>` tags. No JavaScript. See the visual constraints policy.
- No CDN links for fonts. Fonts are either system fonts, referenced via
  `@font-face` with local files in `assets/`, or web-safe fallbacks.
- Images reference local `assets/` paths, not remote URLs.
- The file must render correctly when opened directly in a browser via
  `file://` — no server required.

### CSS animation requirements

All motion is expressed in CSS. The available animation techniques:

**Scroll-driven animations** (primary technique for scroll-based sites):

```css
.section {
  animation: fade-in linear;
  animation-timeline: view();
  animation-range: entry 0% entry 100%;
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(40px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

**Keyframe animations** for timed motion:

```css
@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.05); }
}
```

**Transitions** for state changes (hover, focus):

```css
.button {
  transition: background-color 200ms ease-out, transform 150ms ease-out;
}
.button:hover {
  background-color: var(--accent);
  transform: translateY(-2px);
}
```

**Parallax** via CSS perspective:

```css
.parallax-container {
  perspective: 1px;
  overflow-y: auto;
  height: 100vh;
}
.parallax-layer-back {
  transform: translateZ(-1px) scale(2);
}
```

### Motion annotation

For motion that CSS alone cannot express (physics-based springs, sequence-dependent
choreography, velocity-responsive behavior), use `data-motion-*` attributes as
annotations for the builder:

```html
<div class="hero-element"
     data-motion-type="spring"
     data-motion-stiffness="100"
     data-motion-damping="15"
     data-motion-trigger="viewport-enter"
     data-motion-note="Bouncy entrance when element enters viewport.
       CSS approximation shown; implement with Framer Motion useSpring.">
</div>
```

Required annotation attributes when used:

- `data-motion-type`: the motion type (`spring`, `sequence`, `physics`, `gesture`).
- `data-motion-trigger`: what initiates the motion (`viewport-enter`, `scroll-past-50%`,
  `after-previous`, `hover`, `click`).
- `data-motion-note`: plain-language description of the intended behavior and
  suggested implementation approach.

The CSS in the file should include the best possible CSS approximation of the
annotated motion. The annotation tells the builder where the CSS falls short and
what to use instead.

### Design system fidelity

Every visual choice must trace to `design-spec.md`:

- Colors: use CSS custom properties that map to the design spec palette.
  Define them at the top of `<style>`:

  ```css
  :root {
    --primary: #1a1a2e;
    --accent: #e94560;
    --text: #eaeaea;
    /* ... all from design-spec.md */
  }
  ```

- Typography: font families, sizes, weights, and line heights from the design
  spec's type scale.
- Spacing: values from the design spec's spacing scale.
- Motion: easing curves and durations from the design spec's transition vocabulary.

If a value does not exist in the design spec, the creative agent must not invent
it. Either propose an addition to the design spec (marked `[proposed]` in the
artifact) or use the closest existing value.

### Accessibility baseline

- All images have `alt` attributes.
- Color contrast meets WCAG AA (4.5:1 for body text, 3:1 for large text).
- A `prefers-reduced-motion` media query disables or reduces all animations:

  ```css
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
      scroll-behavior: auto !important;
    }
  }
  ```

- Semantic HTML elements (`<section>`, `<nav>`, `<header>`, `<footer>`, `<main>`).
- Readable without CSS (content order matches visual order).

## Allowed values

- File format: `.html` only.
- Animation: CSS only (`@keyframes`, `transition`, `animation-timeline`,
  `scroll()`, `view()`). No JavaScript.
- Asset formats: `.svg`, `.png`, `.jpg`, `.webp` in `assets/`.
- Font loading: `@font-face` with local files, or system/web-safe fonts.

## Known caveats

- CSS `animation-timeline: scroll()` and `animation-timeline: view()` are
  well-supported in Chromium and Firefox but may have partial Safari support.
  Visual artifacts should degrade gracefully — content must be readable and
  usable without scroll-driven animations. The builder handles cross-browser
  polyfilling if needed.
- Self-contained HTML files can become large for complex sections with many
  embedded styles. If a single file exceeds ~500 lines, consider splitting
  into multiple section files rather than producing one monolithic page.
- Visual artifacts intentionally exclude responsive behavior beyond basic
  viewport meta. The builder implements full responsive design during
  translation. The artifact represents the primary (desktop) viewport unless
  the design spec specifies mobile-first.
- The `file://` rendering constraint means no server-side features (no
  fetch, no dynamic routing, no SSR). This is intentional — the artifact
  is a visual reference, not a running application.
