"""Integration-owned Discord administrative reflection-state contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


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


def project_forum_key(project_path: str) -> str:
    """Build the stable logical key for one project forum."""
    return f"project_forum:{project_path}"


def session_launcher_key(forum_id: int) -> str:
    """Build the stable logical key for one forum launcher."""
    return f"session_launcher:{forum_id}"
