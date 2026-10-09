"""Private chat handlers mixin for Telegram adapter.

Carries a private chat's turns to the conversation seam: the start parameter
or a message that is exactly an entry identifier, the bare start link, and
ordinary text, voice and files. The seam decides where each goes; this mixin
supplies the chat's key, its delivery into a session, its reply, and the
invitation binding of a Telegram account.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from telegram import Update, User
from telegram.ext import ContextTypes

import teleclaude.core.identity as identity_module
from teleclaude.cli.config_handlers import get_person_config, save_person_config
from teleclaude.config.schema import MessagingChannel, TelegramCreds
from teleclaude.core import command_registry
from teleclaude.core.endpoints import EntryIdentifier, parse_entry_identifier
from teleclaude.core.help_desk_relay import AdminReply
from teleclaude.core.inbound import (
    BindOutcome,
    ConversationRef,
    ConversationTurn,
    EntryGesture,
    TurnCreation,
    TurnModality,
    resolve_binding_key,
)
from teleclaude.core.inbound.conversation import ConversationOutcome, handle_conversation_turn
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import Session, SessionEntryPoint, TelegramAdapterMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import ProcessMessageCommand

from .input_handlers import ConversationInputDecision, ConversationInputReason, ConversationModality

if TYPE_CHECKING:
    from typing import Protocol

    from teleclaude.core.command_service import CommandService
    from teleclaude.core.models import MessageMetadata

    class _PrivateHandlersHost(Protocol):
        _metadata: Callable[..., MessageMetadata]
        _dispatch_command: Callable[
            [
                Session,
                str | None,
                MessageMetadata,
                str,
                Mapping[str, object],
                Callable[[], Coroutine[object, object, object]],
            ],
            Coroutine[object, object, object],
        ]


logger = get_logger(__name__)

_KEY_FIELD = "user_id"
_TELEGRAM_USER_ID_FIELD = "telegram_user_id"
_PLATFORM_FIELD = "platform"
_CHAT_TYPE_FIELD = "chat_type"
# A start command carries no message text of its own.
_NO_TEXT = ""
_PRIVATE_CHAT_TYPE = "private"
_UNKNOWN_USER_NAME = "unknown"
_PROCESS_MESSAGE_EVENT = "process_message"
_ACCEPTED_OUTCOMES = frozenset(
    {ConversationOutcome.DELIVERED, ConversationOutcome.SESSION_STARTED, ConversationOutcome.RELAY_ANSWERED}
)


def get_command_service() -> CommandService:
    """Delegate to the global command-service registry at call time.

    Keeping this local wrapper preserves both test seams:
    - patching `teleclaude.core.command_registry.get_command_service`
    - patching `teleclaude.adapters.telegram.private_handlers.get_command_service`
    """
    return command_registry.get_command_service()


def _is_private_chat_session(session: Session) -> bool:
    """A session of the private chat, not one of the user's supergroup topics."""
    return TelegramAdapterMetadata.from_dict(session.get_origin_section(InputOrigin.TELEGRAM.value)).topic_id is None


def telegram_conversation(user_id: int) -> ConversationRef:
    """A Telegram private chat: this computer's bot's conversation with one user."""
    return ConversationRef(
        origin=InputOrigin.TELEGRAM,
        key_field=_KEY_FIELD,
        key=str(user_id),
        reaches_every_computer=False,
        refine=_is_private_chat_session,
    )


def _creation(user_id: int) -> TurnCreation:
    return TurnCreation(
        entry_point=SessionEntryPoint.TELEGRAM,
        origin_metadata={
            _KEY_FIELD: user_id,
            _TELEGRAM_USER_ID_FIELD: user_id,
            _PLATFORM_FIELD: InputOrigin.TELEGRAM.value,
            _CHAT_TYPE_FIELD: _PRIVATE_CHAT_TYPE,
        },
    )


async def _no_content(_session: Session) -> None:
    """An entry gesture carries nothing to deliver."""


def _bind_telegram_invite(person_slug: str, user: User) -> BindOutcome:
    """Bind the Telegram account to the invited person, unless another account holds the invitation."""
    person_config = get_person_config(person_slug)
    bound = person_config.creds.telegram.user_id if person_config.creds.telegram else None
    if bound:
        return BindOutcome.ACCEPTED if str(bound) == str(user.id) else BindOutcome.CONFLICT
    person_config.creds.telegram = TelegramCreds(
        user_id=user.id, user_name=user.username or user.first_name or _UNKNOWN_USER_NAME
    )
    save_person_config(person_slug, person_config)
    return BindOutcome.ACCEPTED


def _relay_reply(update: Update) -> AdminReply | None:
    """What a private message answers when it replies to one of this bot's messages."""
    message = update.effective_message
    chat = update.effective_chat
    replied = message.reply_to_message if message is not None else None
    if message is None or chat is None or replied is None or replied.from_user is None or not replied.from_user.is_bot:
        return None
    user = update.effective_user
    return AdminReply(
        channel=MessagingChannel.TELEGRAM,
        target=str(chat.id),
        replied_message_id=str(replied.message_id),
        admin_message_id=str(message.message_id),
        admin_name=(user.full_name if user is not None else None) or _UNKNOWN_USER_NAME,
    )


class PrivateHandlersMixin:
    """Mixin providing private-chat handlers for TelegramAdapter.

    Required from host class:
    - _metadata(**kwargs) -> MessageMetadata
    - _dispatch_command(session, message_id, metadata, event, payload, fn) -> None
    """

    async def _route_private_turn(
        self,
        update: Update,
        *,
        text: str,
        gesture: EntryGesture,
        identifier: EntryIdentifier | None,
        deliver: Callable[[Session], Awaitable[None]],
        modality: TurnModality,
        relay_reply: AdminReply | None = None,
    ) -> ConversationOutcome:
        """Hand one private-chat turn to the conversation seam."""
        assert update.effective_user is not None
        assert update.effective_message is not None
        user = update.effective_user
        message = update.effective_message
        user_id = str(user.id)

        async def _reply(reply_text: str) -> None:
            await message.reply_text(reply_text)

        async def _bind(person_slug: str) -> BindOutcome:
            return _bind_telegram_invite(person_slug, user)

        turn = ConversationTurn(
            conversation=telegram_conversation(user.id),
            sender=identity_module.get_identity_resolver().resolve(
                InputOrigin.TELEGRAM.value, {_KEY_FIELD: user_id, _TELEGRAM_USER_ID_FIELD: user_id}
            ),
            text=text,
            gesture=gesture,
            identifier=identifier,
            creation=_creation(user.id),
            deliver=deliver,
            reply=_reply,
            bind_invite=_bind,
            modality=modality,
            relay_reply=relay_reply,
        )
        return await handle_conversation_turn(turn)

    async def _handle_private_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start: the start parameter is an entry; a bare start is the entry gesture."""
        payload = context.args[0] if context.args else None
        identifier = parse_entry_identifier(payload) if payload is not None else None
        if payload is None:
            gesture = EntryGesture.BARE
        elif identifier is None:
            gesture = EntryGesture.UNRESOLVABLE
        else:
            gesture = EntryGesture.IDENTIFIER
        await self._route_private_turn(
            update,
            text=_NO_TEXT,
            gesture=gesture,
            identifier=identifier,
            deliver=_no_content,
            modality=TurnModality.TEXT,
        )

    async def _handle_private_text(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages in private chats."""
        assert update.effective_user is not None
        assert update.effective_message is not None
        decision = ConversationInputDecision(
            ConversationModality.TEXT,
            str(update.effective_message.message_id),
        )
        try:
            await self._route_private_text(update, decision)
        except asyncio.CancelledError as error:
            decision.reject_for_error(error)
            raise
        except Exception as error:
            decision.reject_for_error(error)
            raise
        decision.reject_if_unreported()

    async def _route_private_text(self, update: Update, decision: ConversationInputDecision) -> None:
        """Route one supported text message after its decision record is armed."""
        assert update.effective_user is not None
        assert update.effective_message is not None

        user_id = str(update.effective_user.id)
        text = update.effective_message.text or ""
        msg_id = str(update.effective_message.message_id)
        binding_key = resolve_binding_key(InputOrigin.TELEGRAM.value, {_KEY_FIELD: user_id})
        identifier = parse_entry_identifier(text)

        async def _dispatch(session: Session) -> None:
            decision.bind_session(session)
            host = cast("_PrivateHandlersHost", self)
            sender = identity_module.get_identity_resolver().resolve(InputOrigin.TELEGRAM.value, {_KEY_FIELD: user_id})
            cmd = ProcessMessageCommand(
                session_id=session.session_id,
                text=text,
                origin=InputOrigin.TELEGRAM.value,
                text_kind=TranscriptEntryKind.ORDINARY,
                source_feature=InjectedTextSourceFeature.TELEGRAM,
                occurrence_key=msg_id,
                actor_id=binding_key,
                actor_name=sender.person_name or binding_key,
                request_id=msg_id,
                source_message_id=msg_id,
            )
            await host._dispatch_command(
                session,
                msg_id,
                host._metadata(),
                _PROCESS_MESSAGE_EVENT,
                cmd.to_payload(),
                lambda: get_command_service().process_message(cmd),
            )

        outcome = await self._route_private_turn(
            update,
            text=text,
            gesture=EntryGesture.IDENTIFIER if identifier is not None else EntryGesture.NONE,
            identifier=identifier,
            deliver=_dispatch,
            modality=TurnModality.TEXT,
            relay_reply=_relay_reply(update),
        )
        if outcome in _ACCEPTED_OUTCOMES:
            decision.accept()
        else:
            decision.reject(ConversationInputReason.NO_ENDPOINT)
