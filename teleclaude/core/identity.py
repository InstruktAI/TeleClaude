"""Identity resolution for TeleClaude sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.config.loader import load_global_config, load_person_config
from teleclaude.config.schema import PersonEntry
from teleclaude.constants import HUMAN_ROLE_CUSTOMER, HUMAN_ROLES

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass
class IdentityContext:
    """Resolved identity for a human interacting with the system."""

    person_name: str | None = None
    person_email: str | None = None
    person_role: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None

    @property
    def display_name(self) -> str:
        """Best available human-readable name: person_name → person_email → platform_user_id."""
        result = (
            (self.person_name or "").strip()
            or (self.person_email or "").strip()
            or (self.platform_user_id or "").strip()
        )
        if not result:
            raise ValueError(f"Invalid IdentityContext — no resolvable display name: {self}")
        return result


_GLOBAL_CONFIG_PATH = Path("~/.teleclaude/teleclaude.yml").expanduser()
_PEOPLE_DIR = Path("~/.teleclaude/people").expanduser()


class IdentityResolver:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Resolves human identity from channel metadata."""

    def __init__(self) -> None:
        self._by_email: dict[str, PersonEntry] = {}
        self._by_username: dict[str, PersonEntry] = {}
        self._by_telegram_user_id: dict[int, PersonEntry] = {}
        self._by_discord_user_id: dict[str, PersonEntry] = {}
        self._by_whatsapp_phone: dict[str, PersonEntry] = {}
        self._registered_people_count: int = 0
        self._config_mtime_ns: int | None = None
        self._people_mtime_ns: int | None = None
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

    @staticmethod
    def _normalize_phone_number(phone_number: str) -> str:
        """Normalize phone number to numeric digits without leading plus."""
        return "".join(ch for ch in phone_number if ch.isdigit())

    def _reload_if_stale(self) -> None:
        """Reload config if any source file changed (mtime-based)."""
        try:
            config_mtime = _GLOBAL_CONFIG_PATH.stat().st_mtime_ns
        except OSError:
            config_mtime = 0
        try:
            people_mtime = _PEOPLE_DIR.stat().st_mtime_ns
        except OSError:
            people_mtime = 0

        if config_mtime == self._config_mtime_ns and people_mtime == self._people_mtime_ns:
            return
        self._config_mtime_ns = config_mtime
        self._people_mtime_ns = people_mtime
        self._load_config()

    def _load_config(self) -> None:
        """Load global and per-person configuration to build lookup maps."""
        self._by_email.clear()
        self._by_username.clear()
        self._by_telegram_user_id.clear()
        self._by_discord_user_id.clear()
        self._by_whatsapp_phone.clear()
        self._registered_people_count = 0

        try:
            global_config = load_global_config()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to load global config for identity resolution: %s", e)
            return

        self._registered_people_count = len(global_config.people)
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
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to load person config for %s: %s", person.name, e)
                continue

            telegram_creds = getattr(person_conf.creds, "telegram", None) if person_conf.creds else None
            if telegram_creds:
                self._by_telegram_user_id[telegram_creds.user_id] = person

            discord_creds = getattr(person_conf.creds, "discord", None) if person_conf.creds else None
            if discord_creds:
                self._by_discord_user_id[discord_creds.user_id] = person

            whatsapp_creds = getattr(person_conf.creds, "whatsapp", None) if person_conf.creds else None
            if whatsapp_creds and getattr(whatsapp_creds, "phone_number", None):
                normalized_phone = self._normalize_phone_number(str(whatsapp_creds.phone_number))
                if normalized_phone:
                    self._by_whatsapp_phone[normalized_phone] = person

    def resolve_by_email(self, email: str) -> IdentityContext:
        """Resolve identity from email address."""
        self._reload_if_stale()
        person = self._by_email.get(email.lower())
        if person:
            return IdentityContext(
                person_name=person.name,
                person_email=person.email,
                person_role=self._normalize_role(person.role),
            )
        return IdentityContext()

    def resolve_from_terminal(self) -> IdentityContext:
        """Resolve identity from terminal login state (TTY-first, global fallback)."""
        email = read_current_session_email()
        if email:
            return self.resolve_by_email(email)
        return IdentityContext()

    @property
    def registered_people_count(self) -> int:
        """Number of registered people in global config."""
        self._reload_if_stale()
        return self._registered_people_count

    def resolve(self, origin: str, channel_metadata: Mapping[str, object]) -> IdentityContext:  # pylint: disable=too-many-branches,too-many-return-statements
        """Resolve identity from origin and metadata.

        Args:
            origin: Source of the session (e.g. 'telegram', 'web', 'terminal').
            channel_metadata: Dictionary of metadata from the channel.

        Returns:
            IdentityContext with person_role always set. Unknown identity defaults to customer.
        """
        self._reload_if_stale()

        if origin == "terminal":
            email = channel_metadata.get("email")
            if isinstance(email, str):
                person = self._by_email.get(email.lower())
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        platform="terminal",
                        platform_user_id=email,
                    )

        if origin == "telegram":
            user_id = channel_metadata.get("user_id")
            if user_id:
                try:
                    uid_int = int(user_id)  # type: ignore[call-overload]
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
                    person_role=HUMAN_ROLE_CUSTOMER,
                    platform="discord",
                    platform_user_id=discord_uid_str,
                )

        if origin == "whatsapp":
            phone_number = channel_metadata.get("phone_number")
            if phone_number is not None:
                normalized_phone = self._normalize_phone_number(str(phone_number))
                person = self._by_whatsapp_phone.get(normalized_phone)
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        platform="whatsapp",
                        platform_user_id=normalized_phone,
                    )
                if normalized_phone:
                    return IdentityContext(
                        person_role=HUMAN_ROLE_CUSTOMER,
                        platform="whatsapp",
                        platform_user_id=normalized_phone,
                    )

        return IdentityContext()


def derive_identity_key(origin_metadata: dict[str, object]) -> str | None:  # guard: loose-dict
    """Derive identity key from origin_metadata.

    Format: {platform}:{platform_user_id}
    Returns None if no identity can be determined.
    """
    discord = origin_metadata.get("discord")
    if isinstance(discord, dict) and discord.get("user_id"):
        return f"discord:{discord['user_id']}"
    telegram = origin_metadata.get("telegram")
    if isinstance(telegram, dict) and telegram.get("user_id"):
        return f"telegram:{telegram['user_id']}"
    whatsapp = origin_metadata.get("whatsapp")
    if isinstance(whatsapp, dict) and whatsapp.get("phone_number"):
        return f"whatsapp:{whatsapp['phone_number']}"
    return None


_resolver_instance: IdentityResolver | None = None  # pylint: disable=invalid-name


def get_identity_resolver() -> IdentityResolver:
    """Get the singleton IdentityResolver instance."""
    global _resolver_instance  # pylint: disable=global-statement
    if _resolver_instance is None:
        _resolver_instance = IdentityResolver()
    return _resolver_instance
