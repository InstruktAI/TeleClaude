"""Launcher clicks mixin for the Discord adapter.

Decides a launcher click's local ownership, acknowledges it, and starts the chosen agent's session
(`local/projects/teleclaude/spec/feature/integration/discord-interaction-ownership`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord._runtime import AsyncDiscordCallable
from teleclaude.adapters.discord.session_launcher import (
    LauncherAcknowledgementOutcome,
    LauncherAcknowledgementReason,
    LauncherCommandOutcome,
    LauncherCommandReason,
    LauncherComponentGeneration,
    LauncherEvent,
    LauncherInteractionSource,
    LauncherOwnershipOutcome,
    LauncherOwnershipReason,
)
from teleclaude.config import machine as teleclaude_config
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import (
    AgentDispatchMode,
    DiscordMetadataField,
    Session,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

_RESPONSE_FIELD = "response"
_DEFER_FIELD = "defer"
_FOLLOWUP_FIELD = "followup"
_SEND_FIELD = "send"
_USER_FIELD = "user"
_ID_FIELD = "id"
_SESSION_ID_FIELD = "session_id"
_DISCORD_USER_ID_FIELD = "discord_user_id"
_PLATFORM_FIELD = "platform"
_DISCORD_PLATFORM = "discord"
_SLOW_THINKING_MODE = "slow"
_DEFER_LABEL = "Discord interaction response.defer"
_FOLLOWUP_SEND_LABEL = "Discord interaction followup.send"
_STARTING_AGENT_TEMPLATE = "Starting {agent_name}..."
_FAILED_AGENT_TEMPLATE = "Failed to start {agent_name}."
_EMPTY_VALUE = ""


class LauncherClicksMixin:
    """Mixin handling launcher button clicks for DiscordAdapter.

    Required host attributes:
    - _forum_project_map: dict[int, str]
    - _project_category_id: int | None
    - _registered_launcher_message_ids: set[int]
    - _resolve_launcher_interaction_source(interaction) -> LauncherInteractionSource (async; from InfrastructureMixin)
    - ensure_channel(session) -> Session (async; from ChannelOperationsMixin)
    - _discord_errors() -> tuple[type[Exception], ...] (from InputHandlersMixin)
    - _async_callable(fn, *, label) -> AsyncDiscordCallable (from InputHandlersMixin)
    """

    _forum_project_map: dict[int, str]
    _project_category_id: int | None
    _registered_launcher_message_ids: set[int]

    if TYPE_CHECKING:

        async def _resolve_launcher_interaction_source(self, interaction: object) -> LauncherInteractionSource: ...

        async def ensure_channel(self, session: Session) -> Session: ...

        def _discord_errors(self) -> tuple[type[Exception], ...]: ...

        def _async_callable(self, fn: object, *, label: str) -> AsyncDiscordCallable: ...

    async def _handle_launcher_click(
        self,
        interaction: object,
        agent_name: str,
        launcher_forum_id: int,
    ) -> None:
        source = await self._resolve_launcher_interaction_source(interaction)
        project_path = self._forum_project_map.get(source.forum_id) if source.forum_id is not None else None
        logger.info(
            LauncherEvent.RECEIVED,
            generation=LauncherComponentGeneration.CURRENT,
            interaction_id=source.interaction_id,
            message_id=source.message_id,
            thread_id=source.thread_id,
            forum_id=source.forum_id,
            category_id=source.category_id,
            receiver_computer=teleclaude_config.config.computer.name,
            project_path=project_path,
        )

        if source.message_id is None:
            ownership_outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            ownership_reason = LauncherOwnershipReason.MESSAGE_ID_UNRESOLVED
        elif source.forum_id is None:
            ownership_outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            ownership_reason = LauncherOwnershipReason.SOURCE_FORUM_UNRESOLVED
        elif source.category_id is None or self._project_category_id is None:
            ownership_outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            ownership_reason = LauncherOwnershipReason.SOURCE_CATEGORY_UNRESOLVED
        elif source.category_id != self._project_category_id:
            ownership_outcome = LauncherOwnershipOutcome.IGNORED_FOREIGN
            ownership_reason = LauncherOwnershipReason.FOREIGN_PROJECT_CATEGORY
        elif source.forum_id != launcher_forum_id:
            ownership_outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            ownership_reason = LauncherOwnershipReason.BOUND_FORUM_MISMATCH
        elif source.message_id not in self._registered_launcher_message_ids:
            ownership_outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            ownership_reason = LauncherOwnershipReason.MESSAGE_NOT_REGISTERED
        elif project_path is None:
            ownership_outcome = LauncherOwnershipOutcome.OWNERSHIP_UNRESOLVED
            ownership_reason = LauncherOwnershipReason.PROJECT_FORUM_UNMAPPED
        else:
            ownership_outcome = LauncherOwnershipOutcome.ACCEPTED_LOCAL
            ownership_reason = LauncherOwnershipReason.SOURCE_MATCHES_LOCAL_REGISTRATION

        logger.info(
            LauncherEvent.OWNERSHIP_DECIDED,
            outcome=ownership_outcome,
            reason=ownership_reason,
            interaction_id=source.interaction_id,
            message_id=source.message_id,
            thread_id=source.thread_id,
            forum_id=source.forum_id,
            category_id=source.category_id,
            receiver_computer=teleclaude_config.config.computer.name,
            project_path=project_path,
        )
        if ownership_outcome is not LauncherOwnershipOutcome.ACCEPTED_LOCAL or project_path is None:
            return

        response = getattr(interaction, _RESPONSE_FIELD, None)
        response_defer = getattr(response, _DEFER_FIELD, None)
        if not callable(response_defer):
            logger.info(
                LauncherEvent.ACKNOWLEDGEMENT_COMPLETED,
                outcome=LauncherAcknowledgementOutcome.FAILED,
                reason=LauncherAcknowledgementReason.RESPONSE_UNAVAILABLE,
                interaction_id=source.interaction_id,
                message_id=source.message_id,
                thread_id=source.thread_id,
                forum_id=source.forum_id,
                category_id=source.category_id,
                receiver_computer=teleclaude_config.config.computer.name,
                project_path=project_path,
            )
            return
        try:
            await self._async_callable(response_defer, label=_DEFER_LABEL)(ephemeral=True)
        except self._discord_errors() as exc:
            logger.info(
                LauncherEvent.ACKNOWLEDGEMENT_COMPLETED,
                outcome=LauncherAcknowledgementOutcome.FAILED,
                reason=LauncherAcknowledgementReason.PROVIDER_REJECTED,
                interaction_id=source.interaction_id,
                message_id=source.message_id,
                thread_id=source.thread_id,
                forum_id=source.forum_id,
                category_id=source.category_id,
                receiver_computer=teleclaude_config.config.computer.name,
                project_path=project_path,
                error_type=type(exc).__name__,
            )
            return
        logger.info(
            LauncherEvent.ACKNOWLEDGEMENT_COMPLETED,
            outcome=LauncherAcknowledgementOutcome.SUCCESS,
            reason=LauncherAcknowledgementReason.RESPONSE_DEFERRED,
            interaction_id=source.interaction_id,
            message_id=source.message_id,
            thread_id=source.thread_id,
            forum_id=source.forum_id,
            category_id=source.category_id,
            receiver_computer=teleclaude_config.config.computer.name,
            project_path=project_path,
        )

        user_obj = getattr(interaction, _USER_FIELD, None)
        user_id = str(getattr(user_obj, _ID_FIELD, _EMPTY_VALUE)).strip()

        create_cmd = CreateSessionCommand(
            project_path=project_path,
            origin=InputOrigin.DISCORD.value,
            origin_metadata={
                DiscordMetadataField.USER_ID: user_id,
                _DISCORD_USER_ID_FIELD: user_id,
                _PLATFORM_FIELD: _DISCORD_PLATFORM,
            }
            if user_id
            else None,
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                agent=agent_name,
                thinking_mode=_SLOW_THINKING_MODE,
                dispatch_mode=AgentDispatchMode.MANUAL_PREFERENCE,
            ),
            entry_point=SessionEntryPoint.DISCORD,
            command_input_mode=CommandInputMode.INTERACTIVE_SHORTHAND,
        )
        try:
            result = await get_command_service().create_session(create_cmd)
            session_id = str(result.get(_SESSION_ID_FIELD, _EMPTY_VALUE))
            if session_id:
                session = await db.get_session(session_id)
                if session is not None:
                    await self.ensure_channel(session)
        except Exception as exc:
            logger.info(
                LauncherEvent.COMMAND_COMPLETED,
                outcome=LauncherCommandOutcome.FAILED,
                reason=LauncherCommandReason.COMMAND_FAILED,
                interaction_id=source.interaction_id,
                message_id=source.message_id,
                thread_id=source.thread_id,
                forum_id=source.forum_id,
                category_id=source.category_id,
                receiver_computer=teleclaude_config.config.computer.name,
                project_path=project_path,
                session_id=None,
                error_type=type(exc).__name__,
            )
            raise

        logger.info(
            LauncherEvent.COMMAND_COMPLETED,
            outcome=(LauncherCommandOutcome.SESSION_CREATED_LOCAL if session_id else LauncherCommandOutcome.FAILED),
            reason=(
                LauncherCommandReason.SESSION_CREATED if session_id else LauncherCommandReason.SESSION_ID_UNRESOLVED
            ),
            interaction_id=source.interaction_id,
            message_id=source.message_id,
            thread_id=source.thread_id,
            forum_id=source.forum_id,
            category_id=source.category_id,
            receiver_computer=teleclaude_config.config.computer.name,
            project_path=project_path,
            session_id=session_id or None,
        )

        followup = getattr(interaction, _FOLLOWUP_FIELD, None)
        followup_send = getattr(followup, _SEND_FIELD, None)
        if not callable(followup_send):
            return
        if session_id:
            await self._async_callable(followup_send, label=_FOLLOWUP_SEND_LABEL)(
                _STARTING_AGENT_TEMPLATE.format(agent_name=agent_name),
                ephemeral=True,
            )
            return
        await self._async_callable(followup_send, label=_FOLLOWUP_SEND_LABEL)(
            _FAILED_AGENT_TEMPLATE.format(agent_name=agent_name),
            ephemeral=True,
        )
