"""Discord transport for core-owned, desk-local escalation threads."""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
from teleclaude.adapters.discord.help_desk_categories import DeskForums
from teleclaude.core.endpoints import DeskIdentifier
from teleclaude.core.models import DiscordAdapterMetadata, EndpointStamp, Session
from teleclaude.core.protocols import EscalationThread
from teleclaude.services.discord import build_discord_jump_url

logger = get_logger(__name__)

_ESCALATION_FORUM_UNAVAILABLE = "Discord escalation forum unavailable"
_ESCALATION_THREAD_UNAVAILABLE = "Discord escalation thread unavailable"
_ESCALATION_THREAD_CREATE_FAILED = "Discord escalation thread create failed"
_ESCALATION_THREAD_POST_FAILED = "Discord escalation thread post failed"
_ESCALATION_THREAD_LINK_UNAVAILABLE = "Discord escalation thread link unavailable"
_ESCALATION_THREAD_SEND_LABEL = "Discord escalation thread send"
_MESSAGE_TEMPLATE = "**{sender}**: {text}"
_DISCORD_ORIGIN = "discord"


class EscalationThreadsMixin:
    """Implement the escalation thread capability using the desk forum registry."""

    _discord: ModuleType
    _desk_forums: dict[str, DeskForums]

    if TYPE_CHECKING:

        async def _get_channel(self, channel_id: int) -> object | None: ...

        @staticmethod
        def _is_forum_channel(channel: object) -> bool: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> AsyncDiscordCallable: ...

        async def _create_forum_thread(
            self,
            forum_channel: object,
            *,
            title: str,
            content: str = ...,
            allowed_mentions: object | None = None,
        ) -> tuple[int, str]: ...

        async def ensure_channel(self, session: Session) -> Session: ...

    async def open_escalation_thread(
        self,
        desk: DeskIdentifier,
        *,
        title: str,
        brief: str,
    ) -> EscalationThread:
        """Open a visitor-named thread in the desk's escalations forum."""
        forums = self._desk_forums.get(desk.render())
        forum_id = forums.escalations if forums is not None else None
        if forum_id is None:
            raise AdapterError(_ESCALATION_FORUM_UNAVAILABLE)
        forum = await self._get_channel(forum_id)
        if forum is None or not self._is_forum_channel(forum):
            raise AdapterError(_ESCALATION_FORUM_UNAVAILABLE)
        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            allowed_mentions = self._discord.AllowedMentions.none()
            thread_id, _starter_message_id = await self._create_forum_thread(
                forum,
                title=title,
                content=brief,
                allowed_mentions=allowed_mentions,
            )
        except AdapterError:
            raise
        except recoverable_errors as exc:
            raise AdapterError(_ESCALATION_THREAD_CREATE_FAILED) from exc
        link = build_discord_jump_url(None, thread_id, is_thread=True)
        if link is None:
            raise AdapterError(_ESCALATION_THREAD_LINK_UNAVAILABLE)
        return EscalationThread(thread_id=str(thread_id), link=link)

    async def post_to_escalation_thread(self, thread_id: str, *, sender: str, text: str) -> None:
        """Post one visitor message or delivery notice in its escalation thread."""
        try:
            numeric_thread_id = int(thread_id)
        except ValueError as exc:
            raise AdapterError(_ESCALATION_THREAD_UNAVAILABLE) from exc
        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            thread = await self._get_channel(numeric_thread_id)
            if thread is None:
                raise AdapterError(_ESCALATION_THREAD_UNAVAILABLE)
            send = cast_async_callable(
                self._require_async_callable,
                getattr(thread, "send", None),
                label=_ESCALATION_THREAD_SEND_LABEL,
            )
            allowed_mentions = self._discord.AllowedMentions.none()
            await send(_MESSAGE_TEMPLATE.format(sender=sender, text=text), allowed_mentions=allowed_mentions)
        except AdapterError:
            raise
        except recoverable_errors as exc:
            raise AdapterError(_ESCALATION_THREAD_POST_FAILED) from exc

    async def session_thread_link(self, session: Session) -> str:
        """Ensure the desk's customer-session mirror exists and return its thread link."""
        stamp = EndpointStamp.from_session(session)
        if stamp is None or not stamp.is_help_desk or stamp.desk_kind is None or stamp.slug is None:
            raise AdapterError(_ESCALATION_THREAD_LINK_UNAVAILABLE)
        forums = self._desk_forums.get(DeskIdentifier(stamp.desk_kind, stamp.slug).render())
        customer_sessions_forum = forums.customer_sessions if forums is not None else None
        if customer_sessions_forum is None:
            raise AdapterError(_ESCALATION_THREAD_LINK_UNAVAILABLE)
        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            refreshed = await self.ensure_channel(session)
        except AdapterError:
            raise
        except recoverable_errors as exc:
            raise AdapterError(_ESCALATION_THREAD_LINK_UNAVAILABLE) from exc
        metadata: DiscordAdapterMetadata = DiscordAdapterMetadata.from_dict(
            refreshed.get_origin_section(_DISCORD_ORIGIN)
        )
        if metadata.channel_id != customer_sessions_forum or metadata.thread_id is None:
            raise AdapterError(_ESCALATION_THREAD_LINK_UNAVAILABLE)
        link = build_discord_jump_url(None, metadata.thread_id, is_thread=True)
        if link is None:
            raise AdapterError(_ESCALATION_THREAD_LINK_UNAVAILABLE)
        return link
