"""Backend-neutral workflow-store values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NewType, Protocol

from teleclaude.types.state_value import StateValue

WorkItemId = NewType("WorkItemId", str)
"""Canonical workflow identity: the stable todo slug."""

StoreAddress = NewType("StoreAddress", str)
"""Adapter address for identity-pinned row operations; never workflow identity."""


class StorePresenceKind(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"
    INVALID = "invalid"


@dataclass(frozen=True)
class StorePresence:
    kind: StorePresenceKind
    detail: str | None = None


@dataclass(frozen=True)
class StoreCapabilities:
    local_items: bool
    claims: bool
    phases: bool
    artifacts: bool
    revision_stamps: bool
    trail: bool
    delivery_candidates: bool
    incremental_replica_transfer: bool


@dataclass(frozen=True)
class TransferResult:
    returncode: int
    stderr: bytes


class TransferSource(Protocol):
    async def sync_to(self, tool_path: Path, destination: str, remote_tool_path: str) -> TransferResult: ...


@dataclass(frozen=True)
class ClaimHolder:
    """Live workflow claim holder, separate from structural grouping."""

    session_id: str
    role: str | None = None


@dataclass(frozen=True)
class GroupMembership:
    """Structural parent relation, separate from live session claims."""

    parent: WorkItemId | None


@dataclass(frozen=True)
class ArtifactVersion:
    """Immutable content revision and its attribution."""

    revision: str
    created_at: str
    updated_by: str | None


@dataclass(frozen=True)
class DeliveryRecord:
    """Confirmed delivery of one item to a root commit."""

    item_id: WorkItemId
    root_sha: str
    delivered_at: str


@dataclass(frozen=True)
class ArtifactFile:
    name: str
    updated_at: str | None


@dataclass(frozen=True)
class TodoProjectionItem:
    item_id: WorkItemId
    store_address: StoreAddress
    ready_since: str | None
    schedule: str | None
    group_address: StoreAddress | None
    description: str | None
    status: str
    delivered_at: str | None
    updated_at: str | None
    created_at: str | None
    removed_at: str | None
    lineage: str | None
    entry_point: str | None
    human_involved: bool
    context: str | None
    state: dict[str, StateValue] | None
    state_error: str | None
    has_requirements: bool
    has_implementation_plan: bool
    artifact_files: tuple[ArtifactFile, ...]
    version_total: int


@dataclass(frozen=True)
class TodoProjectionMetrics:
    init_seconds: float
    connection_seconds: float
    item_query_seconds: float
    dependency_query_seconds: float
    state_query_seconds: float
    artifact_query_seconds: float
    item_build_seconds: float


@dataclass(frozen=True)
class TodoProjectionSnapshot:
    items: tuple[TodoProjectionItem, ...]
    delivered_items: frozenset[WorkItemId]
    dependencies: dict[WorkItemId, list[WorkItemId]]
    structural_group_slugs: dict[StoreAddress, WorkItemId]
    metrics: TodoProjectionMetrics
