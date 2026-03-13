---
id: 'creative/procedure/image-generation'
type: 'procedure'
domain: 'creative'
scope: 'global'
description: 'Generate images using the Nano Banana helper. Text-to-image, image editing, and multi-turn iteration via Gemini.'
---

# Image Generation — Procedure

## Goal

Generate images using the Nano Banana helper script. Supports text-to-image generation,
image-to-image editing, and multi-turn iteration via Gemini's native image generation.

## Preconditions

1. `GOOGLE_API_KEY` environment variable is set (or custom env var via `--api-key-env`).
2. The Nano Banana helper script is available at `~/.teleclaude/scripts/helpers/nano_banana_helper.py`.

## Steps

### Text-to-image generation

Generate a new image from a text prompt:

```bash
~/.teleclaude/scripts/helpers/nano_banana_helper.py generate \
  --prompt "A futuristic cityscape at sunset with neon lights" \
  --aspect-ratio 16:9 \
  --output-dir todos/{slug}/art/ \
  --output-name hero-mood
```

### Image editing (image-to-image)

Edit an existing image with a text prompt:

```bash
~/.teleclaude/scripts/helpers/nano_banana_helper.py edit \
  --prompt "Add more vibrant colors and a warmer palette" \
  --input-image todos/{slug}/art/hero-mood.png \
  --output-dir todos/{slug}/art/ \
  --output-name hero-mood-v2
```

### Multi-turn iteration

Generate an image and then iterate on it with follow-up prompts:

```bash
~/.teleclaude/scripts/helpers/nano_banana_helper.py iterate \
  --prompt "A minimalist logo with geometric shapes" \
  --output-dir todos/{slug}/art/

# Then iterate with feedback:
~/.teleclaude/scripts/helpers/nano_banana_helper.py edit \
  --prompt "Make the shapes more angular and use a darker palette" \
  --input-image todos/{slug}/art/logo.png \
  --output-dir todos/{slug}/art/ \
  --output-name logo-v2
```

### Options

| Option | Default | Description |
|---|---|---|
| `--prompt` | (required for generate) | Text prompt for image generation |
| `--model` | `gemini-2.0-flash-exp` | Gemini model with image generation support |
| `--aspect-ratio` | `1:1` | Options: `1:1`, `3:4`, `4:3`, `9:16`, `16:9` |
| `--input-image` | (none) | Path to input image for edit mode |
| `--output-dir` | workspace dir | Directory to save generated images |
| `--output-name` | auto-generated | Output filename (without extension) |
| `--api-key-env` | `GOOGLE_API_KEY` | Environment variable name for API key |

## Outputs

- PNG image file(s) saved to the specified output directory.
- JSON metadata printed to stdout with file path and generation details.

## Recovery

1. If the API returns an error, check that the `GOOGLE_API_KEY` is valid.
2. If the model rejects the prompt (safety filter), rephrase with less ambiguous terms.
3. If the output quality is poor, try a more specific prompt or a different aspect ratio.
4. Logs are written to `~/.claude/logs/nano_banana_helper.log`.
