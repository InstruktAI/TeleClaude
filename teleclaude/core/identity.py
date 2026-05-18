"""Identity resolution for TeleClaude sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_global_config, load_person_config
from teleclaude.config.schema import PersonEntry
from teleclaude.constants import HUMAN_ROLE_CUSTOMER, HUMAN_ROLES
from teleclaude.paths import GLOBAL_CONFIG_PATH, PEOPLE_DIR

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass
class IdentityContext:
    """Resolved identity for a human interacting with the system."""

    person_name: str | None = None
    person_email: str | None = None
    person_role: str | None = None
    display_name_override: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None

    @property
    def display_name(self) -> str:
        """Best available human-readable name, honoring platform display overrides."""
        result = (
            (self.display_name_override or "").strip()
            or (self.person_name or "").strip()
            or (self.person_email or "").strip()
            or (self.platform_user_id or "").strip()
        )
        if not result:
            raise ValueError(f"Invalid IdentityContext — no resolvable display name: {self}")
        return result


_GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_PATH
_PEOPLE_DIR = PEOPLE_DIR


class IdentityResolver:
    """Resolves human identity from channel metadata."""

    def __init__(self) -> None:
        self._by_email: dict[str, PersonEntry] = {}
        self._by_username: dict[str, PersonEntry] = {}
        self._by_telegram_user_id: dict[int, PersonEntry] = {}
        self._by_discord_user_id: dict[str, PersonEntry] = {}
        self._discord_nick_by_email: dict[str, str] = {}
        self._discord_nick_by_user_id: dict[str, str] = {}
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

    @staticmethod
    def _optional_nick(value: object) -> str | None:
        """Normalize optional platform nicknames."""
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _display_name_override_for(self, person: PersonEntry) -> str | None:
        """Return the configured display override for a person."""
        return self._discord_nick_by_email.get(person.email.lower())

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
        self._discord_nick_by_email.clear()
        self._discord_nick_by_user_id.clear()
        self._by_whatsapp_phone.clear()
        self._registered_people_count = 0

        try:
            global_config = load_global_config()
        except Exception as e:
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

        for person_config_path in sorted(PEOPLE_DIR.glob("*/teleclaude.yml")):
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
                discord_nick = self._optional_nick(discord_creds.nick)
                if discord_nick:
                    self._discord_nick_by_user_id[discord_creds.user_id] = discord_nick
                    self._discord_nick_by_email[person.email.lower()] = discord_nick

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
                display_name_override=self._display_name_override_for(person),
            )
        return IdentityContext()

    @property
    def registered_people_count(self) -> int:
        """Number of registered people in global config."""
        self._reload_if_stale()
        return self._registered_people_count

    def resolve(self, origin: str, origin_metadata: Mapping[str, object]) -> IdentityContext:
        """Resolve identity from origin and metadata.

        Args:
            origin: Source of the session (e.g. 'telegram', 'web', 'terminal').
            origin_metadata: Typed origin metadata or dict with identity signals.

        Returns:
            IdentityContext with resolved identity, or empty IdentityContext if no signals match.
        """
        self._reload_if_stale()

        if origin == "terminal":
            email = origin_metadata.get("email")
            if isinstance(email, str):
                person = self._by_email.get(email.lower())
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        display_name_override=self._display_name_override_for(person),
                        platform="terminal",
                        platform_user_id=email,
                    )

        if origin == "telegram":
            user_id = origin_metadata.get("user_id")
            if user_id:
                try:
                    uid_int = int(user_id)  # type: ignore[call-overload]
                    person = self._by_telegram_user_id.get(uid_int)
                    if person:
                        return IdentityContext(
                            person_name=person.name,
                            person_email=person.email,
                            person_role=self._normalize_role(person.role),
                            display_name_override=self._display_name_override_for(person),
                            platform="telegram",
                            platform_user_id=str(uid_int),
                        )
                except (ValueError, TypeError):
                    pass

        if origin == "web":
            email = origin_metadata.get("email")
            if isinstance(email, str):
                person = self._by_email.get(email.lower())
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        display_name_override=self._display_name_override_for(person),
                        platform="web",
                        platform_user_id=email,
                    )

        if origin == "discord":
            discord_user_id = origin_metadata.get("user_id") or origin_metadata.get("discord_user_id")
            if discord_user_id is not None:
                discord_uid_str = str(discord_user_id)
                person = self._by_discord_user_id.get(discord_uid_str)
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        display_name_override=self._discord_nick_by_user_id.get(discord_uid_str),
                        platform="discord",
                        platform_user_id=discord_uid_str,
                    )
                return IdentityContext(
                    person_role=HUMAN_ROLE_CUSTOMER,
                    platform="discord",
                    platform_user_id=discord_uid_str,
                )

        if origin == "whatsapp":
            phone_number = origin_metadata.get("phone_number")
            if phone_number is not None:
                normalized_phone = self._normalize_phone_number(str(phone_number))
                person = self._by_whatsapp_phone.get(normalized_phone)
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_role=self._normalize_role(person.role),
                        display_name_override=self._display_name_override_for(person),
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


_resolver_instance: IdentityResolver | None = None


def get_identity_resolver() -> IdentityResolver:
    """Get the singleton IdentityResolver instance."""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = IdentityResolver()
    return _resolver_instance
