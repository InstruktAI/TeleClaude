"""Integration-owned Discord administrative reflection-state contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

PROJECT_FORUM_KEY_PREFIX = "project_forum:"
HELP_DESK_KEY_PREFIX = "help_desk:"
_HELP_DESK_ARTIFACT_SEPARATOR = "."


class DiscordProvider(StrEnum):
    """Supported provider identity for this reflection repository."""

    DISCORD = "discord"


class DiscordArtifactKind(StrEnum):
    """Closed set of reflected Discord artifact classes."""

    CATEGORY = "category"
    TEXT_CHANNEL = "text_channel"
    FORUM = "forum"
    FORUM_THREAD = "forum_thread"
    MESSAGE = "message"


class DiscordScopeKind(StrEnum):
    """Ownership categories for reflection records."""

    SHARED = "shared"
    MACHINE = "machine"
    PROJECT = "project"
    PERSON = "person"


class HelpDeskArtifact(StrEnum):
    """The Discord artifacts one help desk's category holds, with the category itself."""

    CATEGORY = "category"
    CUSTOMER_SESSIONS = "customer_sessions"
    ESCALATIONS = "escalations"
    TEAM_CHAT = "team_chat"


class DiscordVerificationResult(StrEnum):
    """Provider lookup result used by reconciliation decisions."""

    VERIFIED = "verified"
    CONCLUSIVELY_ABSENT = "conclusively_absent"
    INCONCLUSIVE = "inconclusive"


class DiscordReflectionOutcome(StrEnum):
    """Terminal reconciliation outcomes."""

    VERIFIED = "verified"
    ADOPTED = "adopted"
    CREATED = "created"
    STALE_REPLACED = "stale_replaced"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"
    FAILED_CLOSED = "failed_closed"


@dataclass(frozen=True)
class DiscordReflectionScope:
    """Opaque reflection ownership identity retained by the repository only."""

    kind: DiscordScopeKind
    value: str


@dataclass(frozen=True)
class DiscordReflectionRecord:
    """One durable observed Discord artifact binding."""

    provider: DiscordProvider
    logical_key: str
    artifact_kind: DiscordArtifactKind
    scope: DiscordReflectionScope
    provider_id: int
    parent_provider_id: int | None
    metadata_json: str
    verified_at: datetime | None


class DiscordReflectionRepository(Protocol):
    """Repository seam used by reconciliation without exposing database models."""

    async def get_discord_reflection(self, logical_key: str) -> DiscordReflectionRecord | None: ...

    async def list_discord_reflections(
        self, scope: DiscordReflectionScope | None = None
    ) -> list[DiscordReflectionRecord]: ...

    async def upsert_discord_reflection(self, record: DiscordReflectionRecord) -> None: ...

    async def touch_discord_reflection(self, logical_key: str, verified_at: datetime) -> None: ...

    async def delete_discord_reflection(self, logical_key: str) -> None: ...


def shared_key(name: str) -> str:
    """Build the stable logical key for one shared Discord artifact."""
    return f"shared:{name}"


def project_forum_key(identity: str) -> str:
    """Build the stable logical key for one registry identity's forum."""
    return f"{PROJECT_FORUM_KEY_PREFIX}{identity}"


def session_launcher_key(forum_id: int) -> str:
    """Build the stable logical key for one forum launcher."""
    return f"session_launcher:{forum_id}"


def help_desk_key(entry_identifier: str, artifact: HelpDeskArtifact) -> str:
    """Build the stable logical key for one artifact of the help desk an entry identifier names."""
    return f"{HELP_DESK_KEY_PREFIX}{entry_identifier}{_HELP_DESK_ARTIFACT_SEPARATOR}{artifact.value}"


def parse_help_desk_key(logical_key: str) -> tuple[str, HelpDeskArtifact] | None:
    """The entry identifier and artifact a help-desk logical key names, or ``None`` for any other key."""
    if not logical_key.startswith(HELP_DESK_KEY_PREFIX):
        return None
    entry_identifier, separator, artifact = logical_key.removeprefix(HELP_DESK_KEY_PREFIX).rpartition(
        _HELP_DESK_ARTIFACT_SEPARATOR
    )
    if not separator:
        return None
    try:
        return entry_identifier, HelpDeskArtifact(artifact)
    except ValueError:
        return None
