"""Identity resolution for TeleClaude sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AgentName
from teleclaude.caller_identity import (
    SYSTEM_PRINCIPAL_PREFIX,
    RoleResolver,
    SessionIdentityError,
    SessionOf,
    identity_for_session,
    resolve_session_principal,
    visitor_principal,
)
from teleclaude.caller_identity import (
    CliCaller as CliCaller,
)
from teleclaude.caller_identity import (
    CliCallerKind as CliCallerKind,
)
from teleclaude.caller_identity import (
    NoIdentityCliCaller as NoIdentityCliCaller,
)
from teleclaude.caller_identity import (
    PersonCliCaller as PersonCliCaller,
)
from teleclaude.caller_identity import (
    SessionIdentity as SessionIdentity,
)
from teleclaude.caller_identity import (
    SystemCliCaller as SystemCliCaller,
)
from teleclaude.caller_identity import (
    authorizing_role as authorizing_role,
)
from teleclaude.caller_identity import (
    caller_from_principal as caller_from_principal,
)
from teleclaude.caller_identity import (
    human_principal_for_email as human_principal_for_email,
)
from teleclaude.config.identity_schema import PersonEntry
from teleclaude.config.loader import load_global_config, load_person_config, normalize_person_config_key
from teleclaude.config.schema import PersonChipColor
from teleclaude.constants import (
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLES,
)
from teleclaude.core.db import db
from teleclaude.core.injected_text import (
    CALLER_CATEGORY_PART_SEPARATOR,
    CALLER_CATEGORY_SEPARATOR,
    MachineRoleLabel,
    caller_header_identity,
)
from teleclaude.core.models import MessageAuthor, MessageAuthorKind, Session, SessionEntryPoint
from teleclaude.identity_reach import Reach, resolve_reach, visitor_reach
from teleclaude.paths import GLOBAL_CONFIG_PATH, PEOPLE_DIR, ConfigFileName

logger = get_logger(__name__)

_DISCORD_AVATAR_BINDING_EVENT = "discord_avatar_binding_lifecycle"
_UNREGISTERED_LINEAGE_PERSON_EVENT = "session_lineage_person_unregistered"
_PERSON_CONTEXT_BINDING_REGISTRY_UNAVAILABLE = "Person registry is unavailable for context binding"


class DiscordAvatarBindingOutcome(StrEnum):
    """Terminal states emitted while binding Discord avatar presentation."""

    ACCEPTED = "accepted"
    STORED = "stored"


class DiscordAvatarBindingReason(StrEnum):
    """Closed reasons for Discord avatar binding observations."""

    UNBOUND_INVITE = "unbound_invite"
    CREDENTIALS_PERSISTED = "credentials_persisted"


class ReflectionAvatarSource(StrEnum):
    """The owner of the avatar selected for a human reflection."""

    CALLER_SUPPLIED = "caller_supplied"
    IDENTITY_STORED = "identity_stored"
    NONE = "none"


class PersonContextBindingRefusal(StrEnum):
    """Closed refusal vocabulary for person-context binding."""

    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    DISAGREEING = "disagreeing"


class PersonContextBindingRegistryError(ValueError):
    """The person registry could not be read to validate a context claim."""


@dataclass(frozen=True)
class AcceptedPersonContextBinding:
    """A validated person-context binding that publishes one registered person."""

    person: PersonEntry


@dataclass(frozen=True)
class RefusedPersonContextBinding:
    """A person-context claim that does not resolve to one valid binding."""

    refusal: PersonContextBindingRefusal


PersonContextBinding = AcceptedPersonContextBinding | RefusedPersonContextBinding


def observe_discord_avatar_binding(
    *,
    binding_id: str,
    outcome: DiscordAvatarBindingOutcome,
    reason: DiscordAvatarBindingReason,
    avatar_present: bool,
) -> None:
    """Record one Discord avatar binding transition without personal data."""
    logger.info(
        _DISCORD_AVATAR_BINDING_EVENT,
        outcome=outcome,
        reason=reason,
        binding_id=binding_id,
        avatar_present=avatar_present,
    )


def session_person_role(session: Session) -> str | None:
    """Resolve a session's current person's role for its project."""
    resolved = identity_for_session(session)
    if isinstance(resolved.caller, SystemCliCaller):
        return None
    if not isinstance(resolved.caller, PersonCliCaller):
        return None
    if not resolved.caller.person_slug:
        return HUMAN_ROLE_CUSTOMER
    return RoleResolver().role_for(resolved.caller, SessionOf(session.project_path))


def derive_initials(person_name: str) -> str:
    """Derive uppercase chip initials from a person's display name.

    Multi-word names take the first letter of each word (``"Alice Smith"`` →
    ``"AS"``); a single-word name takes its first two letters (``"Alice"`` →
    ``"AL"``) so the chip stays a consistent two-glyph badge.
    """
    words = person_name.split()
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][:1] + words[-1][:1]).upper()


@dataclass
class IdentityContext:
    """Resolved identity for a human interacting with the system."""

    person_name: str | None = None
    person_email: str | None = None
    person_slug: str | None = None
    person_role: str | None = None
    display_name_override: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None
    chip_color: PersonChipColor | None = None
    avatar_url: str | None = None

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


def select_reflection_avatar(
    identity: IdentityContext,
    caller_avatar_url: str | None,
) -> tuple[str | None, ReflectionAvatarSource]:
    """Select a reflection avatar while preserving source precedence."""
    caller_avatar = (caller_avatar_url or "").strip() or None
    if caller_avatar:
        return caller_avatar, ReflectionAvatarSource.CALLER_SUPPLIED
    stored_avatar = (identity.avatar_url or "").strip() or None
    if stored_avatar:
        return stored_avatar, ReflectionAvatarSource.IDENTITY_STORED
    return None, ReflectionAvatarSource.NONE


_GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_PATH
_PEOPLE_DIR = PEOPLE_DIR
_TELEGRAM_PLATFORM = "telegram"
_DISCORD_PLATFORM = "discord"
_WHATSAPP_PLATFORM = "whatsapp"
_GITHUB_PLATFORM = "github"
_GITHUB_LOGIN = "login"
# Each person's own config file, relative to the people directory.
_PERSON_CONFIG_PATTERN = f"*/{ConfigFileName.OVERLAY}"


class IdentityResolver:
    """Resolves human identity from channel metadata."""

    def __init__(self) -> None:
        self._by_email: dict[str, PersonEntry] = {}
        self._email_matches: dict[str, list[PersonEntry]] = {}
        self._by_slug: dict[str, list[PersonEntry]] = {}
        self._by_context_root: dict[Path, PersonEntry] = {}
        self._by_username: dict[str, PersonEntry] = {}
        self._by_telegram_user_id: dict[int, PersonEntry] = {}
        self._by_discord_user_id: dict[str, PersonEntry] = {}
        self._discord_nick_by_email: dict[str, str] = {}
        self._discord_nick_by_user_id: dict[str, str] = {}
        self._discord_avatar_by_email: dict[str, str] = {}
        self._by_whatsapp_phone: dict[str, PersonEntry] = {}
        self._by_github_handle: dict[str, list[PersonEntry]] = {}
        self._color_by_email: dict[str, PersonChipColor] = {}
        self._registered_people_count: int = 0
        self._sole_person_email: str | None = None
        self._registry_load_error: Exception | None = None
        self._config_mtime_ns: int | None = None
        self._people_mtime_ns: int | None = None
        self._person_configs_signature: tuple[tuple[str, int], ...] | None = None
        self._unregistered_lineage_reported: set[str] = set()
        self._load_config()

    @staticmethod
    def _normalize_key(value: str) -> str:
        """Normalize person keys for tolerant directory matching."""
        return normalize_person_config_key(value)

    @staticmethod
    def _normalize_role(role: str | None) -> str:
        """Validate role against known roles, defaulting unknown to customer."""
        if role in HUMAN_ROLES:
            return role
        return HUMAN_ROLE_CUSTOMER

    @staticmethod
    def _normalize_phone_number(phone_number: str) -> str:
        """Normalize phone number to numeric digits without leading plus."""
        return "".join(ch for ch in phone_number if ch.isdigit())

    @staticmethod
    def _optional_nick(value: str | None) -> str | None:
        """Normalize optional platform nicknames."""
        if value and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _optional_avatar_url(value: str | None) -> str | None:
        """Normalize optional stored Discord avatar URLs."""
        if value and value.strip():
            return value.strip()
        return None

    def _display_name_override_for(self, person: PersonEntry) -> str | None:
        """Return the configured display override for a person."""
        return self._discord_nick_by_email.get(person.email.lower())

    def _avatar_url_for(self, person: PersonEntry) -> str | None:
        """Return the stored Discord avatar URL for a person."""
        return self._discord_avatar_by_email.get(person.email.lower())

    @staticmethod
    def _context_root_for(person: PersonEntry) -> Path | None:
        """Return the registry-designated workspace root for one person."""
        if person.slug is None:
            return None
        return (_PEOPLE_DIR / person.slug).expanduser().resolve()

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

        person_configs = self._person_configs_signature_now()

        if (
            config_mtime == self._config_mtime_ns
            and people_mtime == self._people_mtime_ns
            and person_configs == self._person_configs_signature
        ):
            return
        self._config_mtime_ns = config_mtime
        self._people_mtime_ns = people_mtime
        self._person_configs_signature = person_configs
        self._unregistered_lineage_reported.clear()
        self._load_config()

    @staticmethod
    def _person_configs_signature_now() -> tuple[tuple[str, int], ...]:
        """Each person's own config file with its modification time.

        A credential binding rewrites only that person's file, which changes
        neither the global config nor the people directory itself.
        """
        signature: list[tuple[str, int]] = []
        for person_config_path in sorted(_PEOPLE_DIR.glob(_PERSON_CONFIG_PATTERN)):
            try:
                signature.append((person_config_path.parent.name, person_config_path.stat().st_mtime_ns))
            except OSError:
                continue
        return tuple(signature)

    def _load_config(self) -> None:
        """Load global and per-person configuration to build lookup maps."""
        self._by_email.clear()
        self._email_matches.clear()
        self._by_slug.clear()
        self._by_context_root.clear()
        self._by_username.clear()
        self._by_telegram_user_id.clear()
        self._by_discord_user_id.clear()
        self._discord_nick_by_email.clear()
        self._discord_nick_by_user_id.clear()
        self._discord_avatar_by_email.clear()
        self._by_whatsapp_phone.clear()
        self._by_github_handle.clear()
        self._color_by_email.clear()
        self._registered_people_count = 0
        self._sole_person_email = None
        self._registry_load_error = None

        try:
            global_config = load_global_config()
        except Exception as e:
            self._registry_load_error = e
            logger.error("Failed to load global config for identity resolution: %s", e)
            return

        self._registered_people_count = len(global_config.people)
        if self._registered_people_count == 1:
            self._sole_person_email = global_config.people[0].email.strip().lower() or None
        people_by_key: dict[str, PersonEntry] = {}
        for person in global_config.people:
            normalized_email = person.email.lower()
            self._email_matches.setdefault(normalized_email, []).append(person)
            self._by_email[normalized_email] = person
            if person.slug:
                self._by_slug.setdefault(person.slug, []).append(person)
                context_root = self._context_root_for(person)
                if context_root is not None:
                    self._by_context_root[context_root] = person
            if person.username:
                self._by_username[person.username.lower()] = person
            people_by_key[self._normalize_key(person.name)] = person
            if person.username:
                people_by_key[self._normalize_key(person.username)] = person
            if person.slug:
                people_by_key[self._normalize_key(person.slug)] = person

        for person_config_path in sorted(PEOPLE_DIR.glob(f"*/{ConfigFileName.OVERLAY}")):
            person_key = self._normalize_key(person_config_path.parent.name)
            person = people_by_key.get(person_key)
            if not person:
                continue
            try:
                person_conf = load_person_config(person_config_path)
            except Exception as e:
                logger.warning("Failed to load person config for %s: %s", person.name, e)
                continue

            if person_conf.color is not None:
                self._color_by_email[person.email.lower()] = person_conf.color

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
                avatar_url = self._optional_avatar_url(discord_creds.avatar_url)
                if avatar_url:
                    self._discord_avatar_by_email[person.email.lower()] = avatar_url

            whatsapp_creds = getattr(person_conf.creds, "whatsapp", None) if person_conf.creds else None
            if whatsapp_creds and getattr(whatsapp_creds, "phone_number", None):
                normalized_phone = self._normalize_phone_number(str(whatsapp_creds.phone_number))
                if normalized_phone:
                    self._by_whatsapp_phone[normalized_phone] = person

            github_handle = person_conf.github.identity.handle
            if github_handle:
                self._by_github_handle.setdefault(github_handle.casefold(), []).append(person)

    def person_by_slug(self, slug: str) -> PersonEntry | None:
        """The one registered person holding this slug, or ``None`` when none or more than one does."""
        self._reload_if_stale()
        matches = self._by_slug.get(slug, [])
        return matches[0] if len(matches) == 1 else None

    def person_for_provider_identity(self, platform: str, native_id: str) -> PersonEntry | None:
        """The registered person whose verified credentials bind this provider account, if any."""
        self._reload_if_stale()
        if platform == _TELEGRAM_PLATFORM:
            return self._by_telegram_user_id.get(int(native_id)) if native_id.isdigit() else None
        if platform == _DISCORD_PLATFORM:
            return self._by_discord_user_id.get(native_id)
        if platform == _WHATSAPP_PLATFORM:
            return self._by_whatsapp_phone.get(self._normalize_phone_number(native_id))
        return None

    def provider_identities_for_person(self, slug: str) -> tuple[str, ...]:
        """Every provider-qualified identity key the person's verified credentials bind."""
        self._reload_if_stale()
        bound = [
            f"{_TELEGRAM_PLATFORM}:{user_id}"
            for user_id, person in self._by_telegram_user_id.items()
            if person.slug == slug
        ]
        bound += [
            f"{_DISCORD_PLATFORM}:{user_id}"
            for user_id, person in self._by_discord_user_id.items()
            if person.slug == slug
        ]
        bound += [
            f"{_WHATSAPP_PLATFORM}:{phone}" for phone, person in self._by_whatsapp_phone.items() if person.slug == slug
        ]
        return tuple(sorted(bound))

    def resolve_person_context_binding(self, claim: str, context_root: Path) -> PersonContextBinding:
        """Validate a declared person claim against the registry and its designated root."""
        self._reload_if_stale()
        if self._registry_load_error is not None:
            raise PersonContextBindingRegistryError(
                _PERSON_CONTEXT_BINDING_REGISTRY_UNAVAILABLE
            ) from self._registry_load_error
        matches = self._by_slug.get(claim, [])
        if not matches:
            return RefusedPersonContextBinding(PersonContextBindingRefusal.UNKNOWN)
        if len(matches) != 1:
            return RefusedPersonContextBinding(PersonContextBindingRefusal.AMBIGUOUS)
        person = matches[0]
        resolved_root = context_root.expanduser().resolve()
        if self._by_context_root.get(resolved_root) is not person:
            return RefusedPersonContextBinding(PersonContextBindingRefusal.DISAGREEING)
        return AcceptedPersonContextBinding(person)

    def resolve_by_email(self, email: str) -> IdentityContext:
        """Resolve identity from email address."""
        self._reload_if_stale()
        person = self._by_email.get(email.lower())
        if person:
            return IdentityContext(
                person_name=person.name,
                person_email=person.email,
                person_slug=person.slug,
                person_role=self._normalize_role(person.role),
                display_name_override=self._display_name_override_for(person),
                chip_color=self._color_by_email.get(email.lower()),
                avatar_url=self._avatar_url_for(person),
            )
        return IdentityContext()

    def resolve_lineage_person(self, email: str, *, session_id: str) -> IdentityContext | None:
        """The registered person a session's lineage email names, or ``None`` when the registry names none.

        A miss is registry drift — the lineage outlived its person's entry — and is reported once
        per email for each version of the registry.
        """
        context = self.resolve_by_email(email)
        if context.person_name is not None:
            return context
        reported_key = email.lower()
        if reported_key not in self._unregistered_lineage_reported:
            self._unregistered_lineage_reported.add(reported_key)
            logger.warning(_UNREGISTERED_LINEAGE_PERSON_EVENT, session_id=session_id)
        return None

    def resolve_exact_one_by_email(self, email: str) -> IdentityContext:
        """Resolve a person only when the verified email has exactly one configured owner."""
        self._reload_if_stale()
        matches = self._email_matches.get(email.lower(), [])
        if len(matches) != 1:
            return IdentityContext()
        person = matches[0]
        return IdentityContext(
            person_name=person.name,
            person_email=person.email,
            person_slug=person.slug,
            person_role=self._normalize_role(person.role),
            display_name_override=self._display_name_override_for(person),
            chip_color=self._color_by_email.get(person.email.lower()),
            avatar_url=self._avatar_url_for(person),
        )

    @property
    def registered_people_count(self) -> int:
        """Number of registered people in global config."""
        self._reload_if_stale()
        return self._registered_people_count

    @property
    def sole_person_email(self) -> str | None:
        """The registered email when exactly one person is registered, else None."""
        self._reload_if_stale()
        return self._sole_person_email

    @property
    def is_multi_user(self) -> bool:
        """Return whether more than one person is registered."""
        return self.registered_people_count > 1

    def effective_terminal_role(self, email: str | None) -> str | None:
        """Resolve the role a terminal caller holds under the current registry."""
        self._reload_if_stale()
        normalized_email = email.strip().lower() if email else None
        if normalized_email:
            person = self._by_email.get(normalized_email)
            if person:
                return self._normalize_role(person.role)
        return None

    def resolve(self, origin: str, origin_metadata: Mapping[str, object]) -> IdentityContext:
        """Resolve identity from origin and metadata.

        Args:
            origin: Source of the session (e.g. 'telegram', 'terminal').
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
                        person_slug=person.slug,
                        person_role=self._normalize_role(person.role),
                        display_name_override=self._display_name_override_for(person),
                        platform="terminal",
                        platform_user_id=email,
                        avatar_url=self._avatar_url_for(person),
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
                            person_slug=person.slug,
                            person_role=self._normalize_role(person.role),
                            display_name_override=self._display_name_override_for(person),
                            platform=_TELEGRAM_PLATFORM,
                            platform_user_id=str(uid_int),
                            avatar_url=self._avatar_url_for(person),
                        )
                    return IdentityContext(
                        person_role=HUMAN_ROLE_CUSTOMER,
                        platform=_TELEGRAM_PLATFORM,
                        platform_user_id=str(uid_int),
                    )
                except (ValueError, TypeError):
                    pass

        if origin == "discord":
            discord_user_id = origin_metadata.get("user_id") or origin_metadata.get("discord_user_id")
            if discord_user_id is not None:
                discord_uid_str = str(discord_user_id)
                person = self._by_discord_user_id.get(discord_uid_str)
                if person:
                    return IdentityContext(
                        person_name=person.name,
                        person_email=person.email,
                        person_slug=person.slug,
                        person_role=self._normalize_role(person.role),
                        display_name_override=self._discord_nick_by_user_id.get(discord_uid_str),
                        platform="discord",
                        platform_user_id=discord_uid_str,
                        avatar_url=self._avatar_url_for(person),
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
                        person_slug=person.slug,
                        person_role=self._normalize_role(person.role),
                        display_name_override=self._display_name_override_for(person),
                        platform="whatsapp",
                        platform_user_id=normalized_phone,
                        avatar_url=self._avatar_url_for(person),
                    )
                if normalized_phone:
                    return IdentityContext(
                        person_role=HUMAN_ROLE_CUSTOMER,
                        platform="whatsapp",
                        platform_user_id=normalized_phone,
                    )

        if origin == _GITHUB_PLATFORM:
            login = origin_metadata.get(_GITHUB_LOGIN)
            matches = self._by_github_handle.get(login.casefold(), []) if isinstance(login, str) else []
            if len(matches) == 1:
                person = matches[0]
                return IdentityContext(
                    person_name=person.name,
                    person_email=person.email,
                    person_slug=person.slug,
                    person_role=self._normalize_role(person.role),
                    display_name_override=self._display_name_override_for(person),
                    platform=_GITHUB_PLATFORM,
                    platform_user_id=str(login),
                    avatar_url=self._avatar_url_for(person),
                )

        return IdentityContext()


def derive_identity_key(origin_metadata: Mapping[str, object]) -> str | None:
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


_PERSON_KEY_KIND = "person"
_PERSON_KEY_PREFIX = f"{_PERSON_KEY_KIND}:"
_ADAPTER_PLATFORMS = ("discord", "telegram", "whatsapp")


@dataclass(frozen=True)
class MemoryPerson:
    """Who the person a conversation session serves is, as memory needs to know them.

    ``person_slug`` is set when the person is registered. The facts say who the
    person is; what a memory record is about is memory's choice.
    """

    identity_key: str
    principal: str
    person_slug: str | None

    @property
    def registered(self) -> bool:
        """Whether the platform knows the person as a registered person."""
        return self.person_slug is not None


def memory_person_for_session(session: Session) -> MemoryPerson | None:
    """The person a conversation session serves, or ``None`` when the session names no one.

    A registered person is keyed ``person:<slug>`` whichever adapter they write from,
    found through the session's human principal or its adapter binding. Anyone else is
    keyed by the platform identity they wrote from.
    """
    caller = identity_for_session(session).caller
    if isinstance(caller, PersonCliCaller) and caller.person_slug and caller.email:
        return _registered_person(caller.person_slug, caller.email)
    resolver = get_identity_resolver()
    for platform in _ADAPTER_PLATFORMS:
        section = session.get_origin_section(platform)
        if not section:
            continue
        context = resolver.resolve(platform, section)
        if context.person_slug and context.person_email:
            return _registered_person(context.person_slug, context.person_email)
    identity_key = derive_identity_key(session.origin_metadata)
    if identity_key is None:
        return None
    return MemoryPerson(identity_key=identity_key, principal=visitor_principal(identity_key), person_slug=None)


def memory_person_for_identity(reference: str) -> MemoryPerson | None:
    """The person an identity reference names, or ``None`` when it names no recognizable identity.

    The reference is a canonical person key (``person:<slug>``) or a provider-qualified key. A provider
    account bound to a registered person by that person's verified credentials resolves to the person,
    whatever their role; any other provider account stays the visitor it is. The reference is normalized
    exactly as entry binding normalizes it (a WhatsApp number is its digits).
    """
    kind, separator, value = reference.strip().partition(":")
    if not separator or not value:
        return None
    resolver = get_identity_resolver()
    if kind == _PERSON_KEY_KIND:
        person = resolver.person_by_slug(value)
        return _registered_person(value, person.email) if person is not None and person.slug else None
    if kind not in _ADAPTER_PLATFORMS:
        return None
    native_id = resolver._normalize_phone_number(value) if kind == _WHATSAPP_PLATFORM else value
    if not native_id:
        return None
    bound = resolver.person_for_provider_identity(kind, native_id)
    if bound is not None and bound.slug:
        return _registered_person(bound.slug, bound.email)
    identity_key = f"{kind}:{native_id}"
    return MemoryPerson(identity_key=identity_key, principal=visitor_principal(identity_key), person_slug=None)


def provider_identities_for_person(person_slug: str) -> tuple[str, ...]:
    """The provider-qualified identity keys a registered person's verified credentials bind."""
    return get_identity_resolver().provider_identities_for_person(person_slug)


def memory_person_reach(person: MemoryPerson) -> Reach:
    """What a session serving this person may read: a registered person's own reach, a visitor's own records.

    A registered person's reach also admits what their verified provider accounts recorded as visitors, since
    those accounts are theirs.
    """
    if person.person_slug is not None:
        reach = resolve_reach(caller_from_principal(person.principal))
        linked = frozenset(visitor_principal(key) for key in provider_identities_for_person(person.person_slug))
        return replace(reach, linked_principals=linked)
    return visitor_reach(person.identity_key)


def canonical_memory_identity(reference: str) -> str:
    """The identity key a reference names once verified bindings are applied; an unrecognized reference is its own."""
    person = memory_person_for_identity(reference)
    return person.identity_key if person is not None else reference


def _registered_person(person_slug: str, email: str) -> MemoryPerson:
    return MemoryPerson(
        identity_key=f"{_PERSON_KEY_PREFIX}{person_slug}",
        principal=human_principal_for_email(email),
        person_slug=person_slug,
    )


async def is_procedure_agent_session(session_id: str) -> bool:
    """Whether the session is an agent the platform started for a procedure, running under the system principal."""
    session = await db.get_session(session_id)
    if session is None:
        return False
    try:
        principal, _role = resolve_session_principal(session)
    except SessionIdentityError:
        return False
    if not principal.startswith(SYSTEM_PRINCIPAL_PREFIX):
        return False
    handover = await db.get_startup_handover(session_id)
    return handover is not None and handover.intent.entry_point is SessionEntryPoint.PROCEDURE_ACTIVATION


def caller_for_session(session: Session) -> CliCaller:
    """Resolve a session record into its current local CLI caller."""
    return identity_for_session(session).caller


def local_human_author(session: Session) -> MessageAuthor:
    """The author of human input typed into the session: the person its lineage names, else an unnamed human.

    Lineage presents a name and decides nothing about whether the input is carried
    (`general/concept/lineage-vs-authorship`).
    """
    if session.human_email:
        person = get_identity_resolver().resolve_lineage_person(session.human_email, session_id=session.session_id)
        if person is not None:
            return MessageAuthor.for_human(session_id=session.session_id, display_name=person.display_name)
    return MessageAuthor.for_human_without_lineage(session_id=session.session_id)


def resolve_discord_caller_header_alias(opening: str, *, owning_session_id: str) -> tuple[str, str | None]:
    """Present carried caller-header identity, retaining labels without a known runtime."""
    header = caller_header_identity(opening)
    assert header is not None
    session_id, label = header
    role_label, category_separator, category = label.partition(CALLER_CATEGORY_SEPARATOR)
    avatar: str | None = None
    job_role: str | None = None
    if role_label == MachineRoleLabel.AGENT and category_separator:
        runtime_label, role_separator, carried_role = category.partition(CALLER_CATEGORY_PART_SEPARATOR)
        try:
            presentation = AgentName.from_str(runtime_label).discord_presentation
        except ValueError:
            # Unknown carried runtimes retain their header label so their output remains visible.
            return resolve_discord_author_alias(
                MessageAuthor.for_machine(session_id=session_id, role_label=label), owning_session_id=owning_session_id
            )
        else:
            label, avatar = presentation.alias, presentation.avatar_url
            job_role = carried_role if role_separator else None
    author = MessageAuthor.for_machine(session_id=session_id, role_label=label)
    alias, _ = resolve_discord_author_alias(author, owning_session_id=owning_session_id, job_role=job_role)
    return alias, avatar


def resolve_discord_author_alias(
    author: MessageAuthor,
    *,
    owning_session_id: str,
    job_role: str | None = None,
) -> tuple[str, str | None]:
    """Resolve the canonical Discord alias and avatar for a durable author snapshot.

    Grammar: ``<Identity>[ - <role name>][ (peer)]``. Identity and avatar
    resolve from the immutable author snapshot (never from body text);
    ``job_role`` is the role name read from the author's own
    session at event time (``sessions.role``, never ``sessions.job``) and
    carried alongside the author as its own durable field — never re-derived
    here. Thinking mode never appears in the alias. The owning session
    renders its own author without ``(peer)``; any author from another
    session receives it — comparing the author's own session id against the
    session whose Discord thread is rendering, never text or a rendered
    header.
    """
    if author.kind is MessageAuthorKind.AGENT:
        assert author.agent_runtime is not None
        try:
            presentation = AgentName.from_str(author.agent_runtime).discord_presentation
        except ValueError:
            # A carried peer token can name a runtime absent locally; retain its
            # display text so a recognized peer span never becomes a refusal.
            identity, avatar = author.display, None
        else:
            identity, avatar = presentation.alias, presentation.avatar_url
    else:
        identity, avatar = author.display, None

    alias = identity
    if job_role:
        alias = f"{alias} - {job_role}"
    if author.session_id != owning_session_id:
        alias = f"{alias} (peer)"
    return alias, avatar
