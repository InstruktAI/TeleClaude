"""Input handling mixin for Discord adapter.

Handles voice/audio/file attachments, session resolution and creation,
channel ID extraction, destination resolution, forum thread creation,
and escalation thread creation.
"""

from __future__ import annotations

import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
from teleclaude.adapters.base_adapter import AdapterError
from teleclaude import config as teleclaude_config
from teleclaude.core.agents import get_default_agent
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import MessageMetadata, Session, SessionMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.types.commands import CreateSessionCommand, HandleFileCommand, HandleVoiceCommand, KeysCommand

logger = get_logger(__name__)


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
    - _escalation_channel_id: int | None
    - _project_forum_map: dict[str, int]
    - _team_channel_map: dict[int, str]
    - _require_async_callable(fn, *, label) -> Callable
    - _parse_optional_int(value) -> int | None
    - _is_forum_channel(channel) -> bool
    - _extract_forum_thread_result(result) -> tuple
    - _fit_message_text(text, *, context) -> str
    - _resolve_project_from_forum(forum_id) -> str | None
    - _resolve_interaction_forum_id(interaction) -> int | None (async)
    - _discord_actor_name(author, user_id) -> str
    - _discord_actor_avatar_url(author) -> str | None
    - _resolve_forum_context(message) -> tuple[str, str | None]
    - _get_channel(channel_id) -> object | None (async)
    """

    _team_channel_map: dict[int, str]
    _project_forum_map: dict[str, int]

    _client: object
    _escalation_channel_id: int | None
    _parse_optional_int: Callable[[object], int | None]
    _require_async_callable: Callable[..., AsyncDiscordCallable]
    _is_forum_channel: Callable[[object], bool]
    _extract_forum_thread_result: Callable[[object], tuple[object | None, object | None]]
    _fit_message_text: Callable[..., str]
    _resolve_project_from_forum: Callable[[int], str | None]
    _resolve_interaction_forum_id: Callable[[object], Awaitable[int | None]]
    _get_channel: Callable[[int], Awaitable[object | None]]
    _resolve_forum_context: Callable[[object], tuple[str, str | None]]
    _discord_actor_name: Callable[[object, str], str]
    _discord_actor_avatar_url: Callable[[object], str | None]

    async def resolve_or_create_session(self, message: object, *, first_message: str | None = None) -> Session | None:
        """Public wrapper for Discord session resolution or creation."""
        return await self._resolve_or_create_session(message, first_message=first_message)

    async def handle_launcher_click(self, interaction: object, agent_name: str) -> None:
        """Public wrapper for Discord session-launcher button handling."""
        await self._handle_launcher_click(interaction, agent_name)

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
    def _build_auto_command(agent_name: str, first_message: str | None) -> str:
        """Build the auto-start command for a new Discord-backed session."""
        if first_message:
            return f"agent_then_message {agent_name} slow {first_message}"
        return f"agent {agent_name}"

    def _resolve_session_creation_target(
        self,
        message: object,
        context: _SessionCreationContext,
    ) -> tuple[str, SessionMetadata | None]:
        """Resolve the effective project path and session metadata for a new session."""
        session_meta: SessionMetadata | None = None
        if context.forum_type == "help_desk":
            session_meta = SessionMetadata(human_role="customer")
            return context.project_path or teleclaude_config.config.computer.help_desk_dir, session_meta

        forum_id, _ = self._extract_channel_ids(message)
        forum_project_path = self._resolve_project_from_forum(forum_id) if forum_id is not None else None
        return (
            forum_project_path or context.project_path or teleclaude_config.config.computer.help_desk_dir,
            session_meta,
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
            await save_fn(temp_file_path)
            logger.info("Downloaded Discord voice message to: %s", temp_file_path)

            # Discord exposes duration (seconds) on audio attachments
            raw_duration = getattr(attachment, "duration", None)
            duration = float(raw_duration) if raw_duration is not None else None

            await get_command_service().handle_voice(
                HandleVoiceCommand(
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
            )
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
        user_id = str(getattr(getattr(message, "author", None), "id", ""))
        if not user_id:
            return None

        channel_id, thread_id = self._extract_channel_ids(message)
        guild_id = self._parse_optional_int(getattr(getattr(message, "guild", None), "id", None))

        session = await self._find_session(channel_id=channel_id, thread_id=thread_id, user_id=user_id)
        if session and not session.human_role:
            identity = get_identity_resolver().resolve("discord", {"user_id": user_id})
            if identity and identity.person_role:
                await db.update_session(session.session_id, human_role=identity.person_role)
                session = await db.get_session(session.session_id) or session
        if session is None:
            forum_type, project_path = self._resolve_forum_context(message)
            session = await self._create_session_for_message(
                message,
                user_id,
                _SessionCreationContext(
                    forum_type=forum_type,
                    project_path=project_path,
                    first_message=first_message,
                ),
            )
            if session is None:
                return None

        return await self._update_session_discord_metadata(
            session,
            _DiscordRoutingIds(
                user_id=user_id,
                guild_id=guild_id,
                channel_id=channel_id,
                thread_id=thread_id,
            ),
        )

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
            thread_sessions = await db.get_sessions_by_adapter_metadata("discord", "thread_id", thread_id)
            if thread_sessions:
                return thread_sessions[0]
            # Thread-scoped: don't fall through to channel_id lookup.
            # Falling through would return a stale channel session, not the thread session the caller expects.
            return None

        if channel_id is None:
            return None

        channel_sessions = await db.get_sessions_by_adapter_metadata("discord", "channel_id", channel_id)
        for session in channel_sessions:
            if session.get_metadata().get_ui().get_discord().user_id == user_id:
                return session
        return None

    async def _handle_launcher_click(self, interaction: object, agent_name: str) -> None:
        response = getattr(interaction, "response", None)
        response_defer = getattr(response, "defer", None)
        if callable(response_defer):
            await self._async_callable(response_defer, label="Discord interaction response.defer")(
                ephemeral=True
            )

        forum_id = await self._resolve_interaction_forum_id(interaction)
        project_path = self._resolve_project_from_forum(forum_id) if forum_id is not None else None
        if project_path is None:
            followup = getattr(interaction, "followup", None)
            followup_send = getattr(followup, "send", None)
            if callable(followup_send):
                await self._async_callable(followup_send, label="Discord interaction followup.send")(
                    "Unable to resolve project for this forum.",
                    ephemeral=True,
                )
            return

        user_obj = getattr(interaction, "user", None)
        user_id = str(getattr(user_obj, "id", "")).strip()

        create_cmd = CreateSessionCommand(
            project_path=project_path,
            auto_command=f"agent {agent_name}",
            origin=InputOrigin.DISCORD.value,
            channel_metadata={"user_id": user_id, "discord_user_id": user_id, "platform": "discord"}
            if user_id
            else None,
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get("session_id", ""))

        followup = getattr(interaction, "followup", None)
        followup_send = getattr(followup, "send", None)
        if not callable(followup_send):
            return
        if session_id:
            await self._async_callable(followup_send, label="Discord interaction followup.send")(
                f"Starting {agent_name}...",
                ephemeral=True,
            )
            return
        await self._async_callable(followup_send, label="Discord interaction followup.send")(
            f"Failed to start {agent_name}.",
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
        author = getattr(message, "author", None)
        display_name = str(
            getattr(author, "display_name", None) or getattr(author, "name", None) or f"discord-{user_id}"
        )
        channel_metadata: dict[str, str] = {
            "user_id": user_id,
            "discord_user_id": user_id,
            "platform": "discord",
        }

        agent = get_default_agent()
        effective_path, session_meta = self._resolve_session_creation_target(message, context)
        auto_command = self._build_auto_command(agent, context.first_message)

        create_cmd = CreateSessionCommand(
            project_path=effective_path,
            title=f"Discord: {display_name}",
            origin=InputOrigin.DISCORD.value,
            channel_metadata=channel_metadata,  # type: ignore[arg-type]
            session_metadata=session_meta,
            auto_command=auto_command,
        )
        result = await get_command_service().create_session(create_cmd)
        session_id = str(result.get("session_id", ""))
        if not session_id:
            logger.error("Discord session creation returned empty session_id")
            return None
        return await db.get_session(session_id)

    async def _update_session_discord_metadata(self, session: Session, routing_ids: _DiscordRoutingIds) -> Session:
        discord_meta = session.get_metadata().get_ui().get_discord()
        changed = False

        if discord_meta.user_id != routing_ids.user_id:
            discord_meta.user_id = routing_ids.user_id
            changed = True
        if routing_ids.guild_id is not None and discord_meta.guild_id != routing_ids.guild_id:
            discord_meta.guild_id = routing_ids.guild_id
            changed = True
        if routing_ids.channel_id is not None and discord_meta.channel_id != routing_ids.channel_id:
            discord_meta.channel_id = routing_ids.channel_id
            changed = True
        if routing_ids.thread_id is not None and discord_meta.thread_id != routing_ids.thread_id:
            discord_meta.thread_id = routing_ids.thread_id
            changed = True

        if not changed:
            return session

        await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
        return (await db.get_session(session.session_id)) or session

    async def _resolve_destination_channel(
        self,
        session: Session,
        *,
        metadata: MessageMetadata | None = None,
    ) -> object:
        if self._client is None:
            raise AdapterError("Discord adapter not started")

        metadata_channel_id = (
            self._parse_optional_int(metadata.channel_id) if metadata and metadata.channel_id else None
        )
        discord_meta = session.get_metadata().get_ui().get_discord()
        destination_id = metadata_channel_id or discord_meta.thread_id or discord_meta.channel_id
        if destination_id is None:
            raise AdapterError(f"Session {session.session_id} missing discord channel mapping")

        channel = await self._get_channel(destination_id)
        if channel is None:
            # Channel was deleted from Discord — clear stale metadata so we stop retrying
            logger.warning(
                "Discord channel %s not found for session %s, clearing stale metadata",
                destination_id,
                session.session_id,
            )
            discord_meta.thread_id = None
            discord_meta.channel_id = None
            discord_meta.output_message_id = None
            discord_meta.thread_topper_message_id = None
            await db.update_session(session.session_id, adapter_metadata=session.adapter_metadata)
            raise AdapterError(f"Discord channel {destination_id} not found (metadata cleared)")
        return channel

    async def _fetch_destination_message(
        self,
        session: Session,
        message_id: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> object:
        channel = await self._resolve_destination_channel(session, metadata=metadata)
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
