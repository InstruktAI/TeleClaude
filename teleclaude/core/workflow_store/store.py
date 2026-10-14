"""Typed workflow store contract and canonical-root facade resolution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from teleclaude.config.loader import load_declared_project_config
from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.marker_reconciliation import MarkerReceipt
from teleclaude.core.todos_db._rows import ArtifactVersionRow
from teleclaude.core.todos_db_path import todos_db_path
from teleclaude.types.state_value import StateValue

from .local_store import (
    close_local_workflow_stores,
    get_local_workflow_store,
    get_local_workflow_store_sync,
    set_local_workflow_store_hook,
)
from .types import TodoProjectionSnapshot


class StoreUnavailable(RuntimeError):
    """The project selected a workflow-store adapter that is not installed."""


class WorkflowStore(Protocol):
    """Backend-neutral operations consumed by workflow code.

    Implementations own persistence details. In particular, this protocol has
    no connection, table, path, or arbitrary mutation escape hatch.
    """

    def downstream_dependency_slugs_sync(self, item_id: str) -> list[str]: ...

    def delivered_slugs_sync(self) -> set[str]: ...

    def clean_dep_references_sync(self, item_id: str) -> None: ...

    def read_state_sync(self, item_id: str) -> dict[str, StateValue] | None: ...

    def list_active_states_sync(self) -> list[tuple[str, dict[str, StateValue]]]: ...

    def write_state_sync(self, item_id: str, state: dict[str, StateValue]) -> None: ...

    def read_artifact_sync(self, item_id: str, name: str) -> str: ...

    def artifact_digest_sync(self, item_id: str, name: str) -> str: ...

    def artifact_exists_sync(self, item_id: str, name: str) -> bool: ...

    def read_todo_projection_snapshot_sync(self, statuses: tuple[TodoStatus, ...]) -> TodoProjectionSnapshot: ...

    def deliver_sync(
        self,
        item_id: str,
        *,
        reconciliation_receipt: MarkerReceipt | None,
        reconciliation_root: Path,
        commit: str | None = None,
        children: list[str] | None = None,
    ) -> bool: ...

    def write_artifact_sync(self, item_id: str, name: str, content: str, *, updated_by: str | None = None) -> None: ...

    def set_workflow_hooks(
        self,
        on_mutation: Callable[[str, Mapping[str, object] | None], None],
        on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None],
        on_delivered: Callable[[str, str | None, str], None],
    ) -> None: ...

    async def get_deps(self, item_id: str) -> list[str]: ...

    async def load_deps(self) -> dict[str, list[str]]: ...

    async def delivered_slugs(self) -> set[str]: ...

    async def add_to_todo(
        self,
        item_id: str,
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
    ) -> bool: ...

    async def soft_remove_from_todo(self, item_id: str, *, cwd: str) -> bool: ...

    async def set_deps(self, item_id: str, *, after: list[str]) -> None: ...

    async def freeze(self, item_id: str) -> bool: ...

    async def unfreeze(self, item_id: str) -> bool: ...

    async def deliver(
        self,
        item_id: str,
        *,
        reconciliation_receipt: MarkerReceipt | None,
        reconciliation_root: Path,
        commit: str | None = None,
        children: list[str] | None = None,
    ) -> bool: ...

    async def read_artifact(self, item_id: str, name: str) -> str: ...

    async def artifact_exists(self, item_id: str, name: str) -> bool: ...

    async def artifact_digest(self, item_id: str, name: str) -> str: ...

    async def list_artifacts(self, item_id: str) -> list[str]: ...

    async def artifact_versions(self, item_id: str, name: str, *, limit: int = 50) -> list[ArtifactVersionRow]: ...

    async def write_artifact(self, item_id: str, name: str, content: str, *, updated_by: str | None = None) -> None: ...

    async def delete_artifacts(self, item_id: str) -> None: ...

    async def read_state(self, item_id: str) -> dict[str, StateValue] | None: ...

    async def write_state(self, item_id: str, state: dict[str, StateValue]) -> None: ...

    async def delete_state(self, item_id: str) -> None: ...

    async def list_slugs(self) -> list[str]: ...

    async def is_bug_todo(self, item_id: str) -> bool: ...

    async def has_pending_deferrals(self, item_id: str) -> bool: ...


def set_workflow_store_mutation_hook(hook: Callable[[WorkflowStore, str], None] | None) -> None:
    """Attach the daemon's cache invalidation hook to newly resolved stores."""
    set_local_workflow_store_hook(hook)


async def get_workflow_store(project_root_or_cwd: str | Path) -> WorkflowStore:
    path = todos_db_path(project_root_or_cwd)
    _require_local_adapter(path.parent.parent)
    return await get_local_workflow_store(project_root_or_cwd)


def get_workflow_store_sync(project_root_or_cwd: str | Path) -> WorkflowStore:
    path = todos_db_path(project_root_or_cwd)
    _require_local_adapter(path.parent.parent)
    return get_local_workflow_store_sync(project_root_or_cwd)


def write_workflow_artifact_sync(project_root: str | Path, item_id: str, name: str, content: str) -> None:
    """Write a local artifact through the selected store, preserving no-create refusal."""
    path = todos_db_path(project_root)
    _require_local_adapter(path.parent.parent)
    if not path.exists():
        raise FileNotFoundError(f"Todos DB not found: {path}")
    get_workflow_store_sync(project_root).write_artifact_sync(item_id, name, content)


def _require_local_adapter(project_root: Path) -> None:
    """Select the project adapter before touching local storage."""
    project = load_declared_project_config(project_root)
    selected = project.todos.store if project is not None else "local"
    if selected == "github":
        raise StoreUnavailable("Todo store 'github' is not available in this installation")


async def close_workflow_stores() -> None:
    await close_local_workflow_stores()
