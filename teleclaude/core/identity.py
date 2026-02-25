"""Identity resolution for TeleClaude sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Optional

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_global_config, load_person_config
from teleclaude.config.schema import PersonEntry
from teleclaude.constants import HUMAN_ROLE_CUSTOMER, HUMAN_ROLES

if TYPE_CHECKING:
    from teleclaude.core.models import SessionAdapterMetadata

logger = get_logger(__name__)
CUSTOMER_ROLE = "customer"


@dataclass
class IdentityContext:
    """Resolved identity for a human interacting with the system."""

    person_name: Optional[str] = None
    person_email: Optional[str] = None
    person_role: Optional[str] = None
    platform: Optional[str] = None
    platform_user_id: Optional[str] = None


class IdentityResolver:
    """Resolves human identity from channel metadata."""

    def __init__(self) -> None:
        self._by_email: dict[str, PersonEntry] = {}
        self._by_username: dict[str, PersonEntry] = {}
        self._by_telegram_user_id: dict[int, PersonEntry] = {}
        self._by_discord_user_id: dict[str, PersonEntry] = {}
        self._load_config()

    @staticmethod
    def _normalize_key(value: str) -> str:
        """Normalize person keys for tolerant directory matching."""
        return "".join(ch for ch in value.lower() if ch.isalnum())

    @staticmethod
    def _normalize_role(role: str) -> str:
        """Validate role against known roles, defaulting unknown to customer."""
        if role in HUMAN_ROLES:
            return role
        return HUMAN_ROLE_CUSTOMER

    def _load_config(self) -> None:
        """Load global and per-person configuration to build lookup maps."""
        try:
            global_config = load_global_config()
        except Exception as e:
            logger.error("Failed to load global config for identity resolution: %s", e)
            return

        people_by_key: dict[str, PersonEntry] = {}
        for person in global_config.people:
            if person.email:
                self._by_email[person.email.lower()] = person
            if person.username:
                self._by_username[person.username.lower()] = person
            people_by_key[self._normalize_key(person.name)] = person
            if person.username:
                people_by_key[self._normalize_key(person.username)] = person

        people_dir = Path("~/.teleclaude/people").expanduser()
        for person_config_path in sorted(people_dir.glob("*/teleclaude.yml")):
            person_key = self._normalize_key(person_config_path.parent.name)
            person = people_by_key.get(person_key)
            if not person:
                continue
            try:
                person_conf = load_person_config(person_config_path)
            except Exception as e:
                logger.warning("Failed to load person config for %s: %s", person.name, e)
                continue

            telegram_creds = getattr(person_conf.creds, "telegram", None) if person_conf.creds else None
            if telegram_creds:
                self._by_telegram_user_id[telegram_creds.user_id] = person

            discord_creds = getattr(person_conf.creds, "discord", None) if person_conf.creds else None
            if discord_creds:
                self._by_discord_user_id[discord_creds.user_id] = person

    def resolve(self, origin: str, channel_metadata: Mapping[str, object]) -> Optional[IdentityContext]:
        """Resolve identity from origin and metadata.

        Args:
            origin: Source of the session (e.g. 'telegram', 'web', 'api').
            channel_metadata: Dictionary of metadata from the channel.

        Returns:
            IdentityContext if resolved, None if unauthorized/unknown.
        """
        if origin == "telegram":
            user_id = channel_metadata.get("user_id")
            if user_id:
                try:
                    uid_int = int(user_id)
                    person = self._by_telegram_user_id.get(uid_int)
                    if person:
                        return IdentityContext(
                            person_name=person.name,
                            person_email=person.email,
                            person_role=self._normalize_role(person.role),
                            platform="telegram",
                            platform_user_id=str(uid_int),
                        )
                except (ValueError, TypeError):
                    pass

        if origin == "web":
            email = channel_metadata.get("email")
            if isinstance(email, str):
                person = self._by_email.get(email.lower())
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        platform="web",
                        platform_user_id=email,
                    )

        if origin == "discord":
            discord_user_id = channel_metadata.get("user_id") or channel_metadata.get("discord_user_id")
            if discord_user_id is not None:
                discord_uid_str = str(discord_user_id)
                person = self._by_discord_user_id.get(discord_uid_str)
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        platform="discord",
                        platform_user_id=discord_uid_str,
                    )
                return IdentityContext(
                    person_role=CUSTOMER_ROLE,
                    platform="discord",
                    platform_user_id=discord_uid_str,
                )

        return None


def derive_identity_key(adapter_metadata: SessionAdapterMetadata) -> str | None:
    """Derive identity key from adapter metadata.

    Format: {platform}:{platform_user_id}
    Returns None if no identity can be determined.
    """
    ui = adapter_metadata.get_ui()
    if ui._discord and ui._discord.user_id:
        return f"discord:{ui._discord.user_id}"
    if ui._telegram and getattr(ui._telegram, "user_id", None):
        return f"telegram:{ui._telegram.user_id}"
    # TODO: Add web platform when WebAdapterMetadata is implemented:
    #   if ui._web and ui._web.email: return f"web:{ui._web.email}"
    return None


_resolver_instance: Optional[IdentityResolver] = None


def get_identity_resolver() -> IdentityResolver:
    """Get the singleton IdentityResolver instance."""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = IdentityResolver()
    return _resolver_instance
