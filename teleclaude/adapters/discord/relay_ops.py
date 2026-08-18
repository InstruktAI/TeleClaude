"""Admin-reflection mixin for Discord adapter.

Handles escalation-thread creation, customer-to-admin relay diversion, agent
handback, relay message collection, sanitization, and context compilation —
the Discord-only admin-reflection surface.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionEscalatedPayload
from teleclaude.core.injected_text import (
    InjectedTextSourceFeature,
    PlatformTextLabel,
    TranscriptEntryKind,
    platform_control_text,
)
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.relay_context import compile_relay_context
from teleclaude.events.envelope import EventVisibility
from teleclaude.types.commands import ProcessMessageCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_RELAY_OCCURRENCE_PREFIX = "relay"
_RELAY_OCCURRENCE_SEPARATOR = ":"


def _relay_occurrence_key(session_id: str) -> str:
    """Return the stable acceptance key for one compiled relay handback."""
    return _RELAY_OCCURRENCE_SEPARATOR.join((_RELAY_OCCURRENCE_PREFIX, session_id, uuid4().hex))


class AdminReflectionMixin:
    """Mixin providing the Discord-only admin-reflection surface for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - client: AdapterClient
    - _escalation_channel_id: int | None
    - _require_async_callable(fn, *, label) -> Callable
    - _get_channel(channel_id) -> object | None (async)
    - _is_forum_channel(channel) -> bool
    - _create_forum_thread(forum_channel, *, title, content) -> tuple[int, str] (async)
    """

    _client: object
    client: AdapterClient
    _escalation_channel_id: int | None
    _require_async_callable: Callable[..., AsyncDiscordCallable]
    _get_channel: Callable[[int], Awaitable[object | None]]

    if TYPE_CHECKING:

        @staticmethod
        def _is_forum_channel(channel: object) -> bool: ...

        async def _create_forum_thread(
            self, forum_channel: object, *, title: str, content: str = ...
        ) -> tuple[int, str]: ...

    async def create_escalation_thread(self, **kwargs: str | None) -> int:
        """Create a thread in the escalation forum channel for admin relay."""
        customer_name = str(kwargs.get("customer_name") or "")
        reason = str(kwargs.get("reason") or "")
        context_summary = kwargs.get("context_summary")
        session_id = str(kwargs.get("session_id") or "")
        escalation_channel_id = self._escalation_channel_id
        if not escalation_channel_id:
            raise AdapterError("escalation_channel_id not configured")

        forum = await self._get_channel(escalation_channel_id)
        if forum is None:
            raise AdapterError(f"Escalation channel {escalation_channel_id} not found")
        if not self._is_forum_channel(forum):
            raise AdapterError(f"Escalation channel {escalation_channel_id} is not a Forum Channel")

        body = f"**Reason:** {reason}"
        if context_summary:
            body += f"\n\n**Context:** {context_summary}"
        body += f"\n\n*Session: {session_id}*"

        thread_id, _topper_message_id = await self._create_forum_thread(forum, title=customer_name, content=body)
        return thread_id

    async def forward_to_relay_thread(self, session: Session, text: str, message: object) -> None:
        """Public wrapper for forwarding customer traffic into relay threads."""
        await self._forward_to_relay_thread(session, text, message)

    async def handle_relay_thread_message(self, message: object, text: str) -> None:
        """Public wrapper for admin relay-thread traffic handling."""
        await self._handle_relay_thread_message(message, text)

    # =========================================================================
    # Relay Forward / Receive
    # =========================================================================

    async def _forward_to_relay_thread(self, session: Session, text: str, message: object) -> None:
        """Forward a customer message to the relay Discord thread (relay diversion)."""
        relay_channel_id = session.relay_channel_id
        if not relay_channel_id:
            return
        recoverable_errors = recoverable_operation_errors(getattr(self, "_discord", None))
        try:
            thread = await self._get_channel(int(relay_channel_id))
            if thread is None:
                logger.error("Relay thread %s not found", relay_channel_id)
                return

            author = getattr(message, "author", None)
            name = getattr(author, "display_name", None) or "Customer"
            origin = session.last_input_origin or "discord"

            send_fn = cast_async_callable(
                self._require_async_callable,
                getattr(thread, "send", None),
                label="relay thread send",
            )
            await send_fn(f"**{name}** ({origin}): {text}")
        except recoverable_errors:
            logger.warning("Failed to forward message to relay thread %s", relay_channel_id)

    async def _handle_relay_thread_message(self, message: object, text: str) -> None:
        """Handle an admin message in a relay thread — forward to customer or handback."""
        channel = getattr(message, "channel", None)
        thread_id = str(getattr(channel, "id", ""))

        session = await db.get_session_by_field("relay_channel_id", thread_id)
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
        metadata = MessageMetadata()
        recoverable_errors = recoverable_operation_errors(getattr(self, "_discord", None))
        try:
            await self.client.send_message(session=session, text=text, metadata=metadata, ephemeral=False)
        except recoverable_errors:
            logger.warning("Failed to deliver relay message to customer session %s", session.session_id)

    def _is_agent_tag(self, text: str) -> bool:
        """Check if a message contains an @agent handback tag."""
        if "@agent" in text.lower():
            return True
        if self._client and getattr(self._client, "user", None):
            bot_id = getattr(getattr(self._client, "user", None), "id", None)
            if bot_id and f"<@{bot_id}>" in text:
                return True
        return False

    async def _handle_agent_handback(self, session: Session, _text: str, thread_id: str) -> None:
        """Collect relay messages and inject context back into the AI session."""
        messages = await self._collect_relay_messages(thread_id, session.relay_started_at)
        context_block = platform_control_text(PlatformTextLabel.NOTIFICATION, compile_relay_context(messages))
        occurrence_key = _relay_occurrence_key(session.session_id)

        # Inject context through the normal inbound pipeline: session-liveness
        # validation, dedupe, and durable queueing.
        await get_command_service().process_message(
            ProcessMessageCommand(
                session_id=session.session_id,
                text=context_block,
                origin=InputOrigin.DISCORD.value,
                text_kind=TranscriptEntryKind.PLATFORM_CONTROL,
                source_feature=InjectedTextSourceFeature.RELAY,
                occurrence_key=occurrence_key,
                source_message_id=occurrence_key,
            )
        )

        # Clear relay state and restore active lifecycle
        await db.update_session(
            session.session_id,
            relay_status=None,
            relay_channel_id=None,
            relay_started_at=None,
            lifecycle_status="active",
        )

        event_bus.emit(
            "session.escalation_ended",  # type: ignore[arg-type]
            SessionEscalatedPayload(session_id=session.session_id),
            visibility=EventVisibility.CLUSTER,
        )

        logger.info("Agent handback completed for session %s (thread %s)", session.session_id, thread_id)

    # =========================================================================
    # Relay Message Collection
    # =========================================================================

    _FORWARDING_PATTERN: str = r"^\*\*(.+?)\*\* \((\w+)\): (.+)"

    async def _collect_relay_messages(self, thread_id: str, since: datetime | None) -> list[dict[str, str]]:
        """Read all messages from a relay thread since the given timestamp."""
        thread = await self._get_channel(int(thread_id))
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
