"""Cancel command mixin for the Discord adapter.

Answers the ``/cancel`` slash command on a surface this computer owns by sending the thread's
session CTRL+C, and stays silent on a surface it does not own
(`local/projects/teleclaude/spec/feature/integration/discord-interaction-ownership`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord._runtime import AsyncDiscordCallable
from teleclaude.adapters.discord.session_launcher import LauncherInteractionSource
from teleclaude.config import machine as teleclaude_config
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.inbound.conversation import conversation_entry_ownership
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import KeysCommand

if TYPE_CHECKING:
    from teleclaude.adapters.discord.help_desk_categories import DeskForums

logger = get_logger(__name__)

_ID_FIELD = "id"
_CANCEL_NOT_OWNED_EVENT = "discord_cancel_ignored_foreign"
_NO_TEXT = ""
_CHANNEL_FIELD = "channel"
_PARENT_FIELD = "parent"
_USER_FIELD = "user"
_RESPONSE_FIELD = "response"
_SEND_MESSAGE_FIELD = "send_message"
_SEND_MESSAGE_LABEL = "Discord interaction response.send_message"
_NO_ACTIVE_SESSION_REPLY = "No active session in this thread."
_CANCEL_SENT_REPLY = "Sent CTRL+C"
_CANCEL_KEY = "cancel"


class CancelCommandMixin:
    """Mixin answering the /cancel slash command for DiscordAdapter.

    Required host attributes:
    - _project_category_id: int | None
    - _desk_forums: dict[str, DeskForums]
    - _parse_optional_int(value) -> int | None
    - _is_thread_channel(channel) -> bool
    - _resolve_launcher_interaction_source(interaction) -> LauncherInteractionSource (async; from InfrastructureMixin)
    - _find_session(*, channel_id, thread_id, user_id) -> Session | None (async; from ForumSessionsMixin)
    - _async_callable(fn, *, label) -> AsyncDiscordCallable (from InputHandlersMixin)
    """

    _project_category_id: int | None

    if TYPE_CHECKING:
        _desk_forums: dict[str, DeskForums]

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _is_thread_channel(channel: object) -> bool: ...

        async def _resolve_launcher_interaction_source(self, interaction: object) -> LauncherInteractionSource: ...

        async def _find_session(
            self, *, channel_id: int | None, thread_id: int | None, user_id: str
        ) -> Session | None: ...

        def _async_callable(self, fn: object, *, label: str) -> AsyncDiscordCallable: ...

    async def _owns_cancel_surface(self, interaction: object, channel: object) -> bool:
        """Whether this computer owns the surface a ``/cancel`` came from, decided without any response.

        A thread belongs to the computer whose project category holds its forum, or to the master
        for a help desk forum it registered. A channel that is no thread is a shared surface,
        owned by the computer that owns Discord conversational entry. An unresolvable source is
        owned by no one.
        """
        if not self._is_thread_channel(channel):
            return (await conversation_entry_ownership(InputOrigin.DISCORD)).owned_here
        source = await self._resolve_launcher_interaction_source(interaction)
        if source.forum_id is None:
            return False
        if source.category_id is not None and source.category_id == self._project_category_id:
            return True
        return any(
            source.forum_id in (forums.customer_sessions, forums.escalations) for forums in self._desk_forums.values()
        )

    async def _handle_cancel_slash(self, interaction: object) -> None:
        channel = getattr(interaction, _CHANNEL_FIELD, None)
        if not await self._owns_cancel_surface(interaction, channel):
            logger.info(
                _CANCEL_NOT_OWNED_EVENT,
                interaction_id=self._parse_optional_int(getattr(interaction, _ID_FIELD, None)),
                channel_id=self._parse_optional_int(getattr(channel, _ID_FIELD, None)),
                receiver_computer=teleclaude_config.config.computer.name,
            )
            return
        response = getattr(interaction, _RESPONSE_FIELD, None)
        response_send = getattr(response, _SEND_MESSAGE_FIELD, None)
        if not callable(response_send):
            return
        if not self._is_thread_channel(channel):
            await self._async_callable(response_send, label=_SEND_MESSAGE_LABEL)(
                _NO_ACTIVE_SESSION_REPLY,
                ephemeral=True,
            )
            return

        thread_id = self._parse_optional_int(getattr(channel, _ID_FIELD, None))
        parent = getattr(channel, _PARENT_FIELD, None)
        parent_id = self._parse_optional_int(getattr(parent, _ID_FIELD, None))
        channel_id = parent_id or thread_id

        user_obj = getattr(interaction, _USER_FIELD, None)
        user_id = str(getattr(user_obj, _ID_FIELD, _NO_TEXT)).strip()
        session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
        if session is None:
            await self._async_callable(response_send, label=_SEND_MESSAGE_LABEL)(
                _NO_ACTIVE_SESSION_REPLY,
                ephemeral=True,
            )
            return

        cmd = KeysCommand(session_id=session.session_id, key=_CANCEL_KEY, args=[])
        await self._async_callable(response_send, label=_SEND_MESSAGE_LABEL)(
            _CANCEL_SENT_REPLY,
            ephemeral=True,
        )
        await get_command_service().keys(cmd)
