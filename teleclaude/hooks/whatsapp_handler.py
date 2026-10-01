"""Built-in internal handler for WhatsApp webhook events.

Carries each WhatsApp message to the conversation seam: a message that is
exactly an entry identifier is an entry, anything else an ordinary turn. The
seam decides where it goes; this handler supplies the number's key, the local
delivery of text and media, the reply, and the invitation binding of a number.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.cli.config_handlers import get_person_config, save_person_config
from teleclaude.config import config
from teleclaude.config.schema import MessagingChannel, WhatsAppCreds
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.endpoints import parse_entry_identifier, platform_help_desk_folder
from teleclaude.core.help_desk_relay import AdminReply
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.inbound import (
    BindOutcome,
    ConversationRef,
    ConversationTurn,
    EntryGesture,
    InboundSessionPolicy,
    TurnCreation,
    TurnModality,
    resolve_or_create_bound_session,
)
from teleclaude.core.inbound.adoption import WHATSAPP_KEY_FIELD
from teleclaude.core.inbound.conversation import ConversationOutcome, handle_conversation_turn
from teleclaude.core.inbound_media import download_whatsapp_media, is_voice_event
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import (
    AgentDispatchMode,
    MessageMetadata,
    Session,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.hooks.normalizers.whatsapp import CONTEXT_MESSAGE_ID_PROPERTY
from teleclaude.hooks.webhook_models import Contract, HookEvent
from teleclaude.services.whatsapp import send_whatsapp_message
from teleclaude.types.commands import (
    CreateSessionCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    InternalCommand,
    ProcessMessageCommand,
)
from teleclaude.types.media import MediaProvider, MediaRef

logger = get_logger(__name__)

_TEXT_EVENT_TYPE = "message.text"
_PHONE_NUMBER_PROPERTY = "phone_number"
_MESSAGE_ID_PROPERTY = "message_id"
_TEXT_PROPERTY = "text"
_MEDIA_ID_PROPERTY = "media_id"
_MIME_TYPE_PROPERTY = "mime_type"
_PLATFORM_FIELD = "platform"
_LAST_RECEIVED_MESSAGE_ID_FIELD = "last_received_message_id"
_LAST_CUSTOMER_MESSAGE_AT_FIELD = "last_customer_message_at"
_ACTOR_ID_TEMPLATE = "whatsapp:{phone_number}"
_PROCESS_MESSAGE_COMMAND = "process_message"
_HANDLE_VOICE_COMMAND = "handle_voice"
_HANDLE_FILE_COMMAND = "handle_file"
_ACTOR_ID_PAYLOAD_KEY = "actor_id"
_ACTOR_NAME_PAYLOAD_KEY = "actor_name"
_ACTOR_AVATAR_URL_PAYLOAD_KEY = "actor_avatar_url"
_MISSING_PHONE_EVENT = "whatsapp_event_missing_phone_number"
_ADAPTER_DISABLED_EVENT = "whatsapp_event_adapter_disabled"
_REPLY_FAILED_EVENT = "whatsapp_conversation_reply_failed"
_BEFORE_CUTOVER_CREATE_REFUSED_EVENT = "whatsapp_before_cutover_create_refused"
_SESSION_ID_FIELD = "session_id"
_THINKING_MODE = "slow"
_REPLY_PURPOSE = "reply"
_INBOUND_PURPOSE = "inbound"
_NO_TEXT = ""


def _normalize_phone_number(phone_number: str | None) -> str:
    """Normalize a phone number to digits only."""
    if not phone_number:
        return ""
    return "".join(ch for ch in str(phone_number) if ch.isdigit())


def whatsapp_conversation(phone_number: str) -> ConversationRef:
    """A WhatsApp conversation: one number, whose messages every computer receives."""
    return ConversationRef(
        origin=InputOrigin.WHATSAPP,
        key_field=WHATSAPP_KEY_FIELD,
        key=phone_number,
        reaches_every_computer=True,
    )


def _received_metadata(
    phone_number: str, message_id: str, timestamp: str
) -> dict[str, object]:  # guard: loose-dict - WhatsApp origin section delta
    """The WhatsApp origin fields a received message updates, wherever its session runs.

    The last customer message time decides whether a reply may be free text.
    """
    return {
        WHATSAPP_KEY_FIELD: phone_number,
        _LAST_RECEIVED_MESSAGE_ID_FIELD: message_id,
        _LAST_CUSTOMER_MESSAGE_AT_FIELD: timestamp,
    }


async def _update_whatsapp_session_metadata(
    session: Session,
    *,
    phone_number: str,
    message_id: str,
    timestamp: str,
) -> None:
    await db.update_origin_metadata(
        session.session_id, InputOrigin.WHATSAPP.value, _received_metadata(phone_number, message_id, timestamp)
    )


async def _dispatch_whatsapp_command(
    *,
    session: Session,
    message_id: str | None,
    command_name: str,
    payload: dict[str, object],  # guard: loose-dict - Command payload mirrors typed command .to_payload().
    handler: Callable[[], Awaitable[object]],
) -> None:
    command_service = get_command_service()
    client = getattr(command_service, "client", None)
    adapters = getattr(client, "adapters", None)
    if not isinstance(adapters, dict):
        await handler()
        return

    adapter = adapters.get(InputOrigin.WHATSAPP.value)
    if not isinstance(adapter, UiAdapter):
        await handler()
        return

    payload_actor_id = (
        str(payload.get(_ACTOR_ID_PAYLOAD_KEY)).strip() if payload.get(_ACTOR_ID_PAYLOAD_KEY) is not None else None
    )
    payload_actor_name = (
        str(payload.get(_ACTOR_NAME_PAYLOAD_KEY)).strip() if payload.get(_ACTOR_NAME_PAYLOAD_KEY) is not None else None
    )
    payload_actor_avatar_url = (
        str(payload.get(_ACTOR_AVATAR_URL_PAYLOAD_KEY)).strip()
        if payload.get(_ACTOR_AVATAR_URL_PAYLOAD_KEY) is not None
        else None
    )
    metadata = MessageMetadata(
        origin=InputOrigin.WHATSAPP.value,
        platform_message_id=message_id or None,
        actor_id=payload_actor_id or None,
        actor_name=payload_actor_name or None,
        actor_avatar_url=payload_actor_avatar_url or None,
    )
    await adapter.dispatch_command(
        session,
        message_id,
        metadata,
        command_name,
        payload,
        handler,
    )


def _text_command(
    session_id: str, phone_number: str, message_id: str, text: str, timestamp: str
) -> ProcessMessageCommand:
    return ProcessMessageCommand(
        session_id=session_id,
        text=text,
        origin=InputOrigin.WHATSAPP.value,
        text_kind=TranscriptEntryKind.ORDINARY,
        source_feature=InjectedTextSourceFeature.WHATSAPP,
        occurrence_key=message_id or None,
        actor_id=_ACTOR_ID_TEMPLATE.format(phone_number=phone_number),
        actor_name=phone_number,
        source_message_id=message_id or None,
        origin_metadata=_received_metadata(phone_number, message_id, timestamp),
    )


def _media_ref(event: HookEvent, phone_number: str) -> MediaRef | None:
    media_id = str(event.properties.get(_MEDIA_ID_PROPERTY) or "")
    if not media_id:
        return None
    mime_type = str(event.properties.get(_MIME_TYPE_PROPERTY) or "") or None
    return MediaRef(
        provider=MediaProvider.WHATSAPP,
        media_id=media_id,
        mime_type=mime_type,
        sender=phone_number,
        event_type=event.type,
    )


def _media_command(
    session_id: str, phone_number: str, message_id: str, media_ref: MediaRef, timestamp: str
) -> InternalCommand:
    """The command that hands referenced media to a session; its host fetches the media itself."""
    if is_voice_event(media_ref.event_type):
        return HandleVoiceCommand(
            session_id=session_id,
            file_path="",
            origin=InputOrigin.WHATSAPP.value,
            message_id=message_id or None,
            actor_id=_ACTOR_ID_TEMPLATE.format(phone_number=phone_number),
            actor_name=phone_number,
            origin_metadata=_received_metadata(phone_number, message_id, timestamp),
            media_ref=media_ref,
        )
    return HandleFileCommand(
        session_id=session_id,
        file_path=_NO_TEXT,
        filename=_NO_TEXT,
        media_ref=media_ref,
        origin=InputOrigin.WHATSAPP.value,
        actor_id=_ACTOR_ID_TEMPLATE.format(phone_number=phone_number),
    )


async def _deliver_text(session: Session, phone_number: str, message_id: str, text: str, timestamp: str) -> None:
    cmd = _text_command(session.session_id, phone_number, message_id, text, timestamp)
    await _dispatch_whatsapp_command(
        session=session,
        message_id=message_id or None,
        command_name=_PROCESS_MESSAGE_COMMAND,
        payload=cmd.to_payload(),
        handler=lambda: get_command_service().process_message(cmd),
    )


async def _deliver_media(session: Session, phone_number: str, message_id: str, media_ref: MediaRef) -> None:
    local_path = await download_whatsapp_media(
        media_ref.media_id,
        media_ref.mime_type,
        phone_number,
        session_id=session.session_id,
        event_type=media_ref.event_type,
    )
    if is_voice_event(media_ref.event_type):
        voice = HandleVoiceCommand(
            session_id=session.session_id,
            file_path=str(local_path),
            origin=InputOrigin.WHATSAPP.value,
            message_id=message_id or None,
            actor_id=_ACTOR_ID_TEMPLATE.format(phone_number=phone_number),
            actor_name=phone_number,
        )
        await _dispatch_whatsapp_command(
            session=session,
            message_id=message_id or None,
            command_name=_HANDLE_VOICE_COMMAND,
            payload=voice.to_payload(),
            handler=lambda: get_command_service().handle_voice(voice),
        )
        return
    upload = HandleFileCommand(
        session_id=session.session_id,
        file_path=str(local_path),
        filename=local_path.name,
        file_size=local_path.stat().st_size,
        origin=InputOrigin.WHATSAPP.value,
        actor_id=_ACTOR_ID_TEMPLATE.format(phone_number=phone_number),
    )
    await _dispatch_whatsapp_command(
        session=session,
        message_id=message_id or None,
        command_name=_HANDLE_FILE_COMMAND,
        payload=upload.to_payload(),
        handler=lambda: get_command_service().handle_file(upload),
    )


async def _resolve_or_create_session_before_cutover(phone_number: str) -> Session | None:
    """Find or create the number's session as every computer does until shared routing is activated."""

    async def _find() -> Session | None:
        sessions = await db.get_sessions_by_origin_metadata(
            InputOrigin.WHATSAPP.value, WHATSAPP_KEY_FIELD, phone_number
        )
        return sessions[0] if sessions else None

    async def _create() -> Session | None:
        cmd = CreateSessionCommand(
            project_path=str(platform_help_desk_folder()),
            origin=InputOrigin.WHATSAPP.value,
            origin_metadata={WHATSAPP_KEY_FIELD: phone_number, _PLATFORM_FIELD: InputOrigin.WHATSAPP.value},
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                thinking_mode=_THINKING_MODE,
                dispatch_mode=AgentDispatchMode.AUTOMATIC,
            ),
            entry_point=SessionEntryPoint.WHATSAPP,
        )
        try:
            result = await get_command_service().create_session(cmd)
        except ValueError as exc:
            logger.warning(_BEFORE_CUTOVER_CREATE_REFUSED_EVENT, error=str(exc))
            return None
        session_id = result.get(_SESSION_ID_FIELD)
        return await db.get_session(str(session_id)) if session_id else None

    async def _reconcile(session: Session) -> Session:
        return session

    session, _is_new = await resolve_or_create_bound_session(
        InboundSessionPolicy(find=_find, create=_create, reconcile=_reconcile)
    )
    return session


def _bind_whatsapp_invite(person_slug: str, phone_number: str) -> BindOutcome:
    """Bind the number to the invited person, unless another number holds the invitation."""
    person_config = get_person_config(person_slug)
    bound = person_config.creds.whatsapp.phone_number if person_config.creds.whatsapp else None
    if bound:
        return BindOutcome.ACCEPTED if _normalize_phone_number(bound) == phone_number else BindOutcome.CONFLICT
    person_config.creds.whatsapp = WhatsAppCreds(phone_number=phone_number)
    save_person_config(person_slug, person_config)
    return BindOutcome.ACCEPTED


async def _reply(phone_number: str, text: str) -> None:
    """Send the seam's reply from this computer's WhatsApp credentials."""
    if not config.whatsapp.enabled:
        logger.warning(_ADAPTER_DISABLED_EVENT, purpose=_REPLY_PURPOSE)
        return
    try:
        await send_whatsapp_message(
            phone_number,
            text,
            phone_number_id=config.whatsapp.phone_number_id,
            access_token=config.whatsapp.access_token,
            api_version=config.whatsapp.api_version,
        )
    except (RuntimeError, ValueError) as exc:
        logger.warning(_REPLY_FAILED_EVENT, error=str(exc))


def _relay_reply(event: HookEvent, phone_number: str, message_id: str) -> AdminReply | None:
    """What a message answers when it replies to an earlier message of the conversation."""
    replied_id = str(event.properties.get(CONTEXT_MESSAGE_ID_PROPERTY) or _NO_TEXT)
    if not replied_id or not message_id:
        return None
    sender = get_identity_resolver().resolve(InputOrigin.WHATSAPP.value, {WHATSAPP_KEY_FIELD: phone_number})
    return AdminReply(
        channel=MessagingChannel.WHATSAPP,
        target=phone_number,
        replied_message_id=replied_id,
        admin_message_id=message_id,
        admin_name=(sender.person_name or _NO_TEXT).strip() or phone_number,
    )


async def handle_whatsapp_event(event: HookEvent, contract: Contract) -> None:
    """Hand one normalized WhatsApp message to the conversation seam."""
    del contract
    phone_number = _normalize_phone_number(str(event.properties.get(_PHONE_NUMBER_PROPERTY) or ""))
    if not phone_number:
        logger.warning(_MISSING_PHONE_EVENT)
        return
    if not config.whatsapp.enabled:
        logger.info(_ADAPTER_DISABLED_EVENT, purpose=_INBOUND_PURPOSE)
    message_id = str(event.properties.get(_MESSAGE_ID_PROPERTY) or "")
    is_text = event.type == _TEXT_EVENT_TYPE
    text = str(event.properties.get(_TEXT_PROPERTY) or "") if is_text else ""
    media_ref = None if is_text else _media_ref(event, phone_number)
    if not is_text and media_ref is None:
        return
    identifier = parse_entry_identifier(text) if is_text else None

    async def _deliver(session: Session) -> None:
        await _update_whatsapp_session_metadata(
            session, phone_number=phone_number, message_id=message_id, timestamp=event.timestamp
        )
        if media_ref is not None:
            await _deliver_media(session, phone_number, message_id, media_ref)
        elif text:
            await _deliver_text(session, phone_number, message_id, text, event.timestamp)

    def _remote(session_id: str) -> InternalCommand | None:
        if media_ref is not None:
            return _media_command(session_id, phone_number, message_id, media_ref, event.timestamp)
        return _text_command(session_id, phone_number, message_id, text, event.timestamp) if text else None

    async def _bind(person_slug: str) -> BindOutcome:
        return _bind_whatsapp_invite(person_slug, phone_number)

    async def _send_reply(reply_text: str) -> None:
        await _reply(phone_number, reply_text)

    outcome = await handle_conversation_turn(
        ConversationTurn(
            conversation=whatsapp_conversation(phone_number),
            sender=get_identity_resolver().resolve(InputOrigin.WHATSAPP.value, {WHATSAPP_KEY_FIELD: phone_number}),
            text=text,
            gesture=EntryGesture.IDENTIFIER if identifier is not None else EntryGesture.NONE,
            identifier=identifier,
            creation=TurnCreation(
                entry_point=SessionEntryPoint.WHATSAPP,
                origin_metadata={
                    **_received_metadata(phone_number, message_id, event.timestamp),
                    _PLATFORM_FIELD: InputOrigin.WHATSAPP.value,
                },
            ),
            deliver=_deliver,
            reply=_send_reply,
            bind_invite=_bind,
            remote_command=_remote,
            modality=TurnModality.TEXT if is_text else TurnModality.MEDIA,
            relay_reply=_relay_reply(event, phone_number, message_id) if is_text else None,
        )
    )
    if outcome is ConversationOutcome.BEFORE_CUTOVER:
        session = await _resolve_or_create_session_before_cutover(phone_number)
        if session is not None:
            await _deliver(session)
