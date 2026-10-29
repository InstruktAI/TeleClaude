"""Forum sessions mixin for the Discord adapter.

Resolves or creates the session a managed forum message belongs to, and routes that message's
voice and file attachments to it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import PersonCliCaller, RoleResolver, SessionOf
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.inbound import InboundSessionPolicy, resolve_or_create_bound_session
from teleclaude.core.models import (
    AgentDispatchMode,
    DiscordAdapterMetadata,
    DiscordMetadataField,
    Session,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

_UNKNOWN_FORUM = "unknown"
_NO_SESSION_PROJECT_EVENT = "discord_session_creation_no_project"
_DISCORD_SECTION = InputOrigin.DISCORD.value
_NO_TEXT = ""
_AUTHOR_ATTR = "author"
_GUILD_ATTR = "guild"
_CHANNEL_ATTR = "channel"
_PARENT_ATTR = "parent"
_ID_ATTR = "id"
_SESSION_ID_FIELD = "session_id"
_DISCORD_USER_ID_FIELD = "discord_user_id"
_PLATFORM_FIELD = "platform"
_VOICE_RESOLUTION_FAILED_TEMPLATE = "Discord session resolution failed for voice: %s"
_FILE_RESOLUTION_FAILED_TEMPLATE = "Discord session resolution failed for file attachments: %s"
_EMPTY_SESSION_ID_MESSAGE = "Discord session creation returned empty session_id"


@dataclass(frozen=True, slots=True)
class _SessionCreationContext:
    """Context used while creating a new Discord-backed session."""

    forum_type: str = "project"
    project_path: str | None = None
    first_message: str | None = None


@dataclass(frozen=True, slots=True)
class _DiscordRoutingIds:
    """Discord channel identifiers that should be synced onto a session."""

    user_id: str
    guild_id: int | None
    channel_id: int | None
    thread_id: int | None


class ForumSessionsMixin:
    """Mixin resolving or creating forum message sessions and routing their attachments for DiscordAdapter.

    Required host attributes:
    - _parse_optional_int(value) -> int | None
    - _resolve_project_from_forum(forum_id) -> str | None
    - _resolve_forum_context(message) -> tuple[str, str | None]
    - _is_thread_channel(channel) -> bool
    - _discord_errors() -> tuple[type[Exception], ...] (from InputHandlersMixin)
    - _dispatch_voice_attachment(session, message, attachment, *, recovered_at, retain_refusal) -> Task | None (async; from InputHandlersMixin)
    - _dispatch_file_attachments(session, message, attachments, *, recovered_at, retain_refusal) (async; from InputHandlersMixin)
    """

    if TYPE_CHECKING:

        def _parse_optional_int(self, value: object) -> int | None: ...

        def _resolve_project_from_forum(self, forum_id: int) -> str | None: ...

        def _resolve_forum_context(self, message: object) -> tuple[str, str | None]: ...

        @staticmethod
        def _is_thread_channel(channel: object) -> bool: ...

        def _discord_errors(self) -> tuple[type[Exception], ...]: ...

        async def _dispatch_voice_attachment(
            self,
            session: Session,
            message: object,
            attachment: object,
            *,
            recovered_at: datetime | None = None,
            retain_refusal: bool = False,
        ) -> asyncio.Task[object] | None: ...

        async def _dispatch_file_attachments(
            self,
            session: Session,
            message: object,
            attachments: list[object],
            *,
            recovered_at: datetime | None = None,
            retain_refusal: bool = False,
        ) -> None: ...

    async def resolve_or_create_session(self, message: object, *, first_message: str | None = None) -> Session | None:
        """Public wrapper for Discord session resolution or creation."""
        return await self._resolve_or_create_session(message, first_message=first_message)

    @staticmethod
    def _build_launch_intent(first_message: str | None) -> SessionLaunchIntent:
        """Build the typed launch intent for a new Discord-backed session."""
        if first_message:
            return SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                thinking_mode=ThinkingMode.SLOW.value,
                message=first_message,
                dispatch_mode=AgentDispatchMode.AUTOMATIC,
            )
        return SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            thinking_mode=ThinkingMode.SLOW.value,
            dispatch_mode=AgentDispatchMode.AUTOMATIC,
        )

    def _resolve_session_creation_target(
        self,
        message: object,
        context: _SessionCreationContext,
    ) -> str | None:
        """Resolve the project path a new session is created in; ``None`` when the message names no project."""
        forum_id, _ = self._extract_channel_ids(message)
        forum_project_path = self._resolve_project_from_forum(forum_id) if forum_id is not None else None
        return forum_project_path or context.project_path

    async def _handle_voice_attachment(
        self, message: object, attachment: object, *, recovered_at: datetime | None = None, retain_refusal: bool = False
    ) -> asyncio.Task[object] | None:
        """Resolve the message's session through the legacy resolver, then dispatch the voice attachment.

        Returns the transcription task, so a caller that must know when the input was accepted can wait for it.
        """
        recoverable_errors = self._discord_errors()
        try:
            session = await self._resolve_or_create_session(message)
        except recoverable_errors as exc:
            logger.error(_VOICE_RESOLUTION_FAILED_TEMPLATE, exc, exc_info=True)
            return None
        if not session:
            return None
        return await self._dispatch_voice_attachment(
            session, message, attachment, recovered_at=recovered_at, retain_refusal=retain_refusal
        )

    async def _handle_file_attachments(
        self,
        message: object,
        attachments: list[object],
        *,
        recovered_at: datetime | None = None,
        retain_refusal: bool = False,
    ) -> None:
        """Resolve the message's session through the legacy resolver, then dispatch the file attachments."""
        recoverable_errors = self._discord_errors()
        try:
            session = await self._resolve_or_create_session(message)
        except recoverable_errors as exc:
            logger.error(_FILE_RESOLUTION_FAILED_TEMPLATE, exc, exc_info=True)
            return
        if not session:
            return
        await self._dispatch_file_attachments(
            session, message, attachments, recovered_at=recovered_at, retain_refusal=retain_refusal
        )

    async def _resolve_or_create_session(
        self,
        message: object,
        *,
        first_message: str | None = None,
    ) -> Session | None:
        """Resolve-or-create for callers that don't need the explicit is_new flag.

        Voice/file attachment callers always dispatch their command regardless
        of new-vs-existing, so they use this thin wrapper; the text path
        (`_handle_on_message`) needs `is_new` for its delivery gate and calls
        `_resolve_or_create_discord_session` directly.
        """
        session, _is_new = await self._resolve_or_create_discord_session(message, first_message=first_message)
        return session

    async def _resolve_or_create_discord_session(
        self,
        message: object,
        *,
        first_message: str | None = None,
    ) -> tuple[Session | None, bool]:
        user_id = str(getattr(getattr(message, _AUTHOR_ATTR, None), _ID_ATTR, _NO_TEXT))
        if not user_id:
            return None, False

        channel_id, thread_id = self._extract_channel_ids(message)
        guild_id = self._parse_optional_int(getattr(getattr(message, _GUILD_ATTR, None), _ID_ATTR, None))
        routing_ids = _DiscordRoutingIds(user_id=user_id, guild_id=guild_id, channel_id=channel_id, thread_id=thread_id)

        async def _find() -> Session | None:
            session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
            if session is None:
                return None
            return await self._backfill_human_role(session, user_id)

        async def _create() -> Session | None:
            forum_type, project_path = self._resolve_forum_context(message)
            if forum_type == _UNKNOWN_FORUM:
                return None
            return await self._create_session_for_message(
                message,
                user_id,
                _SessionCreationContext(
                    forum_type=forum_type,
                    project_path=project_path,
                    first_message=first_message,
                ),
            )

        async def _reconcile(session: Session) -> Session:
            return await self._update_session_discord_metadata(session, routing_ids)

        policy = InboundSessionPolicy(find=_find, create=_create, reconcile=_reconcile)
        return await resolve_or_create_bound_session(policy)

    async def _backfill_human_role(self, session: Session, user_id: str) -> Session:
        """Backfill a found session's human_role from identity when it predates that field."""
        if session.human_role:
            return session
        identity = get_identity_resolver().resolve(_DISCORD_SECTION, {DiscordMetadataField.USER_ID: user_id})
        if identity and identity.person_slug:
            caller = PersonCliCaller(
                email=identity.person_email,
                person_slug=identity.person_slug,
                human_role=identity.person_role,
            )
            role = RoleResolver().role_for(caller, SessionOf(session.project_path))
            await db.update_session(session.session_id, human_role=role)
            return await db.get_session(session.session_id) or session
        return session

    def _extract_channel_ids(self, message: object) -> tuple[int | None, int | None]:
        channel = getattr(message, _CHANNEL_ATTR, None)
        if not self._is_thread_channel(channel):
            return (self._parse_optional_int(getattr(channel, _ID_ATTR, None)), None)

        thread_id = self._parse_optional_int(getattr(channel, _ID_ATTR, None))
        parent = getattr(channel, _PARENT_ATTR, None)
        parent_id = self._parse_optional_int(getattr(parent, _ID_ATTR, None))
        return (parent_id or thread_id, thread_id)

    async def _find_session(
        self,
        *,
        channel_id: int | None,
        thread_id: int | None,
        user_id: str,
    ) -> Session | None:
        if thread_id is not None:
            thread_sessions = await db.get_sessions_by_origin_metadata(
                _DISCORD_SECTION, DiscordMetadataField.THREAD_ID, thread_id
            )
            if thread_sessions:
                return thread_sessions[0]
            # Thread-scoped: don't fall through to channel_id lookup.
            # Falling through would return a stale channel session, not the thread session the caller expects.
            return None

        if channel_id is None:
            return None

        channel_sessions = await db.get_sessions_by_origin_metadata(
            _DISCORD_SECTION, DiscordMetadataField.CHANNEL_ID, channel_id
        )
        for session in channel_sessions:
            if DiscordAdapterMetadata.from_dict(session.get_origin_section(_DISCORD_SECTION)).user_id == user_id:
                return session
        return None

    async def _create_session_for_message(
        self,
        message: object,
        user_id: str,
        context: _SessionCreationContext,
    ) -> Session | None:
        origin_metadata: dict[str, str] = {
            DiscordMetadataField.USER_ID: user_id,
            _DISCORD_USER_ID_FIELD: user_id,
            _PLATFORM_FIELD: _DISCORD_SECTION,
        }

        effective_path = self._resolve_session_creation_target(message, context)
        if effective_path is None:
            logger.info(_NO_SESSION_PROJECT_EVENT, forum_type=context.forum_type)
            return None
        launch_intent = self._build_launch_intent(context.first_message)

        create_cmd = CreateSessionCommand(
            project_path=effective_path,
            initial_input=context.first_message,
            origin=InputOrigin.DISCORD.value,
            origin_metadata=origin_metadata,
            launch_intent=launch_intent,
            entry_point=SessionEntryPoint.DISCORD,
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get(_SESSION_ID_FIELD, _NO_TEXT))
        if not session_id:
            logger.error(_EMPTY_SESSION_ID_MESSAGE)
            return None
        return await db.get_session(session_id)

    async def _update_session_discord_metadata(self, session: Session, routing_ids: _DiscordRoutingIds) -> Session:
        discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section(_DISCORD_SECTION))
        # Only the ids this call actually changes are written. Submitting the
        # whole serialized section would carry every other field forward from
        # this snapshot and revert a concurrent writer's change to it.
        changes: dict[str, object] = {}  # guard: loose-dict - origin field delta

        if discord_meta.user_id != routing_ids.user_id:
            changes[DiscordMetadataField.USER_ID] = routing_ids.user_id
        if routing_ids.guild_id is not None and discord_meta.guild_id != routing_ids.guild_id:
            changes[DiscordMetadataField.GUILD_ID] = routing_ids.guild_id
        if routing_ids.channel_id is not None and discord_meta.channel_id != routing_ids.channel_id:
            changes[DiscordMetadataField.CHANNEL_ID] = routing_ids.channel_id
        if routing_ids.thread_id is not None and discord_meta.thread_id != routing_ids.thread_id:
            changes[DiscordMetadataField.THREAD_ID] = routing_ids.thread_id

        if not changes:
            return session

        await db.update_origin_metadata(session.session_id, _DISCORD_SECTION, changes)
        return (await db.get_session(session.session_id)) or session
