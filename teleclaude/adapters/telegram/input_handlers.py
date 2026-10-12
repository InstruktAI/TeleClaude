"""Input handlers mixin for Telegram adapter.

Handles user input: voice messages, file attachments, and error handling.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Document, PhotoSize, Update
from telegram.ext import ContextTypes

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.file_handler import sanitize_filename
from teleclaude.core.inbound import EntryGesture, TurnModality, resolve_binding_key
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_utils import get_session_output_dir
from teleclaude.core.shutdown_drain import ShutdownRefusal
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.endpoints import EntryIdentifier
    from teleclaude.core.inbound.conversation import ConversationOutcome

    class _InputHandlersHost(Protocol):
        client: AdapterClient
        _processed_voice_messages: set[str]
        _metadata: Callable[..., MessageMetadata]
        send_message: Callable[..., Awaitable[str | None]]
        answer_shutdown_refusal: Callable[[str], Awaitable[None]]
        answer_refusal_of: Callable[[str, Awaitable[None]], Awaitable[None]]

        async def _route_private_turn(
            self,
            update: Update,
            *,
            text: str,
            gesture: EntryGesture,
            identifier: EntryIdentifier | None,
            deliver: Callable[[Session], Awaitable[None]],
            modality: TurnModality,
        ) -> ConversationOutcome: ...

        _dispatch_command: Callable[
            [Session, str | None, MessageMetadata, str, Mapping[str, object], Callable[[], Awaitable[object]]],
            Awaitable[object],
        ]
        task_registry: object


logger = get_logger(__name__)
_UPLOAD_PATH_REFUSED_EVENT = "upload_path_refused"
_USER_ID_FIELD = "user_id"
_NO_TEXT = ""
_VOICE_TEMP_DIR = "teleclaude_voice"
# Telegram voice notes are ogg/opus.
_VOICE_FILE_TEMPLATE = "voice_{message_id}.ogg"
_VOICE_TASK_TEMPLATE = "voice-{message_id}"
_ACTOR_ID_TEMPLATE = "telegram:{user_id}"
# A Telegram message id is unique only within its chat, so the sender's id completes the part identity.
_SOURCE_PART_TEMPLATE = "{user_id}:{message_id}"
_TASK_REGISTRY_ATTR = "task_registry"
_NO_TASK_REGISTRY_ERROR = "Telegram voice handling requires task_registry"
_VOICE_INPUT_FAILED_EVENT = "telegram_voice_input_failed"
_ATTACHMENT_INPUT_FAILED_EVENT = "telegram_attachment_input_failed"
_VOICE_DOWNLOAD_FAILED_REPLY = "❌ Failed to download voice message."
_UPLOAD_FAILED_TEMPLATE = "❌ Failed to upload {file_type}"
_DEFAULT_FILE_SUBDIR = "files"


class ConversationModality(StrEnum):
    """Supported conversational modalities at the Telegram boundary."""

    TEXT = "text"
    VOICE = "voice"
    DOCUMENT = "document"
    PHOTO = "photo"


class ConversationInputOutcome(StrEnum):
    """Terminal decisions for a supported Telegram input."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ConversationInputReason(StrEnum):
    """Closed reasons for Telegram input decisions."""

    CANCELLED = "cancelled"
    DELIVERY_FAILED = "delivery_failed"
    DISPATCHED = "dispatched"
    DUPLICATE = "duplicate"
    HANDLER_FAILED = "handler_failed"
    NO_ENDPOINT = "no_endpoint"
    SHUTDOWN_REFUSED = "shutdown_refused"
    UNSUPPORTED_INPUT = "unsupported_input"
    UPLOAD_PATH_REFUSED = "upload_path_refused"


class IncomingFileType(StrEnum):
    """Supported inbound file types."""

    DOCUMENT = "document"
    PHOTO = "photo"


FILE_SUBDIR: dict[IncomingFileType, str] = {
    IncomingFileType.DOCUMENT: "files",
    IncomingFileType.PHOTO: "photos",
}


def observe_conversation_input_decision(
    *,
    modality: ConversationModality,
    source_message_id: str,
    outcome: ConversationInputOutcome,
    reason: ConversationInputReason,
    session_id: str | None = None,
) -> None:
    """Record the terminal routing decision for one private Telegram input."""
    logger.info(
        "telegram_conversation_input_decided",
        origin="telegram",
        modality=modality.value,
        source_message_id=source_message_id,
        outcome=outcome.value,
        reason=reason.value,
        session_id=session_id,
    )


@dataclass
class ConversationInputDecision:
    """Record one correlated terminal decision for a supported handler turn."""

    modality: ConversationModality
    source_message_id: str
    session_id: str | None = None
    _recorded: bool = False

    def bind_session(self, session: Session) -> None:
        """Attach the resolved session to all later decisions."""
        self.session_id = session.session_id

    def accept(self) -> None:
        """Record successful dispatch."""
        self._record(ConversationInputOutcome.ACCEPTED, ConversationInputReason.DISPATCHED)

    def reject(self, reason: ConversationInputReason) -> None:
        """Record a rejected handler turn once."""
        self._record(ConversationInputOutcome.REJECTED, reason)

    def reject_for_error(self, error: Exception | asyncio.CancelledError) -> None:
        """Record failure before preserving the handler's propagation semantics."""
        if isinstance(error, asyncio.CancelledError):
            reason = ConversationInputReason.CANCELLED
        elif isinstance(error, ShutdownRefusal):
            reason = ConversationInputReason.SHUTDOWN_REFUSED
        else:
            reason = ConversationInputReason.HANDLER_FAILED
        self.reject(reason)

    def reject_if_unreported(self) -> None:
        """Close a supported handler turn that returned without dispatching."""
        self.reject(ConversationInputReason.UNSUPPORTED_INPUT)

    @property
    def recorded(self) -> bool:
        """Whether this handler turn has reached a terminal decision."""
        return self._recorded

    def _record(self, outcome: ConversationInputOutcome, reason: ConversationInputReason) -> None:
        if self._recorded:
            return
        observe_conversation_input_decision(
            modality=self.modality,
            source_message_id=self.source_message_id,
            outcome=outcome,
            reason=reason,
            session_id=self.session_id,
        )
        self._recorded = True


class InputHandlersMixin:
    """Mixin providing input handlers for TelegramAdapter.

    Required from host class:
    - client: AdapterClient
    - _processed_voice_messages: set[str]
    - _metadata(**kwargs: object) -> AdapterMetadata
    - _route_private_turn(update, ...) -> ConversationOutcome (the conversation seam)
    """

    # Abstract properties/attributes (declared for type hints)
    client: AdapterClient
    _processed_voice_messages: set[str]

    async def _observe_private_update(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Record private ingress before modality handlers decide how to route it."""
        message = update.effective_message
        if message is None:
            return
        modality = "text"
        if message.voice:
            modality = "voice"
        elif message.document:
            modality = "document"
        elif message.photo:
            modality = "photo"
        logger.info(
            "telegram_private_update_received",
            origin="telegram",
            modality=modality,
            source_message_id=str(message.message_id),
            chat_type="private",
        )

    async def _handle_voice_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice messages in private chats, including edited messages."""
        message = update.effective_message
        if message is None:
            return
        decision = ConversationInputDecision(ConversationModality.VOICE, str(message.message_id))
        try:
            await self._route_voice_message(update, decision)
        except asyncio.CancelledError as error:
            decision.reject_for_error(error)
            raise
        except Exception as error:
            decision.reject_for_error(error)
            raise
        decision.reject_if_unreported()

    async def _route_voice_message(self, update: Update, decision: ConversationInputDecision) -> None:
        """Route one supported voice message after its decision record is armed."""
        # Handle both regular messages and edited messages
        message = update.effective_message
        if not message or not update.effective_user:
            return

        # Check if we've already processed this message
        # For edited messages, include edit_date so each edit is unique
        is_edited = update.edited_message is not None
        edit_suffix = (
            f"edited:{message.edit_date}" if is_edited and message.edit_date else ("edited" if is_edited else "new")
        )
        dedup_key_str = f"{message.message_id}:{edit_suffix}"
        if dedup_key_str in self._processed_voice_messages:
            logger.debug("Skipping duplicate voice message: %s", dedup_key_str)
            decision.reject(ConversationInputReason.DUPLICATE)
            return

        # Mark as processed
        self._processed_voice_messages.add(dedup_key_str)

        # Limit set size to prevent memory growth (keep last 1000 message IDs)
        if len(self._processed_voice_messages) > 1000:
            oldest_str = min(self._processed_voice_messages)
            self._processed_voice_messages.remove(oldest_str)

        host = cast("_InputHandlersHost", self)
        voice = message.voice
        if not voice:
            decision.reject(ConversationInputReason.UNSUPPORTED_INPUT)
            return
        user = update.effective_user

        async def _deliver_voice(session: Session) -> None:
            decision.bind_session(session)
            voice_file = await voice.get_file()

            # Create temp file with .ogg extension (Telegram uses ogg/opus format)
            temp_dir = Path(tempfile.gettempdir()) / _VOICE_TEMP_DIR
            temp_dir.mkdir(exist_ok=True)
            temp_file_path = temp_dir / _VOICE_FILE_TEMPLATE.format(message_id=message.message_id)

            try:
                await voice_file.download_to_drive(temp_file_path)
                cmd = HandleVoiceCommand(
                    session_id=session.session_id,
                    file_path=str(temp_file_path),
                    duration=(
                        voice.duration.total_seconds()
                        if isinstance(voice.duration, timedelta)
                        else float(voice.duration)
                    ),
                    message_id=str(message.message_id),
                    message_thread_id=message.message_thread_id,
                    origin=host._metadata().origin,
                    actor_id=_ACTOR_ID_TEMPLATE.format(user_id=user.id),
                    actor_name=(
                        user.username or user.full_name or user.first_name or _ACTOR_ID_TEMPLATE.format(user_id=user.id)
                    ),
                    source_message_id=_SOURCE_PART_TEMPLATE.format(user_id=user.id, message_id=message.message_id),
                )
                registry = getattr(self, _TASK_REGISTRY_ATTR, None)
                if registry is None:
                    raise RuntimeError(_NO_TASK_REGISTRY_ERROR)
                registry.spawn(
                    host.answer_refusal_of(session.session_id, get_command_service().handle_voice(cmd)),
                    name=_VOICE_TASK_TEMPLATE.format(message_id=message.message_id),
                )
                decision.accept()
            except (OSError, RuntimeError, TypeError, ValueError):
                logger.error(_VOICE_INPUT_FAILED_EVENT, source_message_id=str(message.message_id))
                await host.send_message(
                    session,
                    _VOICE_DOWNLOAD_FAILED_REPLY,
                    metadata=MessageMetadata(parse_mode=None),
                )
                decision.reject(ConversationInputReason.DELIVERY_FAILED)

        await host._route_private_turn(
            update,
            text=_NO_TEXT,
            gesture=EntryGesture.NONE,
            identifier=None,
            deliver=_deliver_voice,
            modality=TurnModality.MEDIA,
        )
        decision.reject(ConversationInputReason.NO_ENDPOINT)

    async def _handle_file_attachment(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle file attachments in private chats, including edited messages."""
        message = update.message or update.edited_message
        if message is None:
            return
        modality = ConversationModality.DOCUMENT if message.document else ConversationModality.PHOTO
        decision = ConversationInputDecision(modality, str(message.message_id))
        try:
            await self._route_file_attachment(update, decision)
        except asyncio.CancelledError as error:
            decision.reject_for_error(error)
            raise
        except Exception as error:
            decision.reject_for_error(error)
            raise
        decision.reject_if_unreported()

    async def _route_file_attachment(self, update: Update, decision: ConversationInputDecision) -> None:
        """Route one supported document or photo after its decision record is armed."""
        # Handle both regular messages and edited messages
        message = update.message or update.edited_message
        if not message or not update.effective_user:
            return

        host = cast("_InputHandlersHost", self)

        # Get file object (either document or photo)
        file_obj: Document | PhotoSize | None = None
        file_name: str | None = None
        file_type: IncomingFileType | None = None

        if message.document:
            file_obj = message.document
            file_name = message.document.file_name or f"document_{message.message_id}"
            file_type = IncomingFileType.DOCUMENT
        elif message.photo:
            # Photos come as array, get largest one
            file_obj = message.photo[-1]  # PhotoSize, not Document
            file_name = f"photo_{message.message_id}.jpg"
            file_type = IncomingFileType.PHOTO

        if not file_obj or file_type is None or file_name is None:
            decision.reject(ConversationInputReason.UNSUPPORTED_INPUT)
            return
        # The sender names the file; it is reduced to a bare safe name before any write.
        safe_name = sanitize_filename(file_name)
        incoming_file = file_obj
        incoming_type = file_type
        sender_key = resolve_binding_key(InputOrigin.TELEGRAM.value, {_USER_ID_FIELD: str(update.effective_user.id)})
        source_part = _SOURCE_PART_TEMPLATE.format(user_id=update.effective_user.id, message_id=message.message_id)

        async def _deliver_file(session: Session) -> None:
            decision.bind_session(session)
            # Determine subdirectory based on file type
            subdir = FILE_SUBDIR.get(incoming_type, _DEFAULT_FILE_SUBDIR)
            session_workspace = get_session_output_dir(session.session_id) / subdir
            session_workspace.mkdir(parents=True, exist_ok=True)
            # The file must land inside this session's upload directory.
            upload_root = session_workspace.resolve()
            file_path = (upload_root / safe_name).resolve()
            if file_path.parent != upload_root:
                logger.warning(
                    _UPLOAD_PATH_REFUSED_EVENT,
                    session_id=session.session_id,
                    source_message_id=str(message.message_id),
                )
                decision.reject(ConversationInputReason.UPLOAD_PATH_REFUSED)
                return

            try:
                # Download file to session workspace
                telegram_file = await incoming_file.get_file()
                await telegram_file.download_to_drive(file_path)
                await get_command_service().handle_file(
                    HandleFileCommand(
                        session_id=session.session_id,
                        file_path=str(file_path),
                        filename=safe_name,
                        caption=message.caption.strip() if message.caption else None,
                        # Telegram may omit size; zero keeps the upload notice size-free.
                        file_size=incoming_file.file_size if incoming_file.file_size is not None else 0,
                        origin=InputOrigin.TELEGRAM.value,
                        actor_id=sender_key,
                        source_message_id=source_part,
                    )
                )
                decision.accept()
            except ShutdownRefusal:
                await host.answer_shutdown_refusal(session.session_id)
                decision.reject(ConversationInputReason.SHUTDOWN_REFUSED)
            except (OSError, RuntimeError, TypeError, ValueError):
                logger.error(_ATTACHMENT_INPUT_FAILED_EVENT, source_message_id=str(message.message_id))

                # Send user-friendly error message
                message_id = await host.send_message(
                    session,
                    _UPLOAD_FAILED_TEMPLATE.format(file_type=incoming_type),
                    metadata=host._metadata(),
                )
                if message_id:
                    await db.add_pending_deletion(session.session_id, InputOrigin.TELEGRAM.value, message_id)
                decision.reject(ConversationInputReason.DELIVERY_FAILED)

        await host._route_private_turn(
            update,
            text=_NO_TEXT,
            gesture=EntryGesture.NONE,
            identifier=None,
            deliver=_deliver_file,
            modality=TurnModality.MEDIA,
        )
        decision.reject(ConversationInputReason.NO_ENDPOINT)

    async def _handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors that occur in handlers."""
        logger.error(
            "telegram_update_handler_failed",
            update_type=type(update).__name__,
            error_type=type(context.error).__name__ if context.error else None,
            exc_info=context.error,
        )

    async def handle_file_attachment(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Public wrapper for inbound file routing."""
        await self._handle_file_attachment(update, context)
