"""Core person-addressed messaging service.

Resolves a person by slug and dispatches a message on their routed channel,
reusing the existing per-channel outbound send primitives
(``teleclaude.services.{telegram,discord,whatsapp,email}``) — no new
transport, per ``project/spec/messaging`` (Person-addressed delivery).
"""

from __future__ import annotations

from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.config.loader import load_global_config, load_person_config_for_entry
from teleclaude.config.schema import MessagingChannel, PersonConfig
from teleclaude.paths import PEOPLE_DIR
from teleclaude.services.discord import send_discord_dm
from teleclaude.services.email import send_email
from teleclaude.services.telegram import send_telegram_dm
from teleclaude.services.whatsapp import send_whatsapp_message

logger = get_logger(__name__)

DEFAULT_EMAIL_SUBJECT = "TeleClaude message"


class PersonNotFoundError(ValueError):
    """No addressable person resolves for the given slug."""


class ChannelCredentialError(ValueError):
    """The resolved channel has no usable credential for this person."""


class ChannelCapabilityError(ValueError):
    """The resolved channel cannot carry the requested delivery (e.g. a file)."""


@dataclass(frozen=True)
class PersonMessageOutcome:
    """Result of a successful person-addressed send."""

    channel: MessagingChannel
    message_id: str | None


@dataclass(frozen=True)
class ResolvedPersonChannel:
    """A person's resolved delivery channel and its per-channel send target."""

    channel: MessagingChannel
    target: str


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

    person_config = load_person_config_for_entry(person, PEOPLE_DIR) or PersonConfig()
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


async def send_person_message(
    slug: str,
    text: str,
    *,
    file: str | None = None,
    subject: str | None = None,
    channel: MessagingChannel | None = None,
    origin_session_id: str | None = None,
) -> PersonMessageOutcome:
    """Resolve a person by slug and dispatch a message on their routed channel.

    Channel resolution: the explicit ``channel`` override when given, else the
    person's own ``preferred_channel``, else ``email``. ``origin_session_id``
    carries the calling session into the delivery log line for traceability; it
    does not affect resolution or dispatch. Raises a distinct, actionable error
    for an unresolvable slug, a missing credential, or a
    channel that cannot carry the request (a file to a WhatsApp recipient);
    provider send failures propagate from the underlying provider call.
    """
    resolved = resolve_person_channel(slug, channel=channel)

    if file and resolved.channel is MessagingChannel.WHATSAPP:
        raise ChannelCapabilityError(
            "WhatsApp has no file-attachment capability; cannot deliver a file to a WhatsApp recipient"
        )

    message_id: str | None
    if resolved.channel is MessagingChannel.TELEGRAM:
        message_id = await send_telegram_dm(resolved.target, text, file)
    elif resolved.channel is MessagingChannel.DISCORD:
        message_id = await send_discord_dm(resolved.target, text, file)
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
        await send_email(resolved.target, resolved_subject, render_minimal_html(text), text, attachment=file)
        message_id = None

    logger.info(
        "person message sent",
        slug=slug,
        channel=resolved.channel.value,
        with_file=bool(file),
        origin_session_id=origin_session_id,
    )
    return PersonMessageOutcome(channel=resolved.channel, message_id=message_id)
