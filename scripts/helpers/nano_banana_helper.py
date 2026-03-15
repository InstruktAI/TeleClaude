#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "aiohttp",
#     "python-dotenv",
# ]
# ///
"""Nano Banana image generation helper.

Generate images using Gemini's native image generation (Nano Banana).
Supports text-to-image, image-to-image editing, and multi-turn iteration.

Modes:
  generate   Text-to-image generation from a prompt
  edit       Image-to-image editing with a text prompt
  iterate    Alias for edit (multi-turn iteration)

This script is standalone — no teleclaude imports.
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TypedDict

import aiohttp
from dotenv import load_dotenv


class _InlineData(TypedDict):
    mimeType: str
    data: str


class _TextPart(TypedDict):
    text: str


class _InlineDataPart(TypedDict):
    inlineData: _InlineData


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


LOG_DIR = Path("~/.claude/logs").expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "nano_banana_helper.log"

logger = logging.getLogger("nano_banana_helper")
logger.setLevel(logging.DEBUG)

_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_fh)

# Console handler for errors only
_ch = logging.StreamHandler(sys.stderr)
_ch.setLevel(logging.WARNING)
_ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logger.addHandler(_ch)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ASPECT_RATIOS = ("1:1", "3:4", "4:3", "9:16", "16:9")

QUALITY_MODELS = {
    "low": "gemini-2.5-flash-image",
    "medium": "gemini-3.1-flash-image-preview",
    "high": "gemini-3-pro-image-preview",
}

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------


def _build_generate_payload(prompt: str) -> dict:  # type: ignore[type-arg]
    """Build the API request payload for text-to-image generation."""
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
        },
    }


def _build_edit_payload(prompt: str, images_data: list[tuple[str, str]]) -> dict:  # type: ignore[type-arg]
    """Build the API request payload for image-to-image editing.
    images_data is a list of tuples (base64_data, mime_type).
    """
    parts: list[_TextPart | _InlineDataPart] = [_TextPart(text=prompt)]
    for b64, mime in images_data:
        parts.append(_InlineDataPart(inlineData=_InlineData(mimeType=mime, data=b64)))

    return {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
        },
    }


def _detect_mime_type(path: Path) -> str:
    """Detect MIME type from file extension."""
    ext = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    return mime_map.get(ext, "image/png")


async def _call_gemini(
    api_key: str,
    model: str,
    payload: dict,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Call the Gemini generateContent API and return the response."""
    # Ensure model string doesn't have prefix if it was passed in
    clean_model = model.replace("models/", "")
    url = f"{GEMINI_API_BASE}/{clean_model}:generateContent?key={api_key}"
    logger.info("Calling Gemini API: model=%s", clean_model)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                logger.error("Gemini API error body: %s", body)
                raise RuntimeError(f"Gemini API returned {resp.status}: {body[:500]}")
            return json.loads(body)  # type: ignore[no-any-return]


def _extract_image_from_response(response: dict) -> tuple[bytes, str] | None:  # type: ignore[type-arg]
    """Extract the first image from a Gemini generateContent response.

    Returns (image_bytes, mime_type) or None if no image found.
    """
    candidates = response.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData")
            if inline_data and "data" in inline_data:
                mime_type = inline_data.get("mimeType", "image/png")
                image_bytes = base64.b64decode(inline_data["data"])
                return image_bytes, mime_type
    return None


def _extract_text_from_response(response: dict) -> str:  # type: ignore[type-arg]
    """Extract text content from a Gemini generateContent response."""
    candidates = response.get("candidates", [])
    texts = []
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            if "text" in part:
                texts.append(part["text"])
    return "\n".join(texts)


def _mime_to_ext(mime_type: str) -> str:
    """Convert MIME type to file extension."""
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return ext_map.get(mime_type, ".png")


# ---------------------------------------------------------------------------
# Main operations
# ---------------------------------------------------------------------------


async def generate_image(
    prompt: str,
    model: str | None,
    quality: str,
    aspect_ratio: str,
    output_dir: Path,
    output_name: str | None,
    api_key: str,
) -> dict:  # type: ignore[type-arg]
    """Generate an image from a text prompt."""
    target_model = model if model else QUALITY_MODELS.get(quality, QUALITY_MODELS["medium"])
    payload = _build_generate_payload(prompt)

    try:
        response = await _call_gemini(api_key, target_model, payload)
    except Exception as e:
        logger.error("Image generation failed: %s", e)
        return {"success": False, "error": str(e)}

    result = _extract_image_from_response(response)
    if result is None:
        text = _extract_text_from_response(response)
        logger.warning("No image in response. Text: %s", text[:500])
        return {
            "success": False,
            "error": "No image generated",
            "text_response": text,
        }

    image_bytes, mime_type = result
    ext = _mime_to_ext(mime_type)
    name = output_name or f"generated-{uuid.uuid4().hex[:8]}"
    filename = f"{name}{ext}"
    output_path = output_dir / filename

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    logger.info("Image saved: %s (%d bytes)", output_path, len(image_bytes))

    return {
        "success": True,
        "path": str(output_path),
        "filename": filename,
        "size_bytes": len(image_bytes),
        "mime_type": mime_type,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "model_used": target_model,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def edit_image(
    prompt: str,
    input_images: list[Path],
    model: str | None,
    quality: str,
    output_dir: Path,
    output_name: str | None,
    api_key: str,
) -> dict:  # type: ignore[type-arg]
    """Edit an image with a text prompt (image-to-image), supporting multiple input images."""
    target_model = model if model else QUALITY_MODELS.get(quality, QUALITY_MODELS["medium"])

    images_data = []
    for img_path in input_images:
        if not img_path.exists():
            return {"success": False, "error": f"Input image not found: {img_path}"}
        image_b64 = base64.b64encode(img_path.read_bytes()).decode()
        mime_type = _detect_mime_type(img_path)
        images_data.append((image_b64, mime_type))

    payload = _build_edit_payload(prompt, images_data)

    try:
        response = await _call_gemini(api_key, target_model, payload)
    except Exception as e:
        logger.error("Image editing failed: %s", e)
        return {"success": False, "error": str(e)}

    result = _extract_image_from_response(response)
    if result is None:
        text = _extract_text_from_response(response)
        logger.warning("No image in edit response. Text: %s", text[:500])
        return {
            "success": False,
            "error": "No image generated from edit",
            "text_response": text,
        }

    image_bytes, out_mime = result
    ext = _mime_to_ext(out_mime)
    name = output_name or f"edited-{uuid.uuid4().hex[:8]}"
    filename = f"{name}{ext}"
    output_path = output_dir / filename

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    logger.info("Edited image saved: %s (%d bytes)", output_path, len(image_bytes))

    return {
        "success": True,
        "path": str(output_path),
        "filename": filename,
        "size_bytes": len(image_bytes),
        "mime_type": out_mime,
        "prompt": prompt,
        "input_images": [str(p) for p in input_images],
        "quality": quality,
        "model_used": target_model,
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Nano Banana — Gemini image generation helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="mode", help="Operation mode")

    # Generate
    gen = subparsers.add_parser("generate", help="Text-to-image generation")
    gen.add_argument("--prompt", required=True, help="Text prompt for image generation")
    gen.add_argument("--model", default=None, help="Gemini model override")
    gen.add_argument(
        "--quality", choices=["low", "medium", "high"], default="medium", help="Image quality mode (default: medium)"
    )
    gen.add_argument(
        "--aspect-ratio",
        default="1:1",
        choices=VALID_ASPECT_RATIOS,
        help="Aspect ratio (default: 1:1)",
    )
    gen.add_argument("--output-dir", type=Path, help="Output directory")
    gen.add_argument("--output-name", help="Output filename (without extension)")
    gen.add_argument("--api-key-env", default="GOOGLE_API_KEY", help="Env var for API key")

    # Edit
    edit = subparsers.add_parser("edit", help="Image-to-image editing")
    edit.add_argument("--prompt", required=True, help="Text prompt for editing")
    edit.add_argument("--input-image", type=Path, nargs="+", required=True, help="Path to one or more input images")
    edit.add_argument("--model", default=None, help="Gemini model override")
    edit.add_argument(
        "--quality", choices=["low", "medium", "high"], default="medium", help="Image quality mode (default: medium)"
    )
    edit.add_argument("--output-dir", type=Path, help="Output directory")
    edit.add_argument("--output-name", help="Output filename (without extension)")
    edit.add_argument("--api-key-env", default="GOOGLE_API_KEY", help="Env var for API key")

    # Iterate (alias for edit)
    iterate = subparsers.add_parser("iterate", help="Multi-turn iteration (alias for edit)")
    iterate.add_argument("--prompt", required=True, help="Text prompt for iteration")
    iterate.add_argument("--input-image", type=Path, nargs="+", required=True, help="Path to one or more input images")
    iterate.add_argument("--model", default=None, help="Gemini model override")
    iterate.add_argument(
        "--quality", choices=["low", "medium", "high"], default="medium", help="Image quality mode (default: medium)"
    )
    iterate.add_argument("--output-dir", type=Path, help="Output directory")
    iterate.add_argument("--output-name", help="Output filename (without extension)")
    iterate.add_argument("--api-key-env", default="GOOGLE_API_KEY", help="Env var for API key")

    return parser


def _resolve_output_dir(args: argparse.Namespace) -> Path:
    """Resolve the output directory from args or session env."""
    if args.output_dir:
        return args.output_dir  # type: ignore[no-any-return]
    session_id = os.environ.get("TELECLAUDE_SESSION_ID", "default")
    return Path(f"workspace/{session_id}")


def main() -> None:
    # Load .env from current directory to ensure we get project-specific keys
    # instead of relying on global environment variables.
    load_dotenv(override=True)

    parser = _build_parser()
    args = parser.parse_args()

    if not args.mode:
        parser.print_help()
        sys.exit(1)

    # Resolve API key
    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        print(json.dumps({"success": False, "error": f"Missing API key: set {args.api_key_env} or place it in .env"}))
        sys.exit(1)

    output_dir = _resolve_output_dir(args)

    if args.mode == "generate":
        result = asyncio.run(
            generate_image(
                prompt=args.prompt,
                model=args.model,
                quality=args.quality,
                aspect_ratio=args.aspect_ratio,
                output_dir=output_dir,
                output_name=args.output_name,
                api_key=api_key,
            )
        )
    elif args.mode in ("edit", "iterate"):
        result = asyncio.run(
            edit_image(
                prompt=args.prompt,
                input_images=args.input_image,
                model=args.model,
                quality=args.quality,
                output_dir=output_dir,
                output_name=args.output_name,
                api_key=api_key,
            )
        )
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
