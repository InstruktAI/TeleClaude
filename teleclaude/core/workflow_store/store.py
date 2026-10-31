"""Typed workflow store contract and canonical-root facade resolution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.constants import TodoStatus
from teleclaude.core.todos_db_path import github_working_copy_path, todos_db_path
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import DependencyEntry

from .github_io_transport import GitHubIORefused as GitHubIORefused
from .github_store import (
    close_github_workflow_stores,
    get_github_workflow_store,
    get_github_workflow_store_sync,
    set_github_workflow_store_hook,
)
from .local_store import (
    close_local_workflow_stores,
    get_local_workflow_store,
    get_local_workflow_store_sync,
    set_local_workflow_store_hook,
)
from .selection import selected_workflow_store_backend
from .types import (
    ArtifactMetadata,
    ArtifactRemoval,
    ArtifactVersion,
    ArtifactWriterSet,
    CommitReviewRecord,
    DocumentationAdmission,
    DocumentationEvidenceSnapshot,
    DocumentationTransferRecord,
    ExpiredRemovedItem,
    IdentityResolution,
    PurgedItem,
    RemovalRequest,
    StoreCapabilities,
    TodoDiagnosticRecord,
    TodoProjectionSnapshot,
    WorkItem,
    WorkItemId,
    WorkItemStateRead,
)

if TYPE_CHECKING:
    from teleclaude.core.next_machine.marker_reconciliation import MarkerReceipt

_DATABASE_NOT_FOUND_PREFIX = "Todos DB not found: "
_TODO_UPDATED_EVENT = "todo_updated"


class WorkflowStore(Protocol):
    """Typed workflow operations without local persistence handles."""

    @property
    def project_root(self) -> Path: ...

    @property
    def capabilities(self) -> StoreCapabilities: ...

    def set_workflow_hooks(
        self,
        on_mutation: Callable[[str, Mapping[str, object] | None], None],
        on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None],
        on_delivered: Callable[[str, str | None, str], None],
    ) -> None: ...
    def identity_scope(self, slug: str, todo_id: str) -> AbstractContextManager[None]: ...
    def notify_committed(
        self, event_hint: str = _TODO_UPDATED_EVENT, event_data: Mapping[str, object] | None = None
    ) -> None: ...
    async def create_item_with_initial_artifact(
        self,
        slug: str,
        state: dict[str, StateValue],
        *,
        lineage: str,
        group_slug: str | None,
        after: list[str] | None,
        description: str | None,
        schedule: str | None,
        status: TodoStatus,
        entry_point: str | None,
        human_involved: bool,
        context: str | None,
        cwd: str,
        artifact_name: str,
        artifact_body: str,
        updated_by: str | None,
        documentation_admission: DocumentationAdmission | None = None,
    ) -> WorkItemId: ...
    async def replace_item_state_and_artifacts(
        self,
        slug: str,
        state: dict[str, StateValue],
        *,
        replacement_input: str | None,
        deleted_artifacts: list[str],
    ) -> None: ...
    async def rename_item(self, old_slug: str, new_slug: str) -> None: ...
    async def update_state_with_artifact_evidence(
        self,
        slug: str,
        artifact_names: list[str],
        update: Callable[[dict[str, StateValue] | None, dict[str, str]], dict[str, StateValue]],
    ) -> dict[str, StateValue]: ...
    def read_todo_projection_snapshot_sync(self, statuses: tuple[TodoStatus, ...]) -> TodoProjectionSnapshot: ...
    def list_active_states_sync(self) -> list[tuple[str, dict[str, StateValue]]]: ...
    def read_state_sync(self, slug: str) -> dict[str, StateValue] | None: ...
    def write_state_sync(self, slug: str, state: dict[str, StateValue]) -> None: ...
    def read_artifact_sync(self, slug: str, name: str) -> str: ...
    def artifact_digest_sync(self, slug: str, name: str) -> str: ...
    async def append_commit_reviews(self, records: tuple[CommitReviewRecord, ...]) -> None: ...
    async def commit_review_records(self, shas: tuple[str, ...]) -> tuple[CommitReviewRecord, ...]: ...
    def commit_review_records_sync(self, shas: tuple[str, ...]) -> tuple[CommitReviewRecord, ...]: ...
    async def documentation_transfers(self, target_slug: str) -> tuple[DocumentationTransferRecord, ...]: ...
    def artifact_exists_sync(self, slug: str, name: str) -> bool: ...
    def write_artifact_sync(self, slug: str, name: str, content: str, *, updated_by: str | None = None) -> None: ...
    def resolve_store_address_sync(self, slug: str) -> str | None: ...
    def downstream_dependency_slugs_sync(self, slug: str) -> list[str]: ...
    def delivered_slugs_sync(self) -> set[str]: ...
    def clean_dep_references_sync(self, slug: str) -> None: ...
    def deliver_sync(
        self,
        slug: str,
        *,
        reconciliation_receipt: MarkerReceipt | None,
        reconciliation_root: Path,
        commit: str | None = None,
        children: list[str] | None = None,
    ) -> bool: ...
    async def list_todo(
        self,
        *,
        include_icebox: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
        include_removed: bool = False,
        removed_only: bool = False,
        include_holders: bool = False,
    ) -> list[WorkItem]: ...
    async def read_todo_diagnostic_record(self, slug: str) -> TodoDiagnosticRecord | None: ...
    async def add_to_todo(
        self,
        slug: str,
        *,
        lineage: str,
        group_slug: str | None = None,
        after: list[str] | None = None,
        description: str | None = None,
        schedule: str | None = None,
        status: TodoStatus = TodoStatus.ACTIVE,
        entry_point: str | None = None,
        human_involved: bool = False,
        context: str | None = None,
        cwd: str,
    ) -> WorkItemId: ...
    async def read_state(self, slug: str) -> dict[str, StateValue] | None: ...
    async def write_state(self, slug: str, state: dict[str, StateValue]) -> None: ...
    async def write_state_by_id(self, todo_id: str, state: dict[str, StateValue]) -> None: ...
    async def clear_active_runner_if_matches(self, todo_id: str, session_id: str) -> bool:
        """Atomically release matching driver fields, preserving other stored state."""
        ...

    async def delete_state(self, slug: str) -> None: ...
    async def read_state_by_id(self, todo_id: str) -> dict[str, StateValue] | None: ...
    async def read_state_delivered(self, slug: str) -> dict[str, StateValue] | None: ...
    async def read_status_and_states_by_id(self, todo_ids: list[str]) -> dict[str, WorkItemStateRead]: ...
    async def list_slugs(self) -> list[str]: ...
    async def read_lineage(self, slug: str) -> str | None: ...
    async def get_schedule(self, slug: str) -> str | None: ...
    async def set_schedule(self, slug: str, *, schedule: str | None) -> None: ...
    async def set_deps(self, slug: str, *, after: list[str]) -> None: ...
    async def get_deps(self, slug: str) -> list[str]: ...
    async def get_deps_with_status(self, slug: str) -> list[DependencyEntry]: ...
    async def load_deps(self) -> dict[str, list[str]]: ...
    async def get_open_dependents(self, slug: str) -> list[str]: ...
    async def delivered_slugs(self) -> set[str]: ...
    async def is_structural_group_holder(self, slug: str) -> bool: ...
    async def check_membership_update(
        self, slug: str, *, group_slug: str | None, group_present: bool, after: list[str] | None
    ) -> object: ...
    async def update_membership(
        self, slug: str, *, group_slug: str | None, after: list[str] | None, cwd: str
    ) -> None: ...
    async def is_bug_todo(self, slug: str) -> bool: ...
    async def has_pending_deferrals(self, slug: str) -> bool: ...
    async def freeze(self, slug: str) -> bool: ...
    async def unfreeze(
        self,
        slug: str,
        *,
        evidence_snapshot: DocumentationEvidenceSnapshot | None = None,
    ) -> bool: ...
    async def deliver(
        self,
        slug: str,
        *,
        reconciliation_receipt: MarkerReceipt | None,
        reconciliation_root: Path,
        commit: str | None = None,
        children: list[str] | None = None,
    ) -> bool: ...
    async def read_artifact(self, slug: str, name: str, *, include_removed: bool = False) -> str: ...
    async def read_artifact_by_id(self, todo_id: str, name: str) -> str: ...
    async def artifact_exists(self, slug: str, name: str) -> bool: ...
    async def artifact_digest(self, slug: str, name: str) -> str: ...
    async def list_artifacts(self, slug: str) -> list[str]: ...
    async def list_artifacts_with_writers(
        self, slug: str, *, include_removed: bool = False
    ) -> list[ArtifactWriterSet]: ...
    async def artifact_metadata(self, slug: str) -> list[ArtifactMetadata]: ...
    async def artifact_metadata_by_id(self, todo_id: str) -> list[ArtifactMetadata]: ...
    async def artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[ArtifactVersion]: ...
    async def write_artifact(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
        refuse_executing_contract: bool = False,
    ) -> None: ...
    async def delete_artifact(self, slug: str, name: str) -> ArtifactRemoval: ...
    async def delete_artifacts(self, slug: str) -> None: ...
    async def artifacts_diff(
        self, slug: str, name: str, old_digest: str, new_digest: str, *, include_removed: bool = False
    ) -> str: ...
    async def resolve_live_slug_by_id(self, todo_id: str) -> IdentityResolution: ...
    async def slug_in_todo(self, slug: str) -> bool: ...
    async def admit_item_write(
        self, *, slug: str | None = None, todo_id: str | None = None, retained: bool = False
    ) -> None: ...
    def slug_recorded_sync(self, slug: str) -> bool: ...
    async def has_removed_todo(self, slug: str) -> bool: ...
    async def find_live_slug_conflict(self, slug: str) -> str | None: ...
    async def slug_conflicts_non_removed(self, slug: str) -> bool: ...
    async def removed_todo_claims_active_runner(self, slug: str, session_id: str) -> bool: ...
    async def soft_remove_from_todo(
        self, slug: str, *, cwd: str, removal_context: RemovalRequest | None = None
    ) -> bool: ...
    async def reactivate_removed(self, todo_id: str, *, cwd: str) -> str: ...
    async def list_expired_removed(self, cutoff_iso: str) -> list[ExpiredRemovedItem]: ...
    async def set_pending_purge_paths(self, row_id: str, paths: list[str]) -> None: ...
    async def clear_pending_purge_paths(self, row_id: str) -> None: ...
    async def purge_one_removed(self, row_id: str) -> PurgedItem | None: ...


def set_workflow_store_mutation_hook(hook: Callable[[WorkflowStore, str], None] | None) -> None:
    """Attach the daemon's cache invalidation hook to newly resolved stores."""
    set_local_workflow_store_hook(hook)
    set_github_workflow_store_hook(hook)


async def get_workflow_store(project_root_or_cwd: str | Path) -> WorkflowStore:
    path = todos_db_path(project_root_or_cwd)
    if selected_workflow_store_backend(path.parent.parent) is TodoStoreBackend.GITHUB:
        return await get_github_workflow_store(project_root_or_cwd)
    return await get_local_workflow_store(project_root_or_cwd)


def get_workflow_store_sync(project_root_or_cwd: str | Path) -> WorkflowStore:
    path = todos_db_path(project_root_or_cwd)
    if selected_workflow_store_backend(path.parent.parent) is TodoStoreBackend.GITHUB:
        return get_github_workflow_store_sync(project_root_or_cwd)
    return get_local_workflow_store_sync(project_root_or_cwd)


def write_workflow_artifact_sync(project_root: str | Path, slug: str, name: str, content: str) -> None:
    """Write a local artifact through the selected store, preserving no-create refusal."""
    root = todos_db_path(project_root).parent.parent
    path = (
        github_working_copy_path(root)
        if selected_workflow_store_backend(root) is TodoStoreBackend.GITHUB
        else todos_db_path(root)
    )
    if not path.exists():
        raise FileNotFoundError(f"{_DATABASE_NOT_FOUND_PREFIX}{path}")
    get_workflow_store_sync(project_root).write_artifact_sync(slug, name, content)


async def close_workflow_stores() -> None:
    await close_local_workflow_stores()
    await close_github_workflow_stores()
