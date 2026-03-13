---
name: nano-banana
description: Generate images using Gemini Nano Banana. Text-to-image, image editing, and multi-turn iteration. Use when the user needs AI-generated images, mood boards, visual concepts, or image modifications.
---

# Nano Banana

## Required reads

- @~/.teleclaude/docs/creative/procedure/image-generation.md

## Purpose

Single interface for Gemini image generation via the Nano Banana helper script.

## Scope

- Text-to-image generation from prompts
- Image-to-image editing with text guidance
- Multi-turn iteration for refinement

## Inputs

- **prompt**: text description of the desired image (required for generate)
- **input-image**: path to existing image (required for edit mode)
- **model**: Gemini model (default: `gemini-2.0-flash-exp`)
- **aspect-ratio**: `1:1`, `3:4`, `4:3`, `9:16`, `16:9` (default: `1:1`)
- **output-dir**: where to save generated images
- **output-name**: filename without extension (auto-generated if omitted)

## Outputs

- Image file(s) in the specified output directory
- JSON metadata on stdout with file path and generation details

## Procedure

Follow the image-generation procedure from the required reads. The helper script
handles all API interaction, image decoding, and file saving.
