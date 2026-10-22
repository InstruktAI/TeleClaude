"""Invite token and onboarding infrastructure.

Provides:
- Bot username/ID resolution for deep link generation
- Deep link generation for Telegram, Discord, WhatsApp
- Workspace scaffolding for personal assistants
- Identity-aware project path resolution
- Credential binding helpers
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.cli.config_handlers import get_global_config, get_person_config, save_person_config
from teleclaude.config.declaration import write_declared_config
from teleclaude.config.invitations import issue_invite_token
from teleclaude.config.loader import load_global_config
from teleclaude.config.machine import config
from teleclaude.config.notification_interests import new_person_document
from teleclaude.config.schema import ConfigKind, DiscordCreds
from teleclaude.config.validation import is_section_available
from teleclaude.core.identity import (
    DiscordAvatarBindingOutcome,
    DiscordAvatarBindingReason,
    observe_discord_avatar_binding,
)
from teleclaude.core.inbound.fleet import FleetView, MasterUnavailability
from teleclaude.core.reconciliation.home_convergence import person_home_targets
from teleclaude.core.reconciliation.template_installation import materialize_template_targets
from teleclaude.paths import PEOPLE_DIR, TELECLAUDE_HOME, ConfigFileName
from teleclaude.services.email import send_email

logger = get_logger(__name__)

_TELECLAUDE_DIR = TELECLAUDE_HOME
_PEOPLE_DIR = PEOPLE_DIR
_PROJECT_ROOT = Path(__file__).parent.parent  # teleclaude package parent
_TEMPLATES_DIR = _PROJECT_ROOT / "templates" / "emails"
_LINK_BOT_UNRESOLVED_EVENT = "help_desk_link_bot_unresolved"
_TELEGRAM_ADAPTER = "telegram"
_DISCORD_ADAPTER = "discord"
_WHATSAPP_ADAPTER = "whatsapp"
_EMAIL_ADAPTER = "email"
_NO_LIVE_MASTER_REFUSAL = "invitations are issued on the mesh master, and no master is live"
_CONFLICTING_MASTERS_REFUSAL = (
    "invitations are issued on the mesh master, and several computers declare themselves master: {computers}"
)
_NOT_THE_OWNER_REFUSAL = "invitations are issued on the mesh master {owner}, and this computer is {computer}"
_COMPUTER_SEPARATOR = ", "
_TELEGRAM_GET_ME_URL = "https://api.telegram.org/bot{token}/getMe"
_AUTHORIZATION_HEADER = "Authorization"
_DISCORD_BOT_AUTHORIZATION = "Bot {token}"
_TELEGRAM_RESOLVE_FAILED_LOG = "Failed to resolve Telegram bot username: %s"
_DISCORD_RESOLVE_FAILED_LOG = "Failed to resolve Discord bot user ID: %s"
_INVITE_EMAIL_FAILED_LOG = "Failed to send invite email: %s"


# --- Bot Resolution ---


async def resolve_telegram_bot_username(bot_token: str) -> str:
    """Resolve Telegram bot username from the bot token via getMe API."""
    url = _TELEGRAM_GET_ME_URL.format(token=bot_token)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise ValueError(f"Telegram API error: {data.get('description', 'Unknown')}")
            username = data["result"].get("username")
            if not username:
                raise ValueError("Telegram bot has no username")
            return username  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            raise ValueError(f"Failed to resolve Telegram bot username: {e}") from e


async def resolve_discord_bot_user_id(bot_token: str) -> str:
    """Resolve Discord bot user ID from the bot token via GET /users/@me."""
    url = "https://discord.com/api/v10/users/@me"
    headers = {_AUTHORIZATION_HEADER: _DISCORD_BOT_AUTHORIZATION.format(token=bot_token)}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            user_id = data.get("id")
            if not user_id:
                raise ValueError("Discord bot user ID not found in response")
            return user_id  # type: ignore[no-any-return]
        except httpx.HTTPError as e:
            raise ValueError(f"Failed to resolve Discord bot user ID: {e}") from e


def _available_telegram_token() -> str | None:
    """The Telegram bot token when Telegram is available on this computer, else None."""
    return config.telegram.bot_token if is_section_available(_TELEGRAM_ADAPTER, config) else None


def _available_discord_token() -> str | None:
    """The Discord bot token when Discord is available on this computer, else None."""
    return config.discord.token if is_section_available(_DISCORD_ADAPTER, config) else None


def _available_whatsapp_number() -> str | None:
    """The WhatsApp business number when WhatsApp is available on this computer, else None."""
    return config.whatsapp.business_number if is_section_available(_WHATSAPP_ADAPTER, config) else None


# --- Deep Link Generation ---


def generate_invite_links(
    token: str,
    bot_username: str | None,
    discord_bot_id: str | None,
    whatsapp_number: str | None,
) -> dict[str, str | None]:
    """Generate invite deep links for all platforms.

    Returns a dict with keys: telegram, discord, whatsapp.
    Values are link strings or None if the platform cannot be generated.
    """
    links: dict[str, str | None] = {}

    if bot_username:
        links["telegram"] = f"https://t.me/{bot_username}?start={token}"
    else:
        links["telegram"] = None

    if discord_bot_id:
        links["discord"] = f"https://discord.com/users/{discord_bot_id}"
    else:
        links["discord"] = None

    if whatsapp_number:
        links["whatsapp"] = f"https://wa.me/{whatsapp_number}?text={token}"
    else:
        links["whatsapp"] = None

    return links


async def render_help_desk_links(identifier: str, *, telegram_allowed: bool) -> dict[str, str | None]:
    """Render a hosted help desk's entry links for the adapters that carry desk entry.

    Discord carries none, so the result has no Discord link. ``telegram_allowed``
    is false when the identifier cannot be a Telegram start parameter; that
    adapter then has no link. A bot whose identity cannot be resolved has no
    link either.
    """
    telegram_username: str | None = None
    telegram_token = _available_telegram_token()
    if telegram_allowed and telegram_token is not None:
        try:
            telegram_username = await resolve_telegram_bot_username(telegram_token)
        except ValueError as e:
            logger.warning(_LINK_BOT_UNRESOLVED_EVENT, adapter=_TELEGRAM_ADAPTER, error=str(e))
    links = generate_invite_links(identifier, telegram_username, None, _available_whatsapp_number())
    return {adapter: link for adapter, link in links.items() if adapter != _DISCORD_ADAPTER}


# --- Workspace Scaffolding ---


def _roster_role(person_slug: str) -> str | None:
    """The role the people roster declares for a slug; none when the slug is not on the roster."""
    return next(
        (entry.role for entry in load_global_config().people if (entry.slug or entry.name) == person_slug), None
    )


def scaffold_personal_workspace(person_slug: str, *, people_root: Path = _PEOPLE_DIR) -> Path:
    """Ensure the person's home exists, is declared, and matches the person templates.

    Returns the person's slug-keyed folder (``<people_root>/{slug}/``). Writes the
    person declaration when absent, then converges the home to its templates:
    the person master is the template's rendering after every call, and the
    local baseline manifests are created only when absent.
    """
    person_path = people_root / person_slug
    person_path.mkdir(parents=True, exist_ok=True)

    # Create minimal teleclaude.yml if not present
    workspace_config = person_path / ConfigFileName.OVERLAY
    if not workspace_config.exists():
        write_declared_config(
            workspace_config, ConfigKind.PERSON, new_person_document(person_slug, _roster_role(person_slug))
        )
        logger.info("Created teleclaude.yml for %s workspace", person_slug)

    materialize_template_targets(person_home_targets(person_path), values={}, environ=os.environ)  # fmt: skip  # guard: direct-env-read - allowed: configuration loading or interpolation
    return person_path


# --- Credential Binding ---


def bind_discord_credentials(
    person_slug: str,
    discord_user_id: str,
    *,
    avatar_url: str | None = None,
    binding_id: str,
) -> None:
    """Bind Discord credentials to a person config keyed by slug."""
    person_config = get_person_config(person_slug)
    if not person_config.creds.discord:
        person_config.creds.discord = DiscordCreds(user_id=discord_user_id, avatar_url=avatar_url)
    else:
        person_config.creds.discord.user_id = discord_user_id
        person_config.creds.discord.avatar_url = avatar_url
    save_person_config(person_slug, person_config)
    observe_discord_avatar_binding(
        binding_id=binding_id,
        outcome=DiscordAvatarBindingOutcome.STORED,
        reason=DiscordAvatarBindingReason.CREDENTIALS_PERSISTED,
        avatar_present=avatar_url is not None,
    )


# --- Email Delivery ---


async def send_invite_email(
    name: str,
    email: str,
    links: dict[str, str | None],
    org_name: str = "InstruktAI",
    sender_name: str = "Your Admin",
) -> None:
    """Send invite email with platform links.

    Args:
        name: Person's name
        email: Recipient email address
        links: Dict with keys telegram, discord, whatsapp (values are URLs or None)
        org_name: Organization name for email greeting
        sender_name: Sign-off name

    Raises:
        RuntimeError: If delivery fails.
    """
    # Load templates
    html_template_path = _TEMPLATES_DIR / "member-invite.html"
    text_template_path = _TEMPLATES_DIR / "member-invite.txt"

    if not html_template_path.exists():
        raise FileNotFoundError(f"Email template not found: {html_template_path}")

    html_template = html_template_path.read_text(encoding="utf-8")
    text_template = text_template_path.read_text(encoding="utf-8") if text_template_path.exists() else ""

    # Build platform buttons/links for HTML
    def make_button(platform: str, link: str | None, css_class: str) -> str:
        if link:
            return f'<a href="{link}" class="button {css_class}">{platform.capitalize()}</a>'
        return f'<span class="button coming-soon">{platform.capitalize()} (coming soon)</span>'

    telegram_button = make_button("Telegram", links.get("telegram"), "telegram")
    discord_button = make_button("Discord", links.get("discord"), "discord")
    whatsapp_button = make_button("WhatsApp", links.get("whatsapp"), "whatsapp")

    # Build platform text links
    def make_text_link(platform: str, link: str | None) -> str:
        if link:
            return f"{platform.capitalize()}: {link}"
        return f"{platform.capitalize()}: (coming soon)"

    telegram_text = make_text_link("Telegram", links.get("telegram"))
    discord_text = make_text_link("Discord", links.get("discord"))
    whatsapp_text = make_text_link("WhatsApp", links.get("whatsapp"))

    # Substitute placeholders
    html_body = html_template.format(
        name=name,
        org_name=org_name,
        telegram_button=telegram_button,
        discord_button=discord_button,
        whatsapp_button=whatsapp_button,
        sender_name=sender_name,
    )

    text_body = text_template.format(
        name=name,
        telegram_text=telegram_text,
        discord_text=discord_text,
        whatsapp_text=whatsapp_text,
        sender_name=sender_name,
    )

    # Send email
    subject = f"Welcome to {org_name} — Your Personal AI Assistant"
    await send_email(email, subject, html_body, text_body, email_config=config.email)
    logger.info("Invite email sent")


# --- Invitation (explicit person action) ---


class InvitationOwnerUnavailable(Exception):
    """The fleet names no unique live master to issue invitations."""


def invitation_owner(fleet: FleetView) -> str:
    """The computer that issues and redeems invitations: the fleet's unique live master.

    Raises ``InvitationOwnerUnavailable`` naming why there is none.
    """
    resolution = fleet.resolve_master()
    if resolution.master is not None:
        return resolution.master.name
    if resolution.unavailability is MasterUnavailability.CONFLICTING_MASTERS:
        raise InvitationOwnerUnavailable(
            _CONFLICTING_MASTERS_REFUSAL.format(computers=_COMPUTER_SEPARATOR.join(resolution.computers))
        )
    raise InvitationOwnerUnavailable(_NO_LIVE_MASTER_REFUSAL)


def admit_invitation_here(fleet: FleetView) -> None:
    """Admit an invitation operation on this computer only when it is the owner.

    Raises ``InvitationOwnerUnavailable`` when there is no owner or another computer is it,
    naming the owner; nothing has been read or changed by then.
    """
    owner = invitation_owner(fleet)
    if owner != config.computer.name:
        raise InvitationOwnerUnavailable(_NOT_THE_OWNER_REFUSAL.format(owner=owner, computer=config.computer.name))


@dataclass(frozen=True)
class InviteOutcome:
    """The result of issuing one person's invitation.

    ``unavailable_providers`` names each enabled provider whose public endpoint could not be
    resolved, so its missing link is distinguishable from a provider that is not enabled.
    ``email_enabled`` is false when email is not enabled here, so no email was attempted.
    """

    name: str
    email: str
    links: dict[str, str | None]
    email_sent: bool
    email_enabled: bool
    unavailable_providers: tuple[str, ...] = ()


def invite_person(slug: str) -> InviteOutcome:
    """Issue (or rotate) an invitation for a registered person, and attempt delivery.

    Refuses an unregistered slug and a person with no email. Bot-username
    resolution failures and email-delivery failures are both tolerated —
    neither blocks returning the deep links the invite issued.
    """
    person = next((p for p in get_global_config().people if p.slug == slug), None)
    if person is None:
        raise ValueError(f"Person with slug '{slug}' not found")
    if not person.email:
        raise ValueError(f"Person '{slug}' has no email address configured")

    name = person.name
    email = person.email

    async def _run_invite() -> InviteOutcome:
        token = issue_invite_token(slug)

        telegram_username: str | None = None
        discord_bot_id: str | None = None
        unavailable: list[str] = []

        telegram_token = _available_telegram_token()
        if telegram_token is not None:
            try:
                telegram_username = await resolve_telegram_bot_username(telegram_token)
            except ValueError as e:
                logger.warning(_TELEGRAM_RESOLVE_FAILED_LOG, e)
                unavailable.append(_TELEGRAM_ADAPTER)

        discord_token = _available_discord_token()
        if discord_token is not None:
            try:
                discord_bot_id = await resolve_discord_bot_user_id(discord_token)
            except ValueError as e:
                logger.warning(_DISCORD_RESOLVE_FAILED_LOG, e)
                unavailable.append(_DISCORD_ADAPTER)

        links = generate_invite_links(token, telegram_username, discord_bot_id, _available_whatsapp_number())

        email_enabled = is_section_available(_EMAIL_ADAPTER, config)
        email_sent = False
        if email_enabled:
            try:
                await send_invite_email(name, email, links)
                email_sent = True
            except Exception as e:
                logger.warning(_INVITE_EMAIL_FAILED_LOG, e)

        return InviteOutcome(
            name=name,
            email=email,
            links=links,
            email_sent=email_sent,
            email_enabled=email_enabled,
            unavailable_providers=tuple(unavailable),
        )

    return asyncio.run(_run_invite())
