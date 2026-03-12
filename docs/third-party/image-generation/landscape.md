# Image Generation API Landscape

## Purpose

Reference for the image-generator meta-skill and artist agent. Maps available engines
by capability, cost, and API surface. All engines are REST-only — no SDKs.

## Engine Matrix

### Tier 1 — Primary engines

| Engine | API Base | Auth | Strength | Cost/image |
|---|---|---|---|---|
| Gemini (Nano Banana) | `generativelanguage.googleapis.com/v1beta` | `x-goog-api-key` header | Native multimodal (text+image in/out), iterative dialogue | ~$0.039 (flash), ~$0.134 (pro) |
| GPT Image 1.5 | `api.openai.com/v1/images` | Bearer token | Best instruction following, inpainting, transparency, up to 16 input images | $0.009–$0.133 (quality tiers) |
| Grok | `api.x.ai/v1/images` | Bearer token | Fast, cheap, image-to-image editing with up to 3 source images | $0.02 (standard), $0.07 (pro) |
| FLUX.2 Pro | `api.bfl.ai` | API key | Top photorealism (LM Arena top 5), wide aspect ratios | $0.03–$0.04 |

### Tier 2 — Specialist engines

| Engine | API Base | Auth | Strength | Cost/image |
|---|---|---|---|---|
| Recraft V4 | `api.recraft.ai` | API key | Only API with native SVG/vector output. Illustration styles, icon design, style learning. | $0.04 (raster), $0.08 (vector), $0.25 (pro) |
| Ideogram 3.0 | `api.ideogram.ai` | API key | Best text rendering in images — signage, logos, typography, character consistency | $0.03–$0.09 |
| Imagen 4 | `generativelanguage.googleapis.com/v1beta` | `x-goog-api-key` header | Google production model, strong photorealism + illustration, safety filtering | $0.02–$0.06 |

### Tier 3 — Fast/cheap

| Engine | Access | Strength | Cost/image |
|---|---|---|---|
| FLUX.2 Klein | `api.bfl.ai` or fal.ai | Sub-second generation, concept sketches | $0.014 |
| SDXL Lightning | fal.ai or Replicate | Cheapest possible, throwaway bulk ideation | $0.002 |
| HiDream I1 | fal.ai or Fireworks | 17B open-source, good style prompts | $0.01–$0.05 |

### Notable others

| Engine | Access | Strength | Cost/image |
|---|---|---|---|
| Seedream 4.5 | WaveSpeedAI, fal.ai | Fantasy/concept art, distinctive palettes | $0.05–$0.06 |
| Stability SD 3.5 Flash | `api.stability.ai` (v2beta) | Full edit suite (inpaint, outpaint, search-replace) | $0.025 |
| Midjourney | Discord-only (no API) | Not viable for programmatic pipelines | N/A |

## Meta-Skill Routing Logic

The `image-generator` meta-skill selects engine based on creative intent:

| Intent | Engine | Why |
|---|---|---|
| Photorealism | FLUX.2 Pro or GPT Image 1.5 | Top quality on benchmarks |
| Illustration / vector / icon | Recraft V4 | Only native SVG output |
| Text in image (logos, signage) | Ideogram 3.0 | Only reliable text renderer |
| Quick concept draft | FLUX.2 Klein | Sub-second, $0.014 |
| Iterative editing (image-to-image) | Grok or GPT Image 1.5 | Multi-image input, editing endpoints |
| Multimodal dialogue (reference-driven) | Gemini (Nano Banana) | Native text+image in same conversation |
| Mood board / artistic flair | Seedream 4.5 | Fantasy/concept art aesthetic |
| Budget bulk (100+ variations) | SDXL Lightning via fal.ai | $0.002/image |

## API Patterns

### Common request shape (most engines)

```bash
POST {base}/v1/images/generations
Authorization: Bearer {key}
Content-Type: application/json

{
  "model": "{model_id}",
  "prompt": "...",
  "n": 1,
  "size": "1024x1024"
}
```

### Gemini (Nano Banana) — different shape

```bash
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent
x-goog-api-key: {key}
Content-Type: application/json

{
  "contents": [{"parts": [{"text": "Generate an image of..."}]}],
  "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
}
```

Image data returned as inline `image/png` base64 in the response parts.

### Gemini models for image generation

| Model ID | Codename | Tier |
|---|---|---|
| `gemini-2.5-flash-image` | Nano Banana | Standard |
| `gemini-3-pro-image-preview` | Nano Banana Pro | High quality |
| `gemini-3.1-flash-image-preview` | Latest flash | Fast |

### Image editing (img2img)

Most engines support editing via a separate endpoint:

```bash
POST {base}/v1/images/edits
# multipart/form-data with image file(s) + prompt
```

- GPT: up to 16 input images, mask-based inpainting
- Grok: up to 3 input images
- FLUX Kontext: text+image context for editing ($0.04–$0.08)
- Recraft: image-to-image in both raster AND vector

### Aggregator platforms

For engines without direct REST APIs:

- **fal.ai**: 600+ models, 30-50% cheaper than Replicate. Best for SDXL Lightning, HiDream, Seedream.
- **Replicate**: Better docs, ~200 models. Good fallback.
- **WaveSpeedAI**: Exclusive models (Seedream 4.5).

## Constraints

- All responses return base64 or temporary URLs — agent must save to `art/` folder.
- Gemini Nano Banana is native to the Gemini agent — no separate API call needed when running as a Gemini session.
- Midjourney has no API — not viable for automation.
- Imagen 4 via Gemini API is generation-only (no edit endpoint yet).

## Sources

- [BFL FLUX API](https://docs.bfl.ml/)
- [OpenAI Image API](https://platform.openai.com/docs/api-reference/images)
- [xAI Grok Image API](https://docs.x.ai/docs/guides/image-generation)
- [Google Gemini Image Generation](https://ai.google.dev/gemini-api/docs/image-generation)
- [Recraft API](https://www.recraft.ai/docs)
- [Ideogram API](https://developer.ideogram.ai/)
- [fal.ai](https://fal.ai/)
