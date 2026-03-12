---
id: 'creative/policy/visual-constraints'
type: 'policy'
domain: 'creative'
scope: 'global'
description: 'Rules governing visual artifact production: CSS-only animations, design spec fidelity, no external dependencies.'
---

# Visual Constraints — Policy

## Required reads

@~/.teleclaude/docs/creative/spec/visual-artifact.md

## Rules

### Animation

- All motion in visual artifacts must be CSS-only. No JavaScript animations,
  no animation libraries, no `<script>` tags.
- Permitted CSS techniques: `@keyframes`, `transition`, `animation-timeline`,
  `scroll()`, `view()`, CSS `perspective` for parallax.
- Motion that CSS cannot express (physics springs, choreographed sequences,
  gesture-driven animation) must be annotated via `data-motion-*` attributes
  with a CSS approximation rendered in-file.
- Every animation must include a `prefers-reduced-motion` media query that
  disables or significantly reduces the motion.

### Dependencies

- No external resources. No CDN links, no remote fonts, no hotlinked images,
  no third-party stylesheets.
- Fonts: system fonts, web-safe stacks, or `@font-face` with files in `assets/`.
- Images: local files in `assets/` referenced via relative paths.
- The artifact must render when opened via `file://` in a browser with no
  network connection.

### Design system fidelity

- Every color, font family, font size, spacing value, border radius, shadow,
  and easing curve in a visual artifact must trace to the corresponding
  `design-spec.md`.
- Inventing visual values not in the design spec is a contract violation.
  If a needed value does not exist, the agent marks it `[proposed]` in the
  artifact and notes the gap — the human decides whether to add it to the
  design spec.
- CSS custom properties at the top of `<style>` must mirror the design spec
  palette and tokens exactly. This is the fidelity bridge — the builder
  verifies by comparing custom property values to the design spec document.

### Artifact boundaries

- Visual artifacts are references, not production code. Builders translate
  them into the target framework. Artifacts must never be copied verbatim
  into a production codebase.
- One HTML file per logical section or page. Do not produce monolithic
  single-file dumps of an entire multi-section site.
- Maximum guidance: if a single file exceeds ~500 lines, it should be split
  into smaller section files.
- Artifacts carry no application logic, no routing, no state management,
  no API calls, no form handling. They are purely visual.

### Accessibility

- WCAG AA contrast ratios: 4.5:1 for body text, 3:1 for large text and
  UI components.
- Semantic HTML elements for document structure.
- All images carry `alt` attributes.
- Content is readable and navigable without CSS (correct source order).
- `prefers-reduced-motion` respected for all animations (see Animation rules).

### Multi-agent production

- When multiple agents produce competing visual drafts (bake-off), each
  agent works from the same `design-spec.md`. The design spec is the
  shared constraint — variations are in layout, spatial rhythm, and motion
  choreography, not in visual identity.
- Each agent's output goes to a named subfolder: `todos/{slug}/visuals/{agent}/`.
  The human reviews all versions and selects the winner or cherry-picks
  sections across versions.
- The selected artifacts are promoted to `todos/{slug}/visuals/` (top level)
  as the canonical reference for the builder.

## Rationale

- CSS-only animations eliminate JavaScript dependencies, reduce maintenance
  surface, and keep artifacts renderable in any browser without a build step.
- Design spec fidelity prevents creative drift where agents invent random
  colors, fonts, and styles that produce visually incoherent results.
- Self-contained files ensure the artifact format has zero maintenance cost —
  no versioning, no dependency updates, no scaffold to manage.
- The reference-not-production boundary prevents builders from copying
  untested, unaccessible, non-responsive mockup code into production.

## Scope

- Applies to all agents producing visual artifacts in the creative phase.
- Applies to all visual artifact files in `todos/{slug}/visuals/`.

## Enforcement

- Creative machine review step: the human opens artifacts in a browser and
  validates visual fidelity, animation behavior, and design spec compliance.
- Builders must not use visual artifacts as production code. The translation
  step is mandatory.
- Agents violating the no-JavaScript rule or the design spec fidelity rule
  produce invalid artifacts that must be regenerated.

## Exceptions

- If a visual effect is physically impossible in CSS and the design spec
  explicitly requires it (e.g., a WebGL particle system specified in the
  motion vocabulary), the agent may include a minimal `<script>` block with
  an inline comment explaining why CSS is insufficient. This exception
  requires explicit human approval in the design spec document — agents
  must not self-grant JavaScript exceptions.
