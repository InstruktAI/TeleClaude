"""Discord delivery helpers.

Note: The Discord REST API for creating DM channels (POST /users/@me/channels)
requires the bot to share a guild with the target user. If the bot and the user
have no common guild, the API will return a 403 error. This is an inherent
Discord platform limitation and cannot be worked around in code.
"""

from __future__ import annotations

import os

import httpx
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

DISCORD_MAX_MESSAGE_LENGTH = 2000
DISCORD_API_BASE = "https://discord.com/api/v10"


async def send_discord_dm(
    user_id: str,
    content: str,
    *,
    token_env: str = "DISCORD_BOT_TOKEN",
    timeout_s: float = 10.0,
) -> str:
    """Send a Discord DM to a user by their Discord user ID.

    Steps:
    1. Read bot token from environment.
    2. Create a DM channel with the target user.
    3. Send the message to that channel.
    """
    token = os.getenv(token_env)
    if not token:
        raise ValueError("Missing Discord bot token")

    if not content or not content.strip():
        raise ValueError("Notification content is empty")

    text = content[:DISCORD_MAX_MESSAGE_LENGTH]
    if len(content) > DISCORD_MAX_MESSAGE_LENGTH:
        logger.warning(
            "discord message truncated",
            original_len=len(content),
            max_len=DISCORD_MAX_MESSAGE_LENGTH,
        )

    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        # Step 1: Create DM channel
        dm_response = await client.post(
            f"{DISCORD_API_BASE}/users/@me/channels",
            json={"recipient_id": user_id},
            headers=headers,
        )
        if dm_response.status_code >= 400:
            try:
                detail = dm_response.json().get("message") or dm_response.text[:200]
            except Exception:
                detail = dm_response.text[:200]
            raise RuntimeError(f"Discord create DM channel failed (HTTP {dm_response.status_code}): {detail}")

        channel_id = dm_response.json()["id"]

        # Step 2: Send message
        msg_response = await client.post(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            json={"content": text},
            headers=headers,
        )

    if msg_response.status_code >= 400:
        try:
            detail = msg_response.json().get("message") or msg_response.text[:200]
        except Exception:
            detail = msg_response.text[:200]
        raise RuntimeError(f"Discord send message failed (HTTP {msg_response.status_code}): {detail}")

    message_id = str(msg_response.json()["id"])
    logger.info("discord dm sent", user_id=user_id, message_id=message_id)
    return message_id
