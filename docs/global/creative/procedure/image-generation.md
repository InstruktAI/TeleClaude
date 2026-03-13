---
id: 'creative/procedure/image-generation'
type: 'procedure'
domain: 'creative'
scope: 'global'
description: 'Generate images from text prompts, edit existing images, and iterate on visual output. Backend-agnostic capability with pluggable implementations.'
---

# Image Generation — Procedure

## Goal

Generate, edit, and iterate on images as part of creative work — mood boards, concept
art, logos, visual artifacts. This procedure is backend-agnostic; specific implementations
live in subdirectories.

## Modes

All implementations support three modes:

1. **Text-to-image** — generate a new image from a text prompt.
2. **Image editing** — modify an existing image guided by a text prompt.
3. **Multi-turn iteration** — generate, review, refine with follow-up prompts.

## When to use

- Creative lifecycle art generation phase (mood boards, hero images, concept art).
- Ad-hoc visual work requested by a human (logos, icons, illustrations).
- Iterating on visual output until approved.

## Steps

1. Determine which implementation is available (see below).
2. Follow the implementation-specific procedure for the chosen mode.
3. Save output to the appropriate directory (typically `todos/{slug}/art/` for lifecycle work).
4. If iterating, use the edit mode with the previous output as input.

## Available implementations

| Implementation | Backend | Procedure |
|---|---|---|
| Nano Banana | Gemini (Google) | `creative/procedure/image-generation/nano-banana` |

## Outputs

- Image file(s) (PNG/JPEG) in the specified output directory.
- JSON metadata on stdout with file path and generation details.

## Recovery

- If the API returns an error, check credentials for the specific backend.
- If the model rejects the prompt (safety filter), rephrase with less ambiguous terms.
- If output quality is poor, try a more specific prompt or adjust parameters.
