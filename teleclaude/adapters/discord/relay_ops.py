"""Relay operations mixin for Discord adapter.

Handles customer-to-admin relay diversion, agent handback, relay message
collection, sanitization, and context compilation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db

if TYPE_CHECKING:
    from datetime import datetime

    from teleclaude.core.models import Session

logger = get_logger(__name__)


class RelayOperationsMixin:
    """Mixin providing relay thread operations for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - client: AdapterClient
    - _require_async_callable(fn, *, label) -> Callable
    - _get_channel(channel_id) -> object | None (async)
    """

    if TYPE_CHECKING:
        _client: object

        from teleclaude.core.adapter_client import AdapterClient

        client: AdapterClient

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        async def _get_channel(self, channel_id: int) -> object | None: ...

    # =========================================================================
    # Relay Forward / Receive
    # =========================================================================

    async def _forward_to_relay_thread(self, session: Session, text: str, message: object) -> None:
        """Forward a customer message to the relay Discord thread (relay diversion)."""
        relay_channel_id = session.relay_discord_channel_id
        if not relay_channel_id:
            return
        try:
            thread = await self._get_channel(int(relay_channel_id))  # type: ignore[attr-defined]
            if thread is None:
                logger.error("Relay thread %s not found", relay_channel_id)
                return

            author = getattr(message, "author", None)
            name = getattr(author, "display_name", None) or "Customer"
            origin = session.last_input_origin or "discord"

            send_fn = self._require_async_callable(getattr(thread, "send", None), label="relay thread send")  # type: ignore[attr-defined]
            await send_fn(f"**{name}** ({origin}): {text}")
        except Exception:
            logger.warning("Failed to forward message to relay thread %s", relay_channel_id)

    async def _handle_relay_thread_message(self, message: object, text: str) -> None:
        """Handle an admin message in a relay thread — forward to customer or handback."""
        channel = getattr(message, "channel", None)
        thread_id = str(getattr(channel, "id", ""))

        session = await db.get_session_by_field("relay_discord_channel_id", thread_id)
        if not session:
            return  # Orphaned thread or relay already closed

        if self._is_agent_tag(text):
            await self._handle_agent_handback(session, text, thread_id)
            return

        # Forward admin message to customer via their originating adapter
        author = getattr(message, "author", None)
        admin_name = getattr(author, "display_name", None) or "Admin"
        await self._deliver_to_customer(session, f"{admin_name}: {text}")

    async def _deliver_to_customer(self, session: Session, text: str) -> None:
        """Deliver a message to the customer via all UI adapters."""
        from teleclaude.core.models import MessageMetadata

        metadata = MessageMetadata()
        try:
            await self.client.send_message(session=session, text=text, metadata=metadata, ephemeral=False)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("Failed to deliver relay message to customer session %s", session.session_id)

    def _is_agent_tag(self, text: str) -> bool:
        """Check if a message contains an @agent handback tag."""
        if "@agent" in text.lower():
            return True
        if self._client and getattr(self._client, "user", None):  # type: ignore[attr-defined]
            bot_id = getattr(getattr(self._client, "user", None), "id", None)  # type: ignore[attr-defined]
            if bot_id and f"<@{bot_id}>" in text:
                return True
        return False

    async def _handle_agent_handback(self, session: Session, _text: str, thread_id: str) -> None:
        """Collect relay messages and inject context back into the AI session."""
        messages = await self._collect_relay_messages(thread_id, session.relay_started_at)
        context_block = self._compile_relay_context(messages)

        # Inject context into the AI session's tmux
        from teleclaude.core.tmux_bridge import send_keys_existing_tmux

        await send_keys_existing_tmux(session.tmux_session_name, context_block, send_enter=True)

        # Clear relay state
        await db.update_session(
            session.session_id,
            relay_status=None,
            relay_discord_channel_id=None,
            relay_started_at=None,
        )

        logger.info("Agent handback completed for session %s (thread %s)", session.session_id, thread_id)

    # =========================================================================
    # Relay Message Collection
    # =========================================================================

    _FORWARDING_PATTERN: str = r"^\*\*(.+?)\*\* \((\w+)\): (.+)"

    async def _collect_relay_messages(self, thread_id: str, since: datetime | None) -> list[dict[str, str]]:
        """Read all messages from a relay thread since the given timestamp."""
        import re

        thread = await self._get_channel(int(thread_id))  # type: ignore[attr-defined]
        if not thread:
            return []

        history_fn = getattr(thread, "history", None)
        if not callable(history_fn):
            return []

        messages: list[dict[str, str]] = []
        history_iter = cast(AsyncIterator[object], history_fn(after=since, limit=200))
        async for msg in history_iter:
            content = getattr(msg, "content", "") or ""
            author = getattr(msg, "author", None)
            is_bot = bool(getattr(author, "bot", False))

            if is_bot:
                # Bot-forwarded customer message: **Name** (platform): text
                match = re.match(self._FORWARDING_PATTERN, content, re.DOTALL)
                if match:
                    messages.append(
                        {
                            "role": "Customer",
                            "name": match.group(1),
                            "content": match.group(3),
                        }
                    )
                # Non-matching bot messages (system/notifications) are skipped
                continue

            # Non-bot messages in the relay thread are from admins
            name = getattr(author, "display_name", None) or "Unknown"
            messages.append(
                {
                    "role": "Admin",
                    "name": name,
                    "content": content,
                }
            )
        return messages

    @staticmethod
    def _sanitize_relay_text(text: str) -> str:
        """Strip control characters and ANSI escape sequences from relay text."""
        import re

        # Remove ANSI escape sequences
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        # Remove other control characters (keep newlines and tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        return text

    @staticmethod
    def _compile_relay_context(messages: list[dict[str, str]]) -> str:
        """Compile relay messages into a context block for AI injection."""
        lines = [
            "[Admin Relay Conversation]",
            "The admin spoke directly with the customer. Here is the full exchange:",
            "",
        ]
        for msg in messages:
            content = RelayOperationsMixin._sanitize_relay_text(msg["content"])
            lines.append(f"{msg['role']} ({msg['name']}): {content}")

        lines.extend(
            [
                "",
                "The admin has handed the conversation back to you. Continue naturally,",
                "acknowledging what was discussed.",
            ]
        )
        return "\n".join(lines)
