"""Invite token and onboarding infrastructure.

Provides:
- Bot username/ID resolution for deep link generation
- Deep link generation for Telegram, Discord, WhatsApp
- Workspace scaffolding for personal assistants
- Identity-aware project path resolution
- Credential binding helpers
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_TELECLAUDE_DIR = Path("~/.teleclaude").expanduser()
_PEOPLE_DIR = _TELECLAUDE_DIR / "people"
_PROJECT_ROOT = Path(__file__).parent.parent  # teleclaude package parent
_TEMPLATES_DIR = _PROJECT_ROOT / "templates" / "emails"


# --- Bot Resolution ---


async def resolve_telegram_bot_username(token_env: str = "TELEGRAM_BOT_TOKEN") -> str:
    """Resolve Telegram bot username from token via getMe API."""
    token = os.getenv(token_env)
    if not token:
        raise ValueError(f"Environment variable {token_env} not set")

    url = f"https://api.telegram.org/bot{token}/getMe"
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
            return username
        except httpx.HTTPError as e:
            raise ValueError(f"Failed to resolve Telegram bot username: {e}") from e


async def resolve_discord_bot_user_id(token_env: str = "DISCORD_BOT_TOKEN") -> str:
    """Resolve Discord bot user ID from token via GET /users/@me."""
    token = os.getenv(token_env)
    if not token:
        raise ValueError(f"Environment variable {token_env} not set")

    url = "https://discord.com/api/v10/users/@me"
    headers = {"Authorization": f"Bot {token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            user_id = data.get("id")
            if not user_id:
                raise ValueError("Discord bot user ID not found in response")
            return user_id
        except httpx.HTTPError as e:
            raise ValueError(f"Failed to resolve Discord bot user ID: {e}") from e


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


# --- Workspace Scaffolding ---


def scaffold_personal_workspace(person_name: str) -> Path:
    """Create personal workspace directory and minimal config.

    Returns the workspace path.
    """
    workspace_path = _PEOPLE_DIR / person_name / "workspace"
    workspace_path.mkdir(parents=True, exist_ok=True)

    # Check if AGENTS.master.md exists in person's home folder
    person_home = _PEOPLE_DIR / person_name
    agents_master_src = person_home / "AGENTS.master.md"
    agents_master_dest = workspace_path / "AGENTS.master.md"

    if agents_master_src.exists() and not agents_master_dest.exists():
        # Symlink if possible, otherwise copy
        try:
            agents_master_dest.symlink_to(agents_master_src)
            logger.info("Symlinked AGENTS.master.md for %s", person_name)
        except OSError:
            import shutil

            shutil.copy2(agents_master_src, agents_master_dest)
            logger.info("Copied AGENTS.master.md for %s", person_name)
    elif not agents_master_dest.exists():
        # Create minimal default
        default_agents = f"You are the personal assistant of {person_name}.\n"
        agents_master_dest.write_text(default_agents, encoding="utf-8")
        logger.info("Created default AGENTS.master.md for %s", person_name)

    # Create minimal teleclaude.yml if not present
    workspace_config = workspace_path / "teleclaude.yml"
    if not workspace_config.exists():
        workspace_config.write_text("# Personal workspace config\n", encoding="utf-8")
        logger.info("Created teleclaude.yml for %s workspace", person_name)

    return workspace_path


# --- Identity-Aware Routing ---


def resolve_project_path(
    identity: Any | None,
) -> str:  # guard: loose-any - IdentityContext not imported to avoid circular dep
    """Resolve project path based on identity.

    - Known person (admin/member/contributor) → personal workspace
    - Unknown/newcomer/customer → help_desk_dir
    """
    from teleclaude.config import config

    if identity is None:
        return config.computer.help_desk_dir

    person_role = getattr(identity, "person_role", None)
    person_name = getattr(identity, "person_name", None)

    if person_role in ("customer", "newcomer", None) or person_name is None:
        return config.computer.help_desk_dir

    # Known person → personal workspace
    workspace_path = scaffold_personal_workspace(person_name)
    return str(workspace_path)


# --- Credential Binding ---


def bind_discord_credentials(person_name: str, discord_user_id: str) -> None:
    """Bind Discord credentials to person config."""
    from teleclaude.cli.config_handlers import get_person_config, save_person_config

    person_config = get_person_config(person_name)
    if not person_config.creds.discord:
        from teleclaude.config.schema import DiscordCreds

        person_config.creds.discord = DiscordCreds(user_id=discord_user_id)
    else:
        person_config.creds.discord.user_id = discord_user_id
    save_person_config(person_name, person_config)
    logger.info("Bound Discord user_id for %s", person_name)


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
        ValueError: If BREVO_SMTP_USER is missing (graceful degradation)
        RuntimeError: If email sending fails
    """
    # Check for SMTP credentials
    if not os.getenv("BREVO_SMTP_USER"):
        logger.warning("BREVO_SMTP_USER not set — printing invite links instead of sending email")
        print(f"\n=== Invite Links for {name} ({email}) ===")
        for platform, link in links.items():
            if link:
                print(f"{platform.capitalize()}: {link}")
        print("=" * 50)
        return

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
    from teleclaude.notifications.email import send_email

    subject = f"Welcome to {org_name} — Your Personal AI Assistant"
    await send_email(email, subject, html_body, text_body)
    logger.info("Invite email sent to %s for %s", email, name)
