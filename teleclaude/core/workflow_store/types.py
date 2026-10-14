"""Backend-neutral workflow-store values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, NamedTuple, NewType, Protocol, TypedDict

from teleclaude.constants import TodoStatus
from teleclaude.types.state_value import StateValue

WorkItemId = NewType("WorkItemId", str)
"""Canonical workflow identity: the stable todo slug."""

StoreAddress = NewType("StoreAddress", str)
"""Adapter address for identity-pinned row operations; never workflow identity."""


class StorePresenceKind(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"
    INVALID = "invalid"


class StoreIntegrityStatus(StrEnum):
    OK = "ok"
    ABSENT = "absent"
    FAILED = "failed"


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


class WorkItem(TypedDict):
    id: str
    slug: str
    ready_since: str | None
    schedule: str | None
    group_id: str | None
    description: str | None
    status: str
    delivered_at: str | None
    delivered_commit: str | None
    updated_at: str
    created_at: str
    removed_at: str | None
    children: list[str] | None
    lineage: str | None
    entry_point: str | None
    human_involved: bool
    context: str | None


TODO_DIAGNOSTIC_FIELD_STATUS: Final = "status"
TODO_DIAGNOSTIC_FIELD_DELIVERED_AT: Final = "delivered_at"
TODO_DIAGNOSTIC_FIELD_DELIVERED_COMMIT: Final = "delivered_commit"


class TodoDiagnosticRecord(TypedDict):
    """Complete persisted todo row as serialized by the diagnostic surfaces."""

    id: str
    slug: str
    ready_since: str | None
    schedule: str | None
    group_id: str | None
    description: str | None
    status: str
    delivered_at: str | None
    delivered_commit: str | None
    children: str | None
    lineage: str | None
    entry_point: str | None
    human_involved: bool
    context: str | None
    removed_at: str | None
    prev_status: str | None
    removed_deps: str | None
    removed_claim: str | None
    removed_doc_reconciliation: str | None
    pending_purge_paths: str | None
    created_at: str
    updated_at: str


class ArtifactWriterSet(TypedDict):
    name: str
    writers: list[str]


class ArtifactMetadata(TypedDict):
    name: str
    digest: str
    updated_by: str
    updated_at: str


class ArtifactRemoval(TypedDict):
    removed: bool
    versions_deleted: int


class WorkItemStateRead(NamedTuple):
    status: str | None
    state: dict[str, StateValue] | None
    is_structural_group_holder: bool


class DependencyStatus(NamedTuple):
    dep_slug: str
    todo_status: TodoStatus


class IdentityResolution(NamedTuple):
    slug: WorkItemId
    status: TodoStatus


class ExpiredRemovedItem(TypedDict):
    id: str
    slug: str
    removed_at: str
    pending_purge_paths: list[str] | None


class PurgedItem(TypedDict):
    id: str
    slug: str
    removed_at: str


class RemovalRequest(TypedDict):
    force: bool
    operation_id: str | None
    caller_session_id: str | None


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


class ArtifactVersion(TypedDict):
    """Immutable artifact body revision and its attribution."""

    content: str
    digest: str
    created_at: str
    updated_by: str


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
