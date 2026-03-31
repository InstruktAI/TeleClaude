"""WhatsApp Cloud API delivery helpers.

Note: WhatsApp Cloud API enforces a 24-hour messaging window for non-template
messages. If the window has closed (no outbound/inbound contact in the last 24h),
the API will return an error. The delivery adapter handles this gracefully by
catching exceptions and logging them.
"""

from __future__ import annotations

import asyncio

import httpx
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

WHATSAPP_MAX_MESSAGE_LENGTH = 4096


async def _close_client(client: httpx.AsyncClient) -> None:
    """Close a request-scoped HTTP client safely during shutdown."""
    task = asyncio.current_task()
    task_name = task.get_name() if task is not None else "unknown"
    logger.debug("whatsapp http client close begin", task_name=task_name)
    try:
        await client.aclose()
    except RuntimeError as exc:
        if str(exc) != "Event loop is closed":
            raise
        logger.warning("whatsapp http client close hit closed loop", task_name=task_name)
        return
    logger.debug("whatsapp http client close done", task_name=task_name)


async def send_whatsapp_message(  # pylint: disable=too-many-arguments,too-many-locals
    phone_number: str,
    content: str,
    *,
    phone_number_id: str,
    access_token: str,
    api_version: str = "v21.0",
    timeout_s: float = 10.0,
) -> str:
    """Send a WhatsApp text message via the WhatsApp Cloud API."""
    if not phone_number or not phone_number.strip():
        raise ValueError("phone_number is required")
    if not content or not content.strip():
        raise ValueError("Notification content is empty")
    if not phone_number_id or not phone_number_id.strip():
        raise ValueError("phone_number_id is required")
    if not access_token or not access_token.strip():
        raise ValueError("access_token is required")

    text = content[:WHATSAPP_MAX_MESSAGE_LENGTH]
    if len(content) > WHATSAPP_MAX_MESSAGE_LENGTH:
        logger.warning(
            "whatsapp message truncated",
            original_len=len(content),
            max_len=WHATSAPP_MAX_MESSAGE_LENGTH,
        )

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": text},
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    task = asyncio.current_task()
    task_name = task.get_name() if task is not None else "unknown"
    logger.debug("whatsapp http client create", task_name=task_name, phone_number=phone_number)
    client = httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.post(url, json=payload, headers=headers)
    finally:
        await _close_client(client)

    if response.status_code >= 400:
        try:
            body = response.json()
            detail = body.get("error", {}).get("message") or response.text[:200]
        except (ValueError, KeyError):
            detail = response.text[:200]
        raise RuntimeError(f"WhatsApp send failed (HTTP {response.status_code}): {detail}")

    message_id = str(response.json()["messages"][0]["id"])
    logger.info("whatsapp message sent", phone_number=phone_number, message_id=message_id)
    return message_id
