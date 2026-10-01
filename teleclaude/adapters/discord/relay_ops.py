"""Admin-reflection mixin for Discord adapter.

The shared escalation forum's thread transport: opening a platform desk
escalation's thread, posting the visitor's messages into it, and handing each
admin post in it to the core relay (`teleclaude.core.help_desk_relay`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
from teleclaude.core.db import db
from teleclaude.core.help_desk_relay import answer_in_thread
from teleclaude.types.discord_thread_claims import DiscordThreadClaimKind, DiscordThreadClaimLifecycle

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_AGENT_TAG = "@agent"
_RELAY_CHANNEL_ID_FIELD = "relay_channel_id"
_SEND_ATTR = "send"
_THREAD_SEND_LABEL = "relay thread send"
_CHANNEL_ATTR = "channel"
_ID_ATTR = "id"
_AUTHOR_ATTR = "author"
_DISPLAY_NAME_ATTR = "display_name"
_USER_ATTR = "user"
_NO_TEXT = ""
_MENTION_TEMPLATE = "<@{user_id}>"
_ADMIN_FALLBACK_NAME = "Admin"
_REASON_TEMPLATE = "**Reason:** {reason}"
_CONTEXT_TEMPLATE = "\n\n**Context:** {summary}"
_SESSION_FOOTER_TEMPLATE = "\n\n*Session: {session_id}*"
_THREAD_POST_TEMPLATE = "**{name}**: {text}"
_THREAD_NOT_FOUND_EVENT = "escalation_thread_not_found"
_THREAD_FORWARD_FAILED_EVENT = "escalation_thread_forward_failed"


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

        async def _observe_discord_shared_thread(
            self,
            *,
            thread_id: int,
            parent_id: int,
            kind: DiscordThreadClaimKind,
            local_identity: str,
            lifecycle: DiscordThreadClaimLifecycle,
        ) -> None: ...

        async def _claim_discord_shared_thread(
            self,
            *,
            thread_id: int,
            parent_id: int,
            kind: DiscordThreadClaimKind,
            local_identity: str,
            lifecycle: DiscordThreadClaimLifecycle,
        ) -> bool: ...

    async def create_escalation_thread(
        self, *, customer_name: str, reason: str, context_summary: str, session_id: str
    ) -> int:
        """Create a thread in the escalation forum channel for a platform desk escalation."""
        escalation_channel_id = self._escalation_channel_id
        if not escalation_channel_id:
            raise AdapterError("escalation_channel_id not configured")

        forum = await self._get_channel(escalation_channel_id)
        if forum is None:
            raise AdapterError(f"Escalation channel {escalation_channel_id} not found")
        if not self._is_forum_channel(forum):
            raise AdapterError(f"Escalation channel {escalation_channel_id} is not a Forum Channel")

        body = _REASON_TEMPLATE.format(reason=reason)
        if context_summary:
            body += _CONTEXT_TEMPLATE.format(summary=context_summary)
        body += _SESSION_FOOTER_TEMPLATE.format(session_id=session_id)

        thread_id, _topper_message_id = await self._create_forum_thread(forum, title=customer_name, content=body)
        await self._observe_discord_shared_thread(
            thread_id=thread_id,
            parent_id=escalation_channel_id,
            kind=DiscordThreadClaimKind.ESCALATION_RELAY,
            local_identity=session_id,
            lifecycle=DiscordThreadClaimLifecycle.PENDING,
        )
        if not await self._claim_discord_shared_thread(
            thread_id=thread_id,
            parent_id=escalation_channel_id,
            kind=DiscordThreadClaimKind.ESCALATION_RELAY,
            local_identity=session_id,
            lifecycle=DiscordThreadClaimLifecycle.PENDING,
        ):
            raise AdapterError("shared escalation thread claim was not accepted")
        return thread_id

    async def forward_to_escalation_thread(self, thread_id: str, sender_label: str, text: str) -> None:
        """Post one visitor message into an escalation thread."""
        recoverable_errors = recoverable_operation_errors(getattr(self, "_discord", None))
        try:
            thread = await self._get_channel(int(thread_id))
            if thread is None:
                logger.error(_THREAD_NOT_FOUND_EVENT, thread_id=thread_id)
                raise AdapterError(_THREAD_NOT_FOUND_EVENT)
            send_fn = cast_async_callable(
                self._require_async_callable, getattr(thread, _SEND_ATTR, None), label=_THREAD_SEND_LABEL
            )
            await send_fn(_THREAD_POST_TEMPLATE.format(name=sender_label, text=text))
        except recoverable_errors as exc:
            raise AdapterError(_THREAD_FORWARD_FAILED_EVENT) from exc

    async def handle_relay_thread_message(self, message: object, text: str) -> None:
        """Public wrapper for admin escalation-thread traffic handling."""
        await self._handle_relay_thread_message(message, text)

    async def _handle_relay_thread_message(self, message: object, text: str) -> None:
        """Hand an admin post in an escalation thread to the core relay; any post answers."""
        channel = getattr(message, _CHANNEL_ATTR, None)
        thread_id = str(getattr(channel, _ID_ATTR, None) or _NO_TEXT)
        session = await db.get_session_by_field(_RELAY_CHANNEL_ID_FIELD, thread_id, include_initializing=True)
        if not session:
            return  # Orphaned thread, a relay already closed, or a session on another computer
        author = getattr(message, _AUTHOR_ATTR, None)
        admin_name = getattr(author, _DISPLAY_NAME_ATTR, None) or _ADMIN_FALLBACK_NAME
        await answer_in_thread(session, admin_name, text, self._is_agent_tag(text))

    def _is_agent_tag(self, text: str) -> bool:
        """Whether a post tags the agent: the literal tag or a mention of this bot."""
        if _AGENT_TAG in text.lower():
            return True
        bot_id = getattr(getattr(self._client, _USER_ATTR, None), _ID_ATTR, None) if self._client else None
        return bool(bot_id) and _MENTION_TEMPLATE.format(user_id=bot_id) in text
