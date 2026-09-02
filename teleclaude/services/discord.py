"""Discord delivery helpers.

Note: The Discord REST API for creating DM channels (POST /users/@me/channels)
requires the bot to share a guild with the target user. If the bot and the user
have no common guild, the API will return a 403 error. This is an inherent
Discord platform limitation and cannot be worked around in code.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.config import config

logger = get_logger(__name__)

DISCORD_MAX_MESSAGE_LENGTH = 2000
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_JUMP_URL_BASE = "https://discord.com/channels"
DISCORD_DIRECT_MESSAGE_GUILD_SEGMENT = "@me"
DISCORD_URL_SEGMENT_SEPARATOR = "/"
DISCORD_BACKLINK_LINE_SEPARATOR = "\n"


def _resolve_jump_url_guild_segment(guild_id: int | None, *, is_thread: bool) -> str | None:
    """Resolve a jump URL's guild segment, or ``None`` when no valid segment exists.

    A thread only ever lives in a guild, so an origin that never persisted its
    guild id resolves against the single configured guild. The direct-message
    segment is reserved for a channel-bound origin without a guild, which is how
    this codebase represents a DM-bound session.
    """
    if guild_id is not None:
        return str(guild_id)
    if not is_thread:
        return DISCORD_DIRECT_MESSAGE_GUILD_SEGMENT
    configured_guild_id = config.discord.guild_id
    return str(configured_guild_id) if configured_guild_id is not None else None


def build_discord_jump_url(
    guild_id: int | None,
    channel_or_thread_id: int,
    message_id: str | None = None,
    *,
    is_thread: bool,
) -> str | None:
    """Build the native Discord jump URL for a channel, thread, or message.

    Returns ``None`` when no guild segment resolves, so a thread origin without a
    reachable guild yields a visible miss rather than an unresolvable link.
    """
    guild_segment = _resolve_jump_url_guild_segment(guild_id, is_thread=is_thread)
    if guild_segment is None:
        return None
    segments = [DISCORD_JUMP_URL_BASE, guild_segment, str(channel_or_thread_id)]
    if message_id is not None:
        segments.append(message_id)
    return DISCORD_URL_SEGMENT_SEPARATOR.join(segments)


def render_discord_backlink(body: str, backlink_url: str) -> tuple[str, bool]:
    """Append a backlink within Discord's content limit and report body trimming."""
    backlink = DISCORD_BACKLINK_LINE_SEPARATOR + backlink_url if body else backlink_url
    body_length = DISCORD_MAX_MESSAGE_LENGTH - len(backlink)
    return body[:body_length] + backlink, len(body) > body_length


async def _close_client(client: httpx.AsyncClient) -> None:
    """Close a request-scoped HTTP client safely during shutdown."""
    task = asyncio.current_task()
    task_name = task.get_name() if task is not None else "unknown"
    logger.debug("discord http client close begin", task_name=task_name)
    try:
        await client.aclose()
    except RuntimeError as exc:
        if str(exc) != "Event loop is closed":
            raise
        logger.warning("discord http client close hit closed loop", task_name=task_name)
        return
    logger.debug("discord http client close done", task_name=task_name)


async def send_discord_dm(
    user_id: str,
    content: str,
    file: str | None = None,
    *,
    token_env: str = "DISCORD_BOT_TOKEN",
    timeout_s: float = 10.0,
) -> str:
    """Send a Discord DM to a user by their Discord user ID, optionally with one file attached.

    Steps:
    1. Read bot token from environment.
    2. Create a DM channel with the target user.
    3. Send the message (or the file, with the message as accompanying text) to that channel.
    """
    token = os.getenv(token_env)
    if not token:
        raise ValueError("Missing Discord bot token")

    message = content or ""
    if not message.strip() and not file:
        raise ValueError("Notification content is empty")

    file_path: Path | None = None
    if file:
        file_path = Path(file)
        if not file_path.exists():
            raise FileNotFoundError(file_path)
        if not file_path.is_file():
            raise ValueError(f"Not a file: {file}")

    text = message[:DISCORD_MAX_MESSAGE_LENGTH]
    if len(message) > DISCORD_MAX_MESSAGE_LENGTH:
        logger.warning(
            "discord message truncated",
            original_len=len(message),
            max_len=DISCORD_MAX_MESSAGE_LENGTH,
        )

    auth_header = {"Authorization": f"Bot {token}"}
    json_headers = {**auth_header, "Content-Type": "application/json"}

    task = asyncio.current_task()
    task_name = task.get_name() if task is not None else "unknown"
    logger.debug("discord http client create", task_name=task_name, user_id=user_id, with_file=bool(file))
    client = httpx.AsyncClient(timeout=timeout_s)
    try:
        # Step 1: Create DM channel
        dm_response = await client.post(
            f"{DISCORD_API_BASE}/users/@me/channels",
            json={"recipient_id": user_id},
            headers=json_headers,
        )
        if dm_response.status_code >= 400:
            try:
                detail = dm_response.json().get("message") or dm_response.text[:200]
            except (ValueError, KeyError):
                detail = dm_response.text[:200]
            raise RuntimeError(f"Discord create DM channel failed (HTTP {dm_response.status_code}): {detail}")

        channel_id = dm_response.json()["id"]

        # Step 2: Send message, or the file with the message as accompanying text
        if file_path is not None:
            mime_type, _ = mimetypes.guess_type(file_path.name)
            with file_path.open("rb") as file_obj:
                msg_response = await client.post(
                    f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                    data={"payload_json": json.dumps({"content": text})},
                    files={"files[0]": (file_path.name, file_obj, mime_type or "application/octet-stream")},
                    headers=auth_header,
                )
        else:
            msg_response = await client.post(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                json={"content": text},
                headers=json_headers,
            )
    finally:
        await _close_client(client)

    if msg_response.status_code >= 400:
        try:
            detail = msg_response.json().get("message") or msg_response.text[:200]
        except (ValueError, KeyError):
            detail = msg_response.text[:200]
        raise RuntimeError(f"Discord send message failed (HTTP {msg_response.status_code}): {detail}")

    message_id = str(msg_response.json()["id"])
    logger.info("discord dm sent", user_id=user_id, with_file=bool(file), message_id=message_id)
    return message_id
