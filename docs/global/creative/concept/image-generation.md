---
id: 'creative/concept/image-generation'
type: 'concept'
domain: 'creative'
scope: 'global'
description: 'Image generation capability — text-to-image, editing, and iteration. Backend-agnostic with pluggable implementations.'
---

# Image Generation — Concept

## What

Image generation is an agent capability for producing and refining visual output —
mood boards, concept art, logos, icons, illustrations. It is backend-agnostic;
specific implementations live as separate procedure docs.

Three modes are universally supported:

1. **Text-to-image** — generate a new image from a text prompt.
2. **Image editing** — modify an existing image guided by a text prompt.
3. **Multi-turn iteration** — generate, review, refine with follow-up prompts.

Available implementations:

| Implementation | Backend | Procedure |
|---|---|---|
| Nano Banana | Gemini (Google) | `creative/procedure/image-generation/nano-banana` |

Use cases:

- Creative lifecycle art generation phase (mood boards, hero images, concept art).
- Ad-hoc visual work requested by a human (logos, icons, illustrations).
- Iterating on visual output until approved.

## Why

Creative work needs visual output. Agents need to discover this capability exists and
find the right implementation without loading implementation-specific details upfront.
The concept doc sits in the progressive baseline for discovery; implementation procedures
carry the step-by-step instructions.

## See Also

- ~/.teleclaude/docs/creative/procedure/image-generation/nano-banana.md
