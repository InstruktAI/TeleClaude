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
            with file_path.open("rb") as file_obj:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat_id, "caption": message[:DEFAULT_CAPTION_MAX_LENGTH]},
                    files={"document": (file_path.name, file_obj, mime_type or "application/octet-stream")},
                )
        else:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": message[:DEFAULT_MESSAGE_MAX_LENGTH],
                    "disable_web_page_preview": "true",
                },
            )

    payload = response.json()
    if not payload.get("ok"):
        message = payload.get("description") or "telegram api error"
        raise RuntimeError(f"Telegram send failed: {message}")
    result = payload.get("result") or {}
    message_id = result.get("message_id")
    logger.info("telegram dm sent", chat_id=chat_id, with_file=bool(file), message_id=message_id)
    return str(message_id)
