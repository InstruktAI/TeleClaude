"""Input handling mixin for Discord adapter.

Handles voice/audio/file attachments, session resolution and creation,
channel ID extraction, destination resolution, and forum thread creation.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude import config as teleclaude_config
from teleclaude.adapters.base_adapter import AdapterError, ChannelNotProvisionedError
from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
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
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.delivery import Destination
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
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.invite import scaffold_personal_workspace
from teleclaude.slug import normalize_slug
from teleclaude.types.commands import CreateSessionCommand, HandleFileCommand, HandleVoiceCommand, KeysCommand

logger = get_logger(__name__)

VOICE_DOWNLOAD_EVENT = "discord_voice_downloaded"
VOICE_DOWNLOAD_SIZE_MISMATCH_EVENT = "discord_voice_download_size_mismatch"
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


@dataclass(frozen=True, slots=True)
class _SessionCreationContext:
    """Context used while creating a new Discord-backed session."""

    forum_type: str = "help_desk"
    project_path: str | None = None
    first_message: str | None = None


@dataclass(frozen=True, slots=True)
class _DiscordRoutingIds:
    """Discord channel identifiers that should be synced onto a session."""

    user_id: str
    guild_id: int | None
    channel_id: int | None
    thread_id: int | None


class InputHandlersMixin:
    """Mixin providing input event handling and session routing for DiscordAdapter.

    Required host attributes:
    - _client: DiscordClientLike | None
    - _project_forum_map: dict[str, int]
    - _team_channel_map: dict[int, str]
    - _require_async_callable(fn, *, label) -> Callable
    - _parse_optional_int(value) -> int | None
    - _extract_forum_thread_result(result) -> tuple
    - _fit_message_text(text, *, context) -> str
    - _resolve_project_from_forum(forum_id) -> str | None
    - _resolve_interaction_forum_id(interaction) -> int | None (async)
    - _get_managed_forum_ids() -> set[int]
    - _discord_actor_name(author, user_id) -> str
    - _discord_actor_avatar_url(author) -> str | None
    - _resolve_forum_context(message) -> tuple[str, str | None]
    - _get_channel(channel_id) -> object | None (async)
    - ensure_channel(session) -> Session (async; from ChannelOperationsMixin)
    """

    _team_channel_map: dict[int, str]
    _project_forum_map: dict[str, int]
    _forum_project_map: dict[int, str]
    _project_category_id: int | None
    _registered_launcher_message_ids: set[int]

    _client: object

    if TYPE_CHECKING:

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> AsyncDiscordCallable: ...

        @staticmethod
        def _extract_forum_thread_result(create_result: object) -> tuple[object | None, object | None]: ...

        def _fit_message_text(self, *args: object, **kwargs: object) -> str: ...

        def _resolve_project_from_forum(self, forum_id: int) -> str | None: ...

        async def _resolve_interaction_forum_id(self, interaction: object) -> int | None: ...

        async def _resolve_launcher_interaction_source(self, interaction: object) -> LauncherInteractionSource: ...

        def _get_managed_forum_ids(self) -> set[int]: ...

        def _resolve_forum_context(self, message: object) -> tuple[str, str | None]: ...

        @staticmethod
        def _discord_actor_name(author: object, user_id: str) -> str: ...

        @staticmethod
        def _discord_actor_avatar_url(author: object) -> str | None: ...

        async def ensure_channel(self, session: Session) -> Session: ...

    async def resolve_or_create_session(self, message: object, *, first_message: str | None = None) -> Session | None:
        """Public wrapper for Discord session resolution or creation."""
        return await self._resolve_or_create_session(message, first_message=first_message)

    def _discord_errors(self) -> tuple[type[Exception], ...]:
        """Return recoverable exception types for Discord adapter side effects."""
        return recoverable_operation_errors(getattr(self, "_discord", None))

    def _async_callable(self, fn: object, *, label: str) -> AsyncDiscordCallable:
        """Validate and cast a dynamically resolved Discord coroutine method."""
        return cast_async_callable(self._require_async_callable, fn, label=label)

    @staticmethod
    def _interaction_response_text(message: str) -> tuple[str, bool]:
        """Build a standard interaction-response payload tuple."""
        return message, True

    def _prepare_attachment_target(self, session: Session, attachment: object, index: int) -> tuple[str, Path, bool]:
        """Compute the filename, destination path, and image flag for an attachment."""
        content_type = getattr(attachment, "content_type", None) or ""
        is_image = content_type.startswith("image/")
        filename = getattr(attachment, "filename", None)
        if not filename:
            ext = ".jpg" if is_image else ".dat"
            filename = f"file_{index}{ext}"
        subdir = "photos" if is_image else "files"
        output_dir = get_session_output_dir(session.session_id) / subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        return filename, output_dir / filename, is_image

    async def _process_attachment(
        self,
        session: Session,
        attachment: object,
        index: int,
        caption: str | None,
    ) -> None:
        """Save one Discord attachment and dispatch it through the command service."""
        filename, file_path, is_image = self._prepare_attachment_target(session, attachment, index)
        save_attachment = self._async_callable(getattr(attachment, "save", None), label="Discord attachment save")
        await save_attachment(file_path)
        logger.info("Downloaded Discord %s to: %s", "image" if is_image else "file", file_path)
        await get_command_service().handle_file(
            HandleFileCommand(
                session_id=session.session_id,
                file_path=str(file_path),
                filename=filename,
                caption=caption if index == 0 else None,
            )
        )

    @staticmethod
    def _build_launch_intent(first_message: str | None) -> SessionLaunchIntent:
        """Build the typed launch intent for a new Discord-backed session."""
        if first_message:
            return SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                thinking_mode="slow",
                message=first_message,
                dispatch_mode=AgentDispatchMode.AUTOMATIC,
            )
        return SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            thinking_mode="slow",
            dispatch_mode=AgentDispatchMode.AUTOMATIC,
        )

    def _resolve_session_creation_target(
        self,
        message: object,
        context: _SessionCreationContext,
    ) -> tuple[str, str | None]:
        """Resolve the effective project path and human_role override for a new session."""
        if context.forum_type == "help_desk":
            return context.project_path or teleclaude_config.config.computer.help_desk_dir, "customer"
        if context.forum_type == "team":
            user_id = str(getattr(getattr(message, "author", None), "id", ""))
            identity = get_identity_resolver().resolve("discord", {"user_id": user_id})

            human_role = identity.person_role

            project_path = context.project_path
            if not project_path:
                project_path = teleclaude_config.config.computer.help_desk_dir

            if identity.person_name:
                person_slug = identity.person_slug or normalize_slug(identity.person_name)
                project_path = str(scaffold_personal_workspace(person_slug, identity.person_name))
            else:
                # Ensure a deterministic workspace path exists for legacy team channels.
                if project_path:
                    workspace_path = Path(project_path)
                    if not workspace_path.exists():
                        workspace_path.mkdir(parents=True, exist_ok=True)
            return project_path, human_role

        forum_id, _ = self._extract_channel_ids(message)
        forum_project_path = self._resolve_project_from_forum(forum_id) if forum_id is not None else None
        return (
            forum_project_path or context.project_path or teleclaude_config.config.computer.help_desk_dir,
            None,
        )

    # =========================================================================
    # Attachment Extraction
    # =========================================================================

    @staticmethod
    def _extract_audio_attachment(message: object) -> object | None:
        """Return the first audio attachment from a Discord message, or None."""
        attachments = getattr(message, "attachments", None)
        if not attachments:
            return None
        for attachment in attachments:
            content_type = getattr(attachment, "content_type", None) or ""
            if content_type.startswith("audio/"):
                return attachment  # type: ignore[no-any-return]
        return None

    @staticmethod
    def _extract_file_attachments(message: object) -> list[object]:
        """Return all non-audio attachments from a Discord message."""
        attachments = getattr(message, "attachments", None)
        if not attachments:
            return []
        result = []
        for attachment in attachments:
            content_type = getattr(attachment, "content_type", None) or ""
            if not content_type.startswith("audio/"):
                result.append(attachment)
        return result

    # =========================================================================
    # Attachment Handlers
    # =========================================================================

    async def _handle_voice_attachment(self, message: object, attachment: object) -> None:
        """Download a voice/audio attachment and dispatch it for transcription."""
        recoverable_errors = self._discord_errors()
        try:
            session = await self._resolve_or_create_session(message)
        except recoverable_errors as exc:
            logger.error("Discord session resolution failed for voice: %s", exc, exc_info=True)
            return
        if not session:
            return

        message_id = str(getattr(message, "id", ""))

        # Derive file extension from the attachment filename or default to .ogg
        filename = getattr(attachment, "filename", None) or "voice.ogg"
        ext = Path(filename).suffix or ".ogg"

        temp_dir = Path(tempfile.gettempdir()) / "teleclaude_voice"
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / f"voice_{message_id}{ext}"

        try:
            save_fn = self._async_callable(getattr(attachment, "save", None), label="Discord attachment save")
            bytes_written = await save_fn(temp_file_path)

            # Discord exposes duration (seconds) and the authoritative byte count on audio attachments
            raw_duration = getattr(attachment, "duration", None)
            duration = float(raw_duration) if raw_duration is not None else None
            attachment_size = getattr(attachment, "size", None)

            logger.debug(
                VOICE_DOWNLOAD_EVENT,
                file_path=str(temp_file_path),
                bytes_written=bytes_written,
                attachment_size=attachment_size,
                duration_seconds=duration,
            )
            if attachment_size is not None and bytes_written != attachment_size:
                logger.error(
                    VOICE_DOWNLOAD_SIZE_MISMATCH_EVENT,
                    file_path=str(temp_file_path),
                    bytes_written=bytes_written,
                    attachment_size=attachment_size,
                    duration_seconds=duration,
                )

            cmd = HandleVoiceCommand(
                session_id=session.session_id,
                file_path=str(temp_file_path),
                duration=duration,
                message_id=message_id,
                origin=InputOrigin.DISCORD.value,
                actor_id=f"discord:{getattr(getattr(message, 'author', None), 'id', 'unknown')}",
                actor_name=self._discord_actor_name(
                    getattr(message, "author", None),
                    str(getattr(getattr(message, "author", None), "id", "unknown")),
                ),
                actor_avatar_url=self._discord_actor_avatar_url(getattr(message, "author", None)),
            )
            registry = getattr(self, "task_registry", None)
            if registry is None:
                raise RuntimeError("Discord voice handling requires task_registry")
            registry.spawn(get_command_service().handle_voice(cmd), name=f"voice-{message_id}")
        except recoverable_errors as exc:
            error_msg = str(exc) if str(exc).strip() else "Unknown error"
            logger.error("Failed to process Discord voice message: %s", error_msg, exc_info=True)

    async def _handle_file_attachments(self, message: object, attachments: list[object]) -> None:
        """Download file/image attachments and dispatch them for processing."""
        recoverable_errors = self._discord_errors()
        try:
            session = await self._resolve_or_create_session(message)
        except recoverable_errors as exc:
            logger.error("Discord session resolution failed for file attachments: %s", exc, exc_info=True)
            return
        if not session:
            return

        # Get text caption for the first attachment only (to avoid duplication)
        caption = getattr(message, "content", None)
        if not isinstance(caption, str) or not caption.strip():
            caption = None

        for index, attachment in enumerate(attachments):
            try:
                await self._process_attachment(session, attachment, index, caption)
            except recoverable_errors as exc:
                filename = getattr(attachment, "filename", None) or f"file_{index}.dat"
                error_msg = str(exc) if str(exc).strip() else "Unknown error"
                logger.error(
                    "Failed to process Discord attachment %s: %s",
                    filename,
                    error_msg,
                    exc_info=True,
                )
                # Continue to next attachment

    # =========================================================================
    # Session Resolution
    # =========================================================================

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
        user_id = str(getattr(getattr(message, "author", None), "id", ""))
        if not user_id:
            return None, False

        channel_id, thread_id = self._extract_channel_ids(message)
        guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))
        routing_ids = _DiscordRoutingIds(user_id=user_id, guild_id=guild_id, channel_id=channel_id, thread_id=thread_id)

        async def _find() -> Session | None:
            session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
            if session is None:
                return None
            return await self._backfill_human_role(session, user_id)

        async def _create() -> Session | None:
            forum_type, project_path = self._resolve_forum_context(message)
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
        identity = get_identity_resolver().resolve("discord", {"user_id": user_id})
        if identity and identity.person_role:
            await db.update_session(session.session_id, human_role=identity.person_role)
            return await db.get_session(session.session_id) or session
        return session

    @staticmethod
    def _is_thread_channel(channel: object) -> bool:
        type_name = type(channel).__name__.lower()
        return "thread" in type_name

    def _extract_channel_ids(self, message: object) -> tuple[int | None, int | None]:
        channel = getattr(message, "channel", None)
        if not self._is_thread_channel(channel):
            return (self._parse_optional_int(getattr(channel, "id", None)), None)

        thread_id = self._parse_optional_int(getattr(channel, "id", None))
        parent = getattr(channel, "parent", None)
        parent_id = self._parse_optional_int(getattr(parent, "id", None))
        return (parent_id or thread_id, thread_id)

    async def _find_session(
        self,
        *,
        channel_id: int | None,
        thread_id: int | None,
        user_id: str,
    ) -> Session | None:
        if thread_id is not None:
            thread_sessions = await db.get_sessions_by_origin_metadata("discord", "thread_id", thread_id)
            if thread_sessions:
                return thread_sessions[0]
            # Thread-scoped: don't fall through to channel_id lookup.
            # Falling through would return a stale channel session, not the thread session the caller expects.
            return None

        if channel_id is None:
            return None

        channel_sessions = await db.get_sessions_by_origin_metadata("discord", "channel_id", channel_id)
        for session in channel_sessions:
            if DiscordAdapterMetadata.from_dict(session.get_origin_section("discord")).user_id == user_id:
                return session
        return None

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

    async def _handle_cancel_slash(self, interaction: object) -> None:
        channel = getattr(interaction, "channel", None)
        response = getattr(interaction, "response", None)
        response_send = getattr(response, "send_message", None)
        if not callable(response_send):
            return
        if not self._is_thread_channel(channel):
            await self._async_callable(response_send, label="Discord interaction response.send_message")(
                "No active session in this thread.",
                ephemeral=True,
            )
            return

        thread_id = self._parse_optional_int(getattr(channel, "id", None))
        parent = getattr(channel, "parent", None)
        parent_id = self._parse_optional_int(getattr(parent, "id", None))
        channel_id = parent_id or thread_id

        user_obj = getattr(interaction, "user", None)
        user_id = str(getattr(user_obj, "id", "")).strip()
        session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
        if session is None:
            await self._async_callable(response_send, label="Discord interaction response.send_message")(
                "No active session in this thread.",
                ephemeral=True,
            )
            return

        cmd = KeysCommand(session_id=session.session_id, key="cancel", args=[])
        await self._async_callable(response_send, label="Discord interaction response.send_message")(
            "Sent CTRL+C",
            ephemeral=True,
        )
        await get_command_service().keys(cmd)

    async def _create_session_for_message(
        self,
        message: object,
        user_id: str,
        context: _SessionCreationContext,
    ) -> Session | None:
        origin_metadata: dict[str, str] = {
            "user_id": user_id,
            "discord_user_id": user_id,
            "platform": "discord",
        }

        effective_path, _human_role = self._resolve_session_creation_target(message, context)
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
        session_id = str(result.get("session_id", ""))
        if not session_id:
            logger.error("Discord session creation returned empty session_id")
            return None
        return await db.get_session(session_id)

    async def _update_session_discord_metadata(self, session: Session, routing_ids: _DiscordRoutingIds) -> Session:
        discord_meta = DiscordAdapterMetadata.from_dict(session.get_origin_section("discord"))
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

        await db.update_origin_metadata(session.session_id, "discord", changes)
        return (await db.get_session(session.session_id)) or session

    async def _resolve_destination_channel(
        self,
        destination: Destination,
    ) -> object:
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        destination_id = destination.thread_id or destination.channel_id
        logger.debug(
            "[DISCORD_RESOLVE] session=%s -> destination=%s",
            destination.session_id,
            destination_id,
        )
        if destination_id is None:
            raise ChannelNotProvisionedError(f"Session {destination.session_id} has no discord channel mapping yet")

        channel = await self._get_channel(destination_id)
        if channel is None:
            # Channel was deleted from Discord — clear stale metadata so we stop retrying
            logger.warning(
                "Discord channel %s not found for session %s, clearing stale metadata",
                destination_id,
                destination.session_id,
            )
            clear_section: dict[str, object] = {  # guard: loose-dict - JSON merge-patch section
                DiscordMetadataField.THREAD_ID: None,
                DiscordMetadataField.CHANNEL_ID: None,
                DiscordMetadataField.OUTPUT_MESSAGE_ID: None,
                DiscordMetadataField.THREAD_TOPPER_MESSAGE_ID: None,
            }
            await db.update_origin_metadata(destination.session_id, "discord", clear_section)
            raise AdapterError(f"Discord channel {destination_id} not found (metadata cleared)")
        return channel

    async def _fetch_destination_message(
        self,
        destination: Destination,
        message_id: str,
    ) -> object:
        channel = await self._resolve_destination_channel(destination)
        fetch_fn = self._async_callable(getattr(channel, "fetch_message", None), label="Discord channel fetch_message")
        if not message_id.isdigit():
            raise AdapterError(f"Discord message_id must be numeric, got {message_id!r}")
        return await fetch_fn(int(message_id))

    async def _get_channel(self, channel_id: int) -> object | None:
        if self._client is None:
            return None

        get_fn = getattr(self._client, "get_channel", None)
        if callable(get_fn):
            cached = get_fn(channel_id)
            if cached is not None:
                return cached  # type: ignore[no-any-return]

        fetch_fn = getattr(self._client, "fetch_channel", None)
        if callable(fetch_fn):
            recoverable_errors = self._discord_errors()
            try:
                fetch_channel = self._async_callable(fetch_fn, label="Discord client fetch_channel")
                return await fetch_channel(channel_id)
            except recoverable_errors as exc:
                logger.debug("Discord fetch_channel(%s) failed: %s", channel_id, exc)
        return None

    async def _create_forum_thread(
        self, forum_channel: object, *, title: str, content: str = "Initializing Help Desk session..."
    ) -> tuple[int, str]:
        create_thread_fn = self._async_callable(
            getattr(forum_channel, "create_thread", None),
            label="Discord forum create_thread",
        )

        # Discord channel names must be 1-100 characters
        if len(title) > 100:
            title = title[:97] + "..."
        result = await create_thread_fn(name=title, content=self._fit_message_text(content, context="thread_starter"))
        thread, starter_message = self._extract_forum_thread_result(result)

        thread_id = self._parse_optional_int(getattr(thread, "id", None))
        if thread_id is None:
            raise AdapterError("Discord create_thread() returned invalid thread id")
        starter_message_id_raw = getattr(starter_message, "id", None)
        starter_message_id = str(starter_message_id_raw) if starter_message_id_raw is not None else str(thread_id)
        return thread_id, starter_message_id
