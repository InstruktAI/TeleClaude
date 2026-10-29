"""Input handling mixin for Discord adapter.

Downloads a Discord message's voice and file attachments and dispatches them to an already-resolved
session. Callers are the forum entry in `forum_sessions.py` and the conversation turns in
`conversation_turns.py`.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
from teleclaude.adapters.discord.inbound_continuity import report_refusal_of
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.file_handler import sanitize_filename
from teleclaude.core.inbound import resolve_binding_key
from teleclaude.core.integration.discord_inbound_cursor import PART_IDENTITY_TEMPLATE
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.core.shutdown_drain import ShutdownRefusal
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand

logger = get_logger(__name__)

VOICE_DOWNLOAD_EVENT = "discord_voice_downloaded"
VOICE_DOWNLOAD_SIZE_MISMATCH_EVENT = "discord_voice_download_size_mismatch"
_ID_FIELD = "id"
_USER_ID_FIELD = "user_id"
_AUTHOR_ATTR = "author"
_NO_TEXT = ""
# Each audio attachment of a message is downloaded to a file of its own while it awaits transcription.
_VOICE_TEMP_FILE_TEMPLATE = "voice_{part}{ext}"


class InputHandlersMixin:
    """Mixin downloading Discord message attachments and dispatching them to a resolved session for DiscordAdapter.

    Required host attributes:
    - _require_async_callable(fn, *, label) -> Callable
    - _discord_actor_name(author, user_id) -> str
    - _discord_actor_avatar_url(author) -> str | None
    - task_registry: TaskRegistry | None (assigned by DiscordAdapter)
    - answer_refusal_of(session_id, work) and answer_shutdown_refusal(session_id) (async; from UiAdapter)
    """

    if TYPE_CHECKING:

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> AsyncDiscordCallable: ...

        @staticmethod
        def _discord_actor_name(author: object, user_id: str) -> str: ...

        @staticmethod
        def _discord_actor_avatar_url(author: object) -> str | None: ...

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

    @staticmethod
    def _attachment_part_identity(message: object, attachment: object, index: int) -> str | None:
        """The provider identity of one attachment of a message: the message id completed by the attachment's own.

        A message's parts are not duplicates of each other, and a redelivered message deduplicates per part.
        """
        message_id = str(getattr(message, "id", _NO_TEXT)).strip()
        if not message_id:
            return None
        return PART_IDENTITY_TEMPLATE.format(message_id=message_id, part_id=getattr(attachment, "id", None) or index)

    async def _process_attachment(
        self,
        session: Session,
        attachment: object,
        index: int,
        caption: str | None,
        actor_id: str | None,
        source_message_id: str | None = None,
        recovered_at: datetime | None = None,
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
                origin=InputOrigin.DISCORD.value,
                actor_id=actor_id,
                source_message_id=source_message_id,
                recovered_posted_at=recovered_at,
            )
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

    async def _dispatch_voice_attachment(
        self,
        session: Session,
        message: object,
        attachment: object,
        *,
        recovered_at: datetime | None = None,
        retain_refusal: bool = False,
    ) -> asyncio.Task[object] | None:
        """Download a voice/audio attachment and dispatch it for transcription to ``session``.

        The transcription runs as a task of its own, returned so a caller that must know when the input has
        been accepted can wait for it; the other callers ignore it. ``None`` when the download failed.

        A draining refusal is answered to the sender. A caller whose place is recovered after the restart sets
        ``retain_refusal``: the task then returns the refusal as its outcome and sends no notice, so the
        message stays unprocessed.
        """
        recoverable_errors = self._discord_errors()
        message_id = str(getattr(message, "id", ""))
        part_identity = self._attachment_part_identity(message, attachment, 0)

        # Derive file extension from the attachment filename or default to .ogg
        filename = getattr(attachment, "filename", None) or "voice.ogg"
        ext = Path(filename).suffix or ".ogg"

        temp_dir = Path(tempfile.gettempdir()) / "teleclaude_voice"
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / _VOICE_TEMP_FILE_TEMPLATE.format(
            part=sanitize_filename(part_identity or message_id), ext=ext
        )

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
                source_message_id=part_identity,
                recovered_posted_at=recovered_at,
            )
            registry = getattr(self, "task_registry", None)
            if registry is None:
                raise RuntimeError("Discord voice handling requires task_registry")
            handling = get_command_service().handle_voice(cmd)
            transcription: asyncio.Task[object] = registry.spawn(
                report_refusal_of(handling) if retain_refusal else self.answer_refusal_of(session.session_id, handling),  # type: ignore[attr-defined]
                name=f"voice-{message_id}",
            )
            return transcription
        except recoverable_errors as exc:
            error_msg = str(exc) if str(exc).strip() else "Unknown error"
            logger.error("Failed to process Discord voice message: %s", error_msg, exc_info=True)
        return None

    async def _dispatch_file_attachments(
        self,
        session: Session,
        message: object,
        attachments: list[object],
        *,
        recovered_at: datetime | None = None,
        retain_refusal: bool = False,
    ) -> None:
        """Download file/image attachments and dispatch them for processing to ``session``.

        A draining refusal is answered to the sender. A caller whose place is recovered after the restart sets
        ``retain_refusal``: the refusal is raised without a notice, so the message stays unprocessed.
        """
        recoverable_errors = self._discord_errors()

        # Get text caption for the first attachment only (to avoid duplication)
        caption = getattr(message, "content", None)
        sender_id = str(getattr(getattr(message, _AUTHOR_ATTR, None), _ID_FIELD, None) or _NO_TEXT).strip()
        sender_key = resolve_binding_key(InputOrigin.DISCORD.value, {_USER_ID_FIELD: sender_id}) if sender_id else None
        if not isinstance(caption, str) or not caption.strip():
            caption = None

        for index, attachment in enumerate(attachments):
            try:
                await self._process_attachment(
                    session,
                    attachment,
                    index,
                    caption,
                    sender_key,
                    self._attachment_part_identity(message, attachment, index),
                    recovered_at,
                )
            except ShutdownRefusal:
                if retain_refusal:
                    raise
                await self.answer_shutdown_refusal(session.session_id)  # type: ignore[attr-defined]
                return
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
