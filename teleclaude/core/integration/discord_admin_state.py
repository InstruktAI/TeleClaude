"""Integration-owned Discord administrative reflection-state contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

PROJECT_FORUM_KEY_PREFIX = "project_forum:"


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


class DiscordSharedChildKind(StrEnum):
    """Shared Discord child categories governed by the claim ledger."""

    HELP_DESK_SESSION = "help_desk_session"
    ESCALATION_RELAY = "escalation_relay"


class DiscordThreadClaimLifecycle(StrEnum):
    """Lifecycle state whose owner may reconcile a shared Discord child."""

    PENDING = "pending"
    ACTIVE = "active"
    TERMINAL = "terminal"


class DiscordThreadClaimOutcome(StrEnum):
    """Closed outcomes returned by the source-bound shared-child claim boundary."""

    OBSERVED = "observed"
    CLAIMED = "claimed"
    NOT_OWNER = "not_owner"
    REFUSED = "refused"


class DiscordThreadClaimMemberState(StrEnum):
    """Adoption state retained for every computer participating in the protocol."""

    OBSERVED = "observed"
    ADOPTED = "adopted"


class DiscordThreadReconciliationEpochPhase(StrEnum):
    """Durable state of one master-allocated reconciliation epoch."""

    OPEN = "open"
    COMPLETED = "completed"


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


@dataclass(frozen=True)
class DiscordSharedThreadClaim:
    """One source-bound contender or owner observation for a shared provider child."""

    thread_id: int
    parent_id: int
    kind: DiscordSharedChildKind
    computer: str
    local_identity: str
    lifecycle: DiscordThreadClaimLifecycle
    protocol_generation: int


@dataclass(frozen=True)
class DiscordSharedThreadClaimResult:
    """The durable owner decision for one shared provider child."""

    outcome: DiscordThreadClaimOutcome
    owner_computer: str | None
    lifecycle: DiscordThreadClaimLifecycle | None


@dataclass(frozen=True)
class DiscordThreadClaimActivation:
    """Whether durable membership and live capability evidence permit enforcement."""

    active: bool
    retained_members: tuple[str, ...]


@dataclass(frozen=True)
class DiscordThreadClaimInventoryItem:
    """One local shared-child fact submitted as part of a complete member inventory."""

    thread_id: int
    parent_id: int
    kind: DiscordSharedChildKind
    local_identity: str
    lifecycle: DiscordThreadClaimLifecycle


@dataclass(frozen=True)
class DiscordThreadOrphanCandidate:
    """The current durable garbage-collection proof for one shared child."""

    thread_id: int
    parent_id: int
    consecutive_complete_epochs: int


class DiscordReflectionRepository(Protocol):
    """Repository seam used by reconciliation without exposing database models."""

    async def get_discord_reflection(self, logical_key: str) -> DiscordReflectionRecord | None: ...

    async def list_discord_reflections(
        self, scope: DiscordReflectionScope | None = None
    ) -> list[DiscordReflectionRecord]: ...

    async def upsert_discord_reflection(self, record: DiscordReflectionRecord) -> None: ...

    async def touch_discord_reflection(self, logical_key: str, verified_at: datetime) -> None: ...

    async def delete_discord_reflection(self, logical_key: str) -> None: ...

    async def observe_discord_shared_thread(
        self, claim: DiscordSharedThreadClaim, *, source_computer: str, enforce_owner: bool
    ) -> DiscordSharedThreadClaimResult: ...

    async def get_discord_shared_thread_owner(self, thread_id: int) -> DiscordSharedThreadClaim | None: ...

    async def observe_discord_thread_claim_member(self, computer: str, *, protocol_generation: int) -> None: ...

    async def complete_discord_thread_claim_inventory(
        self, computer: str, *, protocol_generation: int, epoch: int
    ) -> bool: ...

    async def replace_discord_thread_claim_inventory(
        self,
        computer: str,
        *,
        protocol_generation: int,
        epoch: int,
        items: tuple[DiscordThreadClaimInventoryItem, ...],
    ) -> bool: ...

    async def open_discord_thread_reconciliation_epoch(self, *, protocol_generation: int) -> int: ...

    async def complete_discord_thread_reconciliation_epoch(self, *, protocol_generation: int, epoch: int) -> bool: ...

    async def discord_thread_claim_activation(
        self, *, protocol_generation: int, live_members: frozenset[str], capability_members: frozenset[str]
    ) -> DiscordThreadClaimActivation: ...

    async def advance_discord_thread_orphan_candidate(
        self, *, thread_id: int, parent_id: int, epoch: int
    ) -> DiscordThreadOrphanCandidate: ...

    async def reset_discord_thread_orphan_candidate(self, *, thread_id: int) -> None: ...

    async def completed_discord_thread_claim_epoch(self, *, protocol_generation: int) -> int | None: ...


def shared_key(name: str) -> str:
    """Build the stable logical key for one shared Discord artifact."""
    return f"shared:{name}"


def project_forum_key(identity: str) -> str:
    """Build the stable logical key for one registry identity's forum."""
    return f"{PROJECT_FORUM_KEY_PREFIX}{identity}"


def session_launcher_key(forum_id: int) -> str:
    """Build the stable logical key for one forum launcher."""
    return f"session_launcher:{forum_id}"
