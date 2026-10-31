"""Core person-addressed messaging service.

Resolves a person by slug and dispatches a message on their routed channel,
reusing the existing per-channel outbound send primitives
(``teleclaude.services.{telegram,discord,whatsapp,email}``) — no new
transport, per ``local/projects/teleclaude/spec/messaging`` (Person-addressed delivery).

The master sends (``local/projects/teleclaude/spec/messaging``): the fleet's unique
live master delivers every person-addressed message. A request made on another
computer is carried to the master over the computer-addressed relay, and the master's
outcome is the request's outcome; no other computer sends in its place.
"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPMethod, HTTPStatus
from pathlib import Path
from typing import Final

import httpx
from instrukt_ai_logging import get_logger
from pydantic import ValidationError
from redis.exceptions import RedisError

from teleclaude.api_models import PERSON_MESSAGE_PATH, PersonMessageRequest, PersonMessageResponse
from teleclaude.caller_identity import cleared_command_path
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.loader import load_global_config, load_person_config_for_entry
from teleclaude.config.machine import config
from teleclaude.config.schema import ConfigKind, MessagingChannel, PersonConfig
from teleclaude.config.validation import is_section_available
from teleclaude.constants import LOGIN_REQUIRED_DETAIL, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.db import db
from teleclaude.core.inbound.fleet import MasterUnavailability, observe_fleet_from_heartbeats
from teleclaude.core.integration.session_address import (
    SessionAddressMissed,
    resolve_session_conversation_url,
)
from teleclaude.core.person_message_recipients import (
    RecipientUnresolvableError as RecipientUnresolvableError,
)
from teleclaude.core.person_message_recipients import (
    resolve_person_message_recipients,
)
from teleclaude.core.relay_carrier import carry_request
from teleclaude.core.workflow_store.github_store import surface_github_question
from teleclaude.paths import PEOPLE_DIR
from teleclaude.services.discord import (
    DISCORD_MAX_MESSAGE_LENGTH,
    render_discord_backlink,
    send_discord_dm,
)
from teleclaude.services.email import send_email
from teleclaude.services.telegram import send_telegram_dm
from teleclaude.services.whatsapp import send_whatsapp_message
from teleclaude.types.relayed_response import RelayedResponse

logger = get_logger(__name__)

DEFAULT_EMAIL_SUBJECT = "TeleClaude message"
DISCORD_BACKLINK_MISS_LOG = "discord session backlink unavailable"
DISCORD_BACKLINK_BUILT_LOG = "discord session backlink built"
DISCORD_MESSAGE_TRUNCATED_LOG = "discord message truncated"
_GITHUB_QUESTION_SURFACE_FAILED = "github workflow question surface failed"
_ADMIN_MISSING_SLUG = "The platform admin has no addressable slug."
_ADMINS_UNREACHED = "No platform admin received the message: {failures}"
_CHANNEL_NOT_ENABLED = "The {channel} channel is not enabled on the master; it cannot carry this message."
_NO_LIVE_MASTER = "Person-addressed messages are sent by the mesh master, and no master is live."
_CONFLICTING_MASTERS = (
    "Person-addressed messages are sent by the mesh master, and several computers declare themselves master: "
    "{computers}."
)
_FLEET_UNOBSERVABLE = "Person-addressed messages are sent by the mesh master, and the fleet cannot be observed: {error}"
_NOT_THE_MASTER = (
    "Person-addressed messages are sent by the mesh master {owner}, and this computer is {computer}; nothing was sent."
)
_CARRIED_FILE_PATH_REFUSED = "A carried request names no path on the master; it carries the file's content."
_CARRIED_FILE_NAME_REFUSED = "A carried file needs a plain file name."
_NOT_A_FILE = "Not a file: {path}"
_CARRIED_RESPONSE_UNREADABLE = (
    "The master {owner} answered the carried message with a response this computer cannot read."
)
_JSON_CONTENT_TYPE = "application/json"
_JSON_DUMP_MODE = "json"
_COMPUTER_SEPARATOR = ", "
_DETAIL_FIELD = "detail"
_FAILURE_SEPARATOR = "; "
_RECIPIENT_DETAIL_SEPARATOR = ": "


class PersonNotFoundError(ValueError):
    """No addressable person resolves for the given slug."""


class ChannelCredentialError(ValueError):
    """The resolved channel has no usable credential for this person."""


class ChannelCapabilityError(ValueError):
    """The resolved channel cannot carry the requested delivery (e.g. a file)."""


class PersonMessageOwnerUnavailable(RuntimeError):
    """The fleet names no unique live master to send person-addressed messages."""


class PersonMessageNotOwner(RuntimeError):
    """A carried request reached a computer that is not the unique live master."""


class CarriedRequestError(ValueError):
    """A carried request holds a file in a form the master does not accept."""


class PersonMessageRefused(RuntimeError):
    """The master refused the carried message; its status and detail are the request's outcome."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


#: What a person-addressed send raises when it cannot reach that recipient; any other exception is a defect.
PERSON_DELIVERY_FAILURES: Final = (
    PersonNotFoundError,
    ChannelCredentialError,
    ChannelCapabilityError,
    OSError,
    RuntimeError,
    ValueError,
    httpx.HTTPError,
)


@dataclass(frozen=True)
class PersonMessageFailure:
    """A recipient that could not be reached and the reason why."""

    recipient: str
    detail: str


class RecipientsUnreachedError(ValueError):
    """No system-default recipient was reached."""

    def __init__(self, failures: tuple[PersonMessageFailure, ...]) -> None:
        self.failures = failures
        details = _FAILURE_SEPARATOR.join(
            _RECIPIENT_DETAIL_SEPARATOR.join((item.recipient, item.detail)) for item in failures
        )
        super().__init__(_ADMINS_UNREACHED.format(failures=details))


@dataclass(frozen=True)
class PersonMessageOutcome:
    """Result of a successful person-addressed send."""

    channel: MessagingChannel
    message_id: str | None


@dataclass(frozen=True)
class PersonMessageDelivery:
    """One successfully delivered message and its routed channel."""

    recipient: str
    channel: MessagingChannel
    message_id: str | None


@dataclass(frozen=True)
class PersonMessageDeliveryResult:
    """Successful deliveries and recipient-specific failures."""

    deliveries: tuple[PersonMessageDelivery, ...]
    failures: tuple[PersonMessageFailure, ...]


@dataclass(frozen=True)
class ResolvedPersonChannel:
    """A person's resolved delivery channel and its per-channel send target."""

    channel: MessagingChannel
    target: str


@dataclass(frozen=True)
class CarriedAttachment:
    """A file's name and content, read by the computer that named it."""

    name: str
    content: bytes


@dataclass(frozen=True)
class CarriedMessageParts:
    """What the requesting computer sent along with a relayed person-addressed request."""

    attachment: CarriedAttachment | None
    backlink_url: str | None


async def _remote_owner() -> str | None:
    """The computer that sends person-addressed messages when it is not this one; None when this computer is it.

    The owner is the fleet's unique live master. Raises ``PersonMessageOwnerUnavailable`` naming why there is none.
    A fleet that cannot be observed establishes no owner on any computer, this one included.
    """
    try:
        fleet = await observe_fleet_from_heartbeats()
    except (OSError, RedisError) as error:
        raise PersonMessageOwnerUnavailable(_FLEET_UNOBSERVABLE.format(error=error)) from error
    resolution = fleet.resolve_master()
    if resolution.master is None:
        if resolution.unavailability is MasterUnavailability.CONFLICTING_MASTERS:
            raise PersonMessageOwnerUnavailable(
                _CONFLICTING_MASTERS.format(computers=_COMPUTER_SEPARATOR.join(resolution.computers))
            )
        raise PersonMessageOwnerUnavailable(_NO_LIVE_MASTER)
    return None if resolution.master.name == config.computer.name else resolution.master.name


async def _read_attachment(path: str) -> CarriedAttachment:
    """Read the file this computer was asked to send, to carry its content to the master."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    if not file_path.is_file():
        raise ValueError(_NOT_A_FILE.format(path=path))
    return CarriedAttachment(name=file_path.name, content=await asyncio.to_thread(file_path.read_bytes))


async def _origin_backlink_url(origin_session_id: str | None) -> str | None:
    """The Discord jump link of a session on this computer, when it resolves."""
    if not origin_session_id:
        return None
    address = resolve_session_conversation_url(await db.get_session(origin_session_id))
    return None if isinstance(address, SessionAddressMissed) else address.url


def _outcome_of(response: RelayedResponse, owner: str) -> PersonMessageDeliveryResult:
    """The master's delivery result, or its refusal as this request's refusal."""
    try:
        payload: object = json.loads(base64.b64decode(response.body_b64))
    except (ValueError, UnicodeError) as error:
        raise PersonMessageRefused(HTTPStatus.BAD_GATEWAY, _CARRIED_RESPONSE_UNREADABLE.format(owner=owner)) from error
    if response.status_code != HTTPStatus.OK:
        detail = payload.get(_DETAIL_FIELD, payload) if isinstance(payload, dict) else payload
        raise PersonMessageRefused(response.status_code, detail if isinstance(detail, str) else json.dumps(detail))
    try:
        answered = PersonMessageResponse.model_validate(payload)
    except ValidationError as error:
        raise PersonMessageRefused(HTTPStatus.BAD_GATEWAY, _CARRIED_RESPONSE_UNREADABLE.format(owner=owner)) from error
    return PersonMessageDeliveryResult(
        tuple(PersonMessageDelivery(item.recipient, item.channel, item.message_id) for item in answered.deliveries),
        tuple(PersonMessageFailure(item.recipient, item.detail) for item in answered.failures),
    )


async def _carry_to_owner(
    owner: str,
    request: PersonMessageRequest,
    *,
    principal: str | None,
    caller_session_id: str | None,
    cleared_command: str | None,
) -> PersonMessageDeliveryResult:
    """Carry the request to the master and return its outcome as this request's outcome."""
    if not principal:
        raise PersonMessageRefused(HTTPStatus.FORBIDDEN, LOGIN_REQUIRED_DETAIL)
    result = await carry_request(
        destination=owner,
        method=HTTPMethod.POST.value,
        path=PERSON_MESSAGE_PATH,
        query=[],
        body=json.dumps(request.model_dump(mode=_JSON_DUMP_MODE, exclude_none=True)).encode(),
        content_type=_JSON_CONTENT_TYPE,
        principal=principal,
        caller_session_id=caller_session_id,
        cleared_command=cleared_command_path(cleared_command) if cleared_command else None,
    )
    return _outcome_of(RelayedResponse.from_wire(result if isinstance(result, dict) else None), owner)


async def _carried_request(
    owner: str,
    *,
    recipient: str | None,
    principal: str | None,
    text: str,
    file: str | None,
    subject: str | None,
    channel: MessagingChannel | None,
    origin_session_id: str | None,
    cleared_command: str | None,
) -> PersonMessageDeliveryResult:
    """Resolve what only this computer holds, then carry the whole request to the master."""
    attachment = await _read_attachment(file) if file else None
    request = PersonMessageRequest(
        recipient=recipient,
        text=text,
        subject=subject,
        channel=channel,
        file_name=attachment.name if attachment else None,
        file_content_b64=base64.b64encode(attachment.content).decode() if attachment else None,
        origin_backlink_url=await _origin_backlink_url(origin_session_id),
    )
    return await _carry_to_owner(
        owner,
        request,
        principal=principal,
        caller_session_id=origin_session_id,
        cleared_command=cleared_command,
    )


@contextmanager
def _carried_file(attachment: CarriedAttachment | None) -> Iterator[str | None]:
    """A master-owned temporary file holding a carried attachment, removed when the send is over."""
    if attachment is None:
        yield None
        return
    file_name = Path(attachment.name).name
    if not file_name or file_name != attachment.name:
        raise CarriedRequestError(_CARRIED_FILE_NAME_REFUSED)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / file_name
        path.write_bytes(attachment.content)
        yield str(path)


async def send_person_message_to_caller(
    recipient: str | None,
    principal: str | None,
    text: str,
    *,
    file: str | None = None,
    subject: str | None = None,
    channel: MessagingChannel | None = None,
    origin_session_id: str | None = None,
    cleared_command: str | None = None,
    carried: CarriedMessageParts | None = None,
) -> PersonMessageDeliveryResult:
    """Deliver to the named person or the caller's resolved default recipients, from the master.

    On the master the message is delivered here. On any other computer the whole request is
    carried to the master and the master's outcome is returned. ``carried`` is set when this
    request was itself carried here by another computer: it then runs only on the master, names
    no path, and delivers with the file content and Discord backlink the requester sent.
    """
    owner = await _remote_owner()
    if carried is not None:
        if owner is not None:
            raise PersonMessageNotOwner(_NOT_THE_MASTER.format(owner=owner, computer=config.computer.name))
        if file:
            raise CarriedRequestError(_CARRIED_FILE_PATH_REFUSED)
        with _carried_file(carried.attachment) as carried_path:
            return await _deliver_to_recipients(
                recipient,
                principal,
                text,
                file=carried_path,
                subject=subject,
                channel=channel,
                origin_session_id=None,
                backlink_url=carried.backlink_url,
            )
    if owner is not None:
        result = await _carried_request(
            owner,
            recipient=recipient,
            principal=principal,
            text=text,
            file=file,
            subject=subject,
            channel=channel,
            origin_session_id=origin_session_id,
            cleared_command=cleared_command,
        )
        await _surface_origin_question(
            result,
            recipient=recipient,
            principal=principal,
            text=text,
            origin_session_id=origin_session_id,
        )
        return result
    result = await _deliver_to_recipients(
        recipient,
        principal,
        text,
        file=file,
        subject=subject,
        channel=channel,
        origin_session_id=origin_session_id,
        backlink_url=None,
    )
    await _surface_origin_question(
        result,
        recipient=recipient,
        principal=principal,
        text=text,
        origin_session_id=origin_session_id,
    )
    return result


async def _surface_origin_question(
    result: PersonMessageDeliveryResult,
    *,
    recipient: str | None,
    principal: str | None,
    text: str,
    origin_session_id: str | None,
) -> None:
    """Project a delivered message to the origin item's GitHub issue when it is selected there."""
    if not origin_session_id or not result.deliveries:
        return
    try:
        origin = await db.get_session(origin_session_id)
        if origin is None or origin.project_path is None or origin.working_slug is None:
            return
        recipients = resolve_person_message_recipients(recipient, principal)
        session_link = await _origin_backlink_url(origin_session_id)
        await surface_github_question(
            origin.project_path,
            origin.working_slug,
            origin_session_id,
            origin.role,
            text,
            session_link,
            recipients,
        )
    except Exception as error:
        logger.warning(
            _GITHUB_QUESTION_SURFACE_FAILED,
            session_id=origin_session_id,
            reason=type(error).__name__,
            exc_info=True,
        )


async def _deliver_to_recipients(
    recipient: str | None,
    principal: str | None,
    text: str,
    *,
    file: str | None,
    subject: str | None,
    channel: MessagingChannel | None,
    origin_session_id: str | None,
    backlink_url: str | None,
) -> PersonMessageDeliveryResult:
    """Deliver from this computer to the named person or the caller's resolved default recipients."""
    recipients = resolve_person_message_recipients(recipient, principal)
    first_recipient = recipients[0]
    if isinstance(first_recipient, str):
        slug = first_recipient
        outcome = await _send_here(
            slug,
            text,
            file=file,
            subject=subject,
            channel=channel,
            origin_session_id=origin_session_id,
            backlink_url=backlink_url,
        )
        delivery = PersonMessageDelivery(slug, outcome.channel, outcome.message_id)
        return PersonMessageDeliveryResult((delivery,), ())

    deliveries: list[PersonMessageDelivery] = []
    failures: list[PersonMessageFailure] = []
    for admin in recipients:
        if not isinstance(admin, PersonEntry):
            continue
        label = admin.slug or admin.name
        if admin.slug is None:
            failures.append(PersonMessageFailure(label, _ADMIN_MISSING_SLUG))
            continue
        try:
            outcome = await _send_here(
                admin.slug,
                text,
                file=file,
                subject=subject,
                channel=channel,
                origin_session_id=origin_session_id,
                backlink_url=backlink_url,
            )
        except PERSON_DELIVERY_FAILURES as exc:
            failures.append(PersonMessageFailure(label, str(exc)))
        else:
            deliveries.append(PersonMessageDelivery(admin.slug, outcome.channel, outcome.message_id))

    if not deliveries:
        raise RecipientsUnreachedError(tuple(failures))
    return PersonMessageDeliveryResult(tuple(deliveries), tuple(failures))


def render_minimal_html(text: str) -> str:
    """Render a minimal HTML body from plain text for the email channel."""
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<p>{escaped.replace(chr(10), '<br>')}</p>"


def resolve_person_channel(slug: str, *, channel: MessagingChannel | None = None) -> ResolvedPersonChannel:
    """Resolve a person by slug to their delivery channel and per-channel send target.

    Channel resolution: the explicit ``channel`` override when given, else the
    person's own ``preferred_channel``, else ``email`` — the one channel every
    person has by construction (``email`` is a required identity field;
    Telegram/Discord/WhatsApp credentials are optional per-person). Raises
    ``PersonNotFoundError`` for an unresolvable slug or ``ChannelCredentialError``
    when the resolved channel has no usable credential.
    """
    global_config = load_global_config()
    person = next((p for p in global_config.people if p.slug == slug), None)
    if person is None:
        raise PersonNotFoundError(f"No person found for slug '{slug}'")

    person_config = load_person_config_for_entry(person, PEOPLE_DIR) or PersonConfig(kind=ConfigKind.PERSON, slug=slug)
    resolved_channel = channel or person_config.preferred_channel or MessagingChannel.EMAIL

    if resolved_channel is MessagingChannel.TELEGRAM:
        telegram_creds = person_config.creds.telegram
        if telegram_creds is None or not telegram_creds.chat_id:
            raise ChannelCredentialError(f"No Telegram chat_id configured for '{slug}'")
        return ResolvedPersonChannel(channel=resolved_channel, target=telegram_creds.chat_id)
    if resolved_channel is MessagingChannel.DISCORD:
        discord_creds = person_config.creds.discord
        if discord_creds is None or not discord_creds.user_id:
            raise ChannelCredentialError(f"No Discord user_id configured for '{slug}'")
        return ResolvedPersonChannel(channel=resolved_channel, target=discord_creds.user_id)
    if resolved_channel is MessagingChannel.WHATSAPP:
        whatsapp_creds = person_config.creds.whatsapp
        if whatsapp_creds is None or not whatsapp_creds.phone_number:
            raise ChannelCredentialError(f"No WhatsApp phone_number configured for '{slug}'")
        return ResolvedPersonChannel(channel=resolved_channel, target=whatsapp_creds.phone_number)
    if not person.email:
        raise ChannelCredentialError(f"No email address configured for '{slug}'")
    return ResolvedPersonChannel(channel=resolved_channel, target=person.email)


def _channel_available(channel: MessagingChannel) -> bool:
    """Whether this computer's effective configuration enables and completes the channel's provider section."""
    if channel is MessagingChannel.TELEGRAM:
        return is_section_available(MessagingChannel.TELEGRAM.value, config)
    if channel is MessagingChannel.DISCORD:
        return is_section_available(MessagingChannel.DISCORD.value, config)
    if channel is MessagingChannel.WHATSAPP:
        return is_section_available(MessagingChannel.WHATSAPP.value, config)
    return is_section_available(MessagingChannel.EMAIL.value, config)


async def send_person_message(
    slug: str,
    text: str,
    *,
    file: str | None = None,
    subject: str | None = None,
    channel: MessagingChannel | None = None,
    origin_session_id: str | None = None,
) -> PersonMessageOutcome:
    """Send a message to one person from the master, as the daemon's own act.

    The entry point for daemon-internal callers. On the master the message is delivered here; on
    any other computer it is carried to the master and the master's delivery is returned. A refusal
    or relay failure reaches the caller as one of ``PERSON_DELIVERY_FAILURES``.
    """
    owner = await _remote_owner()
    if owner is None:
        return await _send_here(
            slug,
            text,
            file=file,
            subject=subject,
            channel=channel,
            origin_session_id=origin_session_id,
            backlink_url=None,
        )
    carried = await _carried_request(
        owner,
        recipient=slug,
        principal=SYSTEM_DAEMON_PRINCIPAL,
        text=text,
        file=file,
        subject=subject,
        channel=channel,
        origin_session_id=origin_session_id,
        cleared_command=None,
    )
    delivery = carried.deliveries[0]
    return PersonMessageOutcome(channel=delivery.channel, message_id=delivery.message_id)


async def _send_here(
    slug: str,
    text: str,
    *,
    file: str | None,
    subject: str | None,
    channel: MessagingChannel | None,
    origin_session_id: str | None,
    backlink_url: str | None,
) -> PersonMessageOutcome:
    """Resolve a person by slug and dispatch a message on their routed channel from this computer.

    Channel resolution: the explicit ``channel`` override when given, else the
    person's own ``preferred_channel``, else ``email``. A Discord delivery ends with
    ``backlink_url`` when the requester carried one, else with the backlink of
    ``origin_session_id`` when it resolves. Raises a distinct, actionable error for an
    unresolvable slug, a missing credential, or a channel that cannot carry the request
    (a file to a WhatsApp recipient); provider send failures propagate from the provider call.
    """
    resolved = resolve_person_channel(slug, channel=channel)

    if not _channel_available(resolved.channel):
        raise ChannelCapabilityError(_CHANNEL_NOT_ENABLED.format(channel=resolved.channel.value))

    if file and resolved.channel is MessagingChannel.WHATSAPP:
        raise ChannelCapabilityError(
            "WhatsApp has no file-attachment capability; cannot deliver a file to a WhatsApp recipient"
        )

    message_id: str | None
    if resolved.channel is MessagingChannel.TELEGRAM:
        message_id = await send_telegram_dm(resolved.target, text, file, bot_token=config.telegram.bot_token)
    elif resolved.channel is MessagingChannel.DISCORD:
        if backlink_url is None and origin_session_id:
            origin_session = await db.get_session(origin_session_id)
            address = resolve_session_conversation_url(origin_session)
            if isinstance(address, SessionAddressMissed):
                logger.info(
                    DISCORD_BACKLINK_MISS_LOG,
                    origin_session_id=origin_session_id,
                    recipient_slug=slug,
                    reason=address.reason.value,
                )
            else:
                backlink_url = address.url
        if backlink_url is not None:
            original_body_length = len(text)
            text, body_was_truncated = render_discord_backlink(text, backlink_url)
            if body_was_truncated:
                logger.warning(
                    DISCORD_MESSAGE_TRUNCATED_LOG,
                    original_len=original_body_length + len(backlink_url) + 1,
                    max_len=DISCORD_MAX_MESSAGE_LENGTH,
                )
        message_id = await send_discord_dm(resolved.target, text, file, bot_token=config.discord.token)
        if backlink_url is not None:
            logger.info(
                DISCORD_BACKLINK_BUILT_LOG,
                origin_session_id=origin_session_id,
                recipient_slug=slug,
                backlink_url=backlink_url,
                message_id=message_id,
            )
    elif resolved.channel is MessagingChannel.WHATSAPP:
        message_id = await send_whatsapp_message(
            resolved.target,
            text,
            phone_number_id=config.whatsapp.phone_number_id or "",
            access_token=config.whatsapp.access_token or "",
            api_version=config.whatsapp.api_version,
        )
    else:
        resolved_subject = subject or DEFAULT_EMAIL_SUBJECT
        await send_email(
            resolved.target,
            resolved_subject,
            render_minimal_html(text),
            text,
            attachment=file,
            email_config=config.email,
        )
        message_id = None

    logger.info(
        "person message sent",
        channel=resolved.channel.value,
        with_file=bool(file),
        origin_session_id=origin_session_id,
    )
    return PersonMessageOutcome(channel=resolved.channel, message_id=message_id)
