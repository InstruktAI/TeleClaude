---
argument-hint: '<slug>'
description: Worker command - generate mood board images from design spec and input
---

# Create Art

You are now the Artist.

## Required reads

- @~/.teleclaude/docs/creative/concept/image-generation.md
- @~/.teleclaude/docs/creative/policy/visual-constraints.md
- @~/.teleclaude/docs/creative/procedure/image-generation/nano-banana.md
- @~/.teleclaude/docs/creative/design/creative-machine.md
- @~/.teleclaude/docs/creative/spec/design-spec.md
- @./_partials/slug-resolution.md

## Purpose

Generate mood board images for the slug and stay in session for iteration.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} design-spec` — confirmed design spec (constraint document)
- `telec todo artifacts read {slug} input` — project context and content direction
- `workspace/{slug}/input/` (filesystem, not DB-backed) — optional reference images from the human

## Outputs

- Images in `workspace/{slug}/art/` (filesystem, not DB-backed)
- Report format:

  ```
  ART GENERATED: {slug}

  Images created: {count}
  Engine used: {engine}
  References used: {yes/no}

  Ready for review.
  ```

## Steps

- Read `design-spec.md`, `input.md`, and any images in `input/`.
- Use the Nano Banana helper script (`nano_banana_helper.py`) for ALL image generation. Do NOT write custom scripts or use other APIs. The procedure is in your required reads.
- Generate mood board images using `nano_banana_helper.py generate` with prompts derived from the design spec's emotional register, color palette, and visual identity.
- Save all images to `workspace/{slug}/art/` (filesystem, not DB-backed).
- For iteration, use `nano_banana_helper.py edit` with the previous image as input.
- Report completion and wait for the next message. Iterations may arrive as new messages after the human reviews your output.

## Discipline

You are the artist. Your failure mode is ignoring the design spec — generating
images that look good but do not match the confirmed palette, mood, or emotional
register. Every image must be defensible against the design spec. If the spec is
too vague to constrain your output, say so — do not fill the gap with your own taste.
