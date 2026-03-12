# Gemini Image Generation (Nano Banana) — API Reference

## Purpose

Detailed API reference for Gemini's native image generation, codenamed "Nano Banana."
This is the default engine for the artist agent because Gemini is natively multimodal —
it reads images and generates images in the same conversation turn.

## Models

| Codename | Model ID | Tier |
|---|---|---|
| Nano Banana | `gemini-2.5-flash-image` | Fast, good quality |
| Nano Banana 2 | `gemini-3.1-flash-image-preview` | Faster, improved quality, reasoning-guided |
| Nano Banana Pro | `gemini-3-pro-image-preview` | Best quality, advanced reasoning |

## Two API Surfaces

### Google Direct API

**Endpoint:**
```
POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent
```

**Auth:** `x-goog-api-key: $GEMINI_API_KEY` header.

**Text-to-image:**
```bash
curl -s -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent" \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{"parts": [{"text": "A photorealistic portrait of..."}]}],
    "generationConfig": {
      "responseModalities": ["TEXT", "IMAGE"],
      "imageConfig": {"aspectRatio": "1:1", "imageSize": "2K"}
    }
  }'
```

**Image-to-image (editing):**
```bash
curl -s -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image-preview:generateContent" \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{"parts": [
      {"inline_data": {"mime_type": "image/png", "data": "<BASE64>"}},
      {"text": "Change the blue sofa to brown leather. Keep everything else."}
    ]}],
    "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
  }'
```

Up to 14 reference images supported (Nano Banana 2/Pro). Include multiple `inline_data` parts.

**Multi-turn iteration:**
```json
{
  "contents": [
    {"role": "user", "parts": [{"text": "Create an infographic about X"}]},
    {"role": "model", "parts": [{"inline_data": {"mime_type": "image/png", "data": "<PREV>"}}]},
    {"role": "user", "parts": [{"text": "Now change the title to Spanish"}]}
  ]
}
```

**Request parameters:**

| Parameter | Values | Notes |
|---|---|---|
| `responseModalities` | `["TEXT", "IMAGE"]` or `["IMAGE"]` | Image-only skips text |
| `imageConfig.aspectRatio` | `1:1`, `3:2`, `4:3`, `9:16`, `16:9`, `21:9`, etc. | 14 options |
| `imageConfig.imageSize` | `512`, `1K`, `2K`, `4K` | Not on gemini-2.5-flash-image |
| `thinkingConfig.thinkingLevel` | `minimal`, `high` | Reasoning before generating |
| `tools` | `[{"google_search": {}}]` | Web search grounding |

**Response:** Base64-encoded image inline in `candidates[0].content.parts[]`:
```json
{
  "candidates": [{
    "content": {
      "parts": [
        {"text": "Here is the image..."},
        {"inlineData": {"mimeType": "image/png", "data": "<BASE64>"}}
      ]
    }
  }]
}
```

No `seed`, no explicit `num_images`, no `output_format` control. Inpainting via natural
language only (no mask parameter).

### fal.ai Proxy API

Simpler image-focused wrapper. Returns URLs instead of base64. Adds `seed`, `num_images`,
`output_format`, and `safety_tolerance` parameters.

**Endpoints:**

| Model | Text-to-Image | Edit |
|---|---|---|
| Nano Banana | `fal-ai/nano-banana` | `fal-ai/nano-banana/edit` |
| Nano Banana 2 | `fal-ai/nano-banana-2` | `fal-ai/nano-banana-2/edit` |
| Nano Banana Pro | `fal-ai/nano-banana-pro` | `fal-ai/nano-banana-pro/edit` |

**Auth:** `Authorization: Key $FAL_KEY` header.

**Queue-based workflow (recommended):**
```bash
# Submit
curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2" \
  -H "Authorization: Key $FAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "...", "num_images": 1, "seed": 42, "aspect_ratio": "1:1", "resolution": "2K"}'

# Returns: {"request_id": "abc-123"}

# Poll status
curl "https://queue.fal.run/fal-ai/nano-banana-2/requests/abc-123/status" \
  -H "Authorization: Key $FAL_KEY"

# Get result
curl "https://queue.fal.run/fal-ai/nano-banana-2/requests/abc-123/response" \
  -H "Authorization: Key $FAL_KEY"
```

**Edit endpoint:**
```bash
curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2/edit" \
  -H "Authorization: Key $FAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "...", "image_urls": ["https://..."], "resolution": "2K"}'
```

**fal.ai parameters:**

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `prompt` | string | required | Text description |
| `num_images` | int | 1 | Number of outputs |
| `seed` | int | random | Reproducibility |
| `aspect_ratio` | enum | `1:1` | Same options as Google |
| `resolution` | enum | `1K` | `0.5K`, `1K`, `2K`, `4K` |
| `output_format` | enum | `png` | `jpeg`, `png`, `webp` |
| `safety_tolerance` | enum | `4` | `1`-`6` (strict to permissive) |
| `enable_web_search` | bool | false | Nano Banana 2/Pro only |
| `thinking_level` | enum | — | `minimal` or `high` |
| `image_urls` | list | — | Edit endpoint only, up to 14 |

**Response:** Hosted URLs:
```json
{
  "images": [{
    "url": "https://storage.googleapis.com/...",
    "content_type": "image/png",
    "width": 1024,
    "height": 1024
  }]
}
```

## API Surface Comparison

| Feature | Google Direct | fal.ai |
|---|---|---|
| Image return | Base64 inline | Hosted URL |
| `seed` | Not available | Available |
| `num_images` | Not explicit | Available |
| `output_format` | PNG only | jpeg/png/webp |
| Multi-turn conversation | Yes | No |
| Image input format | Base64 only | URL or base64 |
| Safety control | Not available | 1-6 scale |

**Recommendation for the artist agent:** Use Google Direct API when running as a Gemini
session (native multimodal, multi-turn iteration). Use fal.ai when calling from a
non-Gemini agent or when `seed`/`num_images` control is needed.

## Pricing

| Model | Resolution | ~Cost/Image |
|---|---|---|
| Nano Banana | 1K | ~$0.039 |
| Nano Banana 2 | 512 | ~$0.045 |
| Nano Banana 2 | 1K | ~$0.067 |
| Nano Banana 2 | 2K | ~$0.101 |
| Nano Banana 2 | 4K | ~$0.151 |
| Nano Banana Pro | 1K-2K | ~$0.134 |
| Nano Banana Pro | 4K | ~$0.240 |

Batch API gives 50% discount (24-hour processing window).

## Sources

- [Google Gemini API Image Generation](https://ai.google.dev/gemini-api/docs/image-generation)
- [Google Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [fal.ai Nano Banana 2 API](https://fal.ai/models/fal-ai/nano-banana-2/api)
- [fal.ai Nano Banana Pro API](https://fal.ai/models/fal-ai/nano-banana-pro/api)
