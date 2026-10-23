"""Backend-neutral workflow-store values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, NamedTuple, NewType, Protocol, TypedDict

from teleclaude.constants import TodoStatus
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import CommitReviewVerdict

WorkItemId = NewType("WorkItemId", str)
"""Canonical identity assigned by the selected adapter; opaque to consumers."""

StoreAddress = NewType("StoreAddress", str)
"""Adapter address for identity-pinned row operations; never workflow identity."""


@dataclass(frozen=True)
class ItemChange:
    """The result of an atomic item change: the state to persist and the log entry to append with it.

    ``converted_from`` is the legacy phase the change replaced when it converted the row, with the ``conversion_path``
    that did it; the converted-row record is inserted in the same transaction.
    """

    state: dict[str, StateValue]
    log_entry: str = ""
    converted_from: str = ""
    conversion_path: str = ""


class ConversionPath(StrEnum):
    """The path a row was converted by, as the converted-row record stores it."""

    ACTIVATION = "activation"
    RESTORE = "restore"
    CAPABILITY = "capability"


@dataclass(frozen=True)
class ActivationRow:
    """One item row as an activation pass reads it inside its transaction."""

    row_id: str
    slug: str
    status: str
    state: dict[str, StateValue]
    has_input: bool
    has_design_spec: bool
    converted: bool


@dataclass(frozen=True)
class RowRewrite:
    """The state an activation pass writes for one row, and the legacy phase it replaced when it converts the row."""

    row_id: str
    state: dict[str, StateValue]
    converted_from: str = ""
    path: ConversionPath = ConversionPath.ACTIVATION


class ActivationRefused(Exception):
    """The activation did not complete; nothing was written and the store stays unmarked."""


@dataclass(frozen=True)
class PendingEffectItem:
    """An item row, whatever its status, that holds effects the workflow machine has not finished."""

    todo_id: str
    slug: str
    status: str


class ArtifactRevisionMismatch(Exception):
    """An artifact is not at the revision an atomic change required; nothing was written."""

    def __init__(self, name: str, expected: str, actual: str) -> None:
        super().__init__(name, expected, actual)
        self.name = name
        self.expected = expected
        self.actual = actual


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
    atomic_item_change: bool


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
class CommitReviewRecord:
    """Immutable repository-local evidence for one reviewed commit."""

    sha: str
    verdict: CommitReviewVerdict
    reviewer_session_id: str
    producer_session_ids: tuple[str, ...] | None
    stamped_at: str
    reason: str
    migration_source: str | None = None

    @property
    def independent(self) -> bool:
        """Whether verified producer provenance excludes the reviewer."""
        return bool(self.producer_session_ids) and self.reviewer_session_id not in self.producer_session_ids


@dataclass(frozen=True)
class ReviewedDocumentationSource:
    """A carrier path proven to match an independently reviewed source commit."""

    owner_slug: str
    source_sha: str
    relative_path: str
    blob_id: str
    carrier_path: str
    carrier_blob_id: str


@dataclass(frozen=True)
class DocumentationAdmission:
    """Pinned first-child parent identity and its reviewed pending source set."""

    parent_slug: str | None
    parent_id: str | None
    parent_status: TodoStatus | None
    sources: tuple[ReviewedDocumentationSource, ...]
    carrier_path_blobs: tuple[tuple[str, str], ...]
    source_commit_by_path: tuple[tuple[str, str | None], ...]
    evidence_snapshot: DocumentationEvidenceSnapshot | None


@dataclass(frozen=True)
class DocumentationEvidenceSnapshot:
    """Exact canonical evidence set checked before a lifecycle mutation."""

    main_revision: str
    checked_slugs: tuple[str, ...]
    carrier_blobs: tuple[tuple[str, str, str], ...]
    sources: tuple[ReviewedDocumentationSource, ...]
    review_records: tuple[CommitReviewRecord, ...]
    transfer_records: tuple[DocumentationTransferRecord, ...]


@dataclass(frozen=True)
class DocumentationTransferRecord:
    """Exact source-to-child continuity produced by a successful marker split."""

    source_slug: str
    target_slug: str
    parent_id: str
    source_sha: str | None
    source_path_blobs: tuple[tuple[str, str], ...]
    target_path_blobs: tuple[tuple[str, str, str, str, str], ...]
    transition_id: str
    reconciliation_commit: str


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
