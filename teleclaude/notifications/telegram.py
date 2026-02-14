"""Telegram delivery helpers for notification outbox entries."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

import httpx
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

DEFAULT_MESSAGE_MAX_LENGTH = 4000
DEFAULT_CAPTION_MAX_LENGTH = 1024


async def send_telegram_dm(
    chat_id: str,
    content: str,
    file: str | None = None,
    *,
    token_env: str = "TELEGRAM_BOT_TOKEN",
    timeout_s: float = 10.0,
) -> str:
    """Send a Telegram message or document directly by chat_id."""
    token = os.getenv(token_env)
    if not token:
        raise ValueError("Missing Telegram bot token")

    message = content or ""
    if not message.strip() and not file:
        raise ValueError("Notification content is empty")

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        if file:
            file_path = Path(file)
            if not file_path.exists():
                raise FileNotFoundError(file_path)
            if not file_path.is_file():
                raise ValueError(f"Not a file: {file}")

            mime_type, _ = mimetypes.guess_type(file_path.name)
            caption = message[:DEFAULT_CAPTION_MAX_LENGTH]
            if len(message) > DEFAULT_CAPTION_MAX_LENGTH:
                logger.warning("caption truncated", original_len=len(message), max_len=DEFAULT_CAPTION_MAX_LENGTH)
            with file_path.open("rb") as file_obj:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"document": (file_path.name, file_obj, mime_type or "application/octet-stream")},
                )
        else:
            text = message[:DEFAULT_MESSAGE_MAX_LENGTH]
            if len(message) > DEFAULT_MESSAGE_MAX_LENGTH:
                logger.warning("message truncated", original_len=len(message), max_len=DEFAULT_MESSAGE_MAX_LENGTH)
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": "true",
                },
            )

    if response.status_code >= 400:
        try:
            payload = response.json()
            detail = payload.get("description") or response.text[:200]
        except Exception:
            detail = response.text[:200]
        raise RuntimeError(f"Telegram send failed (HTTP {response.status_code}): {detail}")

    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"Telegram returned non-JSON (HTTP {response.status_code}): {response.text[:200]}") from exc

    if not payload.get("ok"):
        detail = payload.get("description") or "telegram api error"
        raise RuntimeError(f"Telegram send failed: {detail}")
    result = payload.get("result") or {}
    message_id = result.get("message_id")
    logger.info("telegram dm sent", chat_id=chat_id, with_file=bool(file), message_id=message_id)
    return str(message_id)
