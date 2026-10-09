"""Telegram delivery helpers."""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.services.provider_observation import (
    Provider,
    ProviderOutcome,
    client_cleanup_details,
    new_operation_id,
    observe_provider,
)

logger = get_logger(__name__)

DEFAULT_MESSAGE_MAX_LENGTH = 4000
DEFAULT_CAPTION_MAX_LENGTH = 1024


async def _close_client(client: httpx.AsyncClient) -> bool:
    """Close a request-scoped HTTP client safely during shutdown."""
    task = asyncio.current_task()
    task_name = task.get_name() if task is not None else "unknown"
    logger.debug("telegram http client close begin", task_name=task_name)
    try:
        await client.aclose()
    except RuntimeError as exc:
        if str(exc) != "Event loop is closed":
            raise
        logger.warning("telegram http client close hit closed loop", task_name=task_name)
        return False
    logger.debug("telegram http client close done", task_name=task_name)
    return True


async def send_telegram_dm(
    chat_id: str,
    content: str,
    file: str | None = None,
    timeout_s: float = 10.0,
) -> str:
    """Send a Telegram message or document directly by chat_id."""
    operation_id = new_operation_id()
    observe_provider(Provider.TELEGRAM, ProviderOutcome.ACCEPTED, operation_id)
    terminal_observed = False
    client_cleanup_completed = False
    try:
        token = config.telegram.bot_token
        if not token:
            observe_provider(Provider.TELEGRAM, ProviderOutcome.MISSING_CONFIG, operation_id)
            terminal_observed = True
            raise ValueError("Missing Telegram bot token")

        message = content or ""
        if not message.strip() and not file:
            observe_provider(Provider.TELEGRAM, ProviderOutcome.REJECTED, operation_id, reason="empty_content")
            terminal_observed = True
            raise ValueError("Notification content is empty")

        task = asyncio.current_task()
        task_name = task.get_name() if task is not None else "unknown"
        logger.debug("telegram http client create", task_name=task_name, chat_id=chat_id, with_file=bool(file))
        client = httpx.AsyncClient(timeout=timeout_s)
        try:
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
        finally:
            client_cleanup_completed = await _close_client(client)

        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("description") or response.text[:200]
            except (ValueError, KeyError):
                detail = response.text[:200]
            raise RuntimeError(f"Telegram send failed (HTTP {response.status_code}): {detail}")

        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Telegram returned non-JSON (HTTP {response.status_code}): {response.text[:200]}"
            ) from exc

        if not payload.get("ok"):
            detail = payload.get("description") or "telegram api error"
            raise RuntimeError(f"Telegram send failed: {detail}")
        result = payload.get("result") or {}
        message_id = result.get("message_id")
        logger.info("telegram dm sent", chat_id=chat_id, with_file=bool(file), message_id=message_id)
        observe_provider(
            Provider.TELEGRAM,
            ProviderOutcome.SENT,
            operation_id,
            message_id=str(message_id),
            **client_cleanup_details(client_cleanup_completed),
        )
        terminal_observed = True
        return str(message_id)
    except asyncio.CancelledError:
        if not terminal_observed:
            observe_provider(
                Provider.TELEGRAM,
                ProviderOutcome.REJECTED,
                operation_id,
                **client_cleanup_details(client_cleanup_completed),
            )
        raise
    except Exception:
        if not terminal_observed:
            observe_provider(
                Provider.TELEGRAM,
                ProviderOutcome.REJECTED,
                operation_id,
                **client_cleanup_details(client_cleanup_completed),
            )
        raise
