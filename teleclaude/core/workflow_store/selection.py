"""Backend selection and read-only adapter helpers for workflow state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from teleclaude.config.loader import load_declared_project_config
from teleclaude.config.project_models import TodoStoreBackend, TodoStoreConfig
from teleclaude.constants import TodoStatus
from teleclaude.core.todos_db_path import github_working_copy_path, todos_db_path

from .local import (
    check_local_database_integrity,
    get_local_transfer_source,
    local_database_location,
    local_store_presence,
    read_local_validation_status_rows,
)
from .types import StoreIntegrityStatus, StorePresence, StorePresenceKind, TransferSource

_TRANSFER_UNAVAILABLE = "not transferable: the project's workflow state lives in GitHub"
_READ_ONLY_URI_SUFFIX = "?mode=ro"
_INTEGRITY_CHECK_SQL = "PRAGMA integrity_check"
_SCHEMA_VERSION_SQL = "PRAGMA schema_version"
_WORKING_COPY_MISSING = "project workflow working copy is missing"
_WORKING_COPY_UNREADABLE = "project workflow working copy cannot be read"
_INTEGRITY_NO_RESULT = "integrity check returned no result"
_GITHUB_STATUS_QUERY = (
    "SELECT todo.slug, todo.status, todo.delivered_commit FROM todo "
    "JOIN todo_state ON todo_state.slug = todo.slug WHERE todo.status IN (?, ?, ?, ?)"
)
_STATUS_VALUES = (
    TodoStatus.ACTIVE.value,
    TodoStatus.ICEBOX.value,
    TodoStatus.DELIVERED.value,
    TodoStatus.REMOVED.value,
)


class WorkflowStoreNotTransferable(RuntimeError):
    """The selected store has no local replica that the state-transfer tool can copy."""


def selected_workflow_store_config(project_root: Path) -> TodoStoreConfig:
    """Read declared store settings, using defaults when no project is declared."""
    project = load_declared_project_config(project_root)
    return project.todos if project is not None else TodoStoreConfig()


def selected_workflow_store_backend(project_root: Path) -> TodoStoreBackend:
    """Read the declared backend for a project root without opening its store."""
    return selected_workflow_store_config(project_root).store


def inspect_workflow_store_presence(project_root: str | Path) -> StorePresence:
    """Read selected-store presence without creating or migrating local state."""
    root = todos_db_path(project_root).parent.parent
    if selected_workflow_store_backend(root) is TodoStoreBackend.LOCAL:
        return local_store_presence(root)
    return _github_store_presence(root)


def read_workflow_validation_status_rows(project_root: str | Path) -> list[tuple[str, str, str | None]] | None:
    """Read validation facts through the selected adapter without bootstrapping."""
    root = todos_db_path(project_root).parent.parent
    if selected_workflow_store_backend(root) is TodoStoreBackend.LOCAL:
        return read_local_validation_status_rows(root)
    path = github_working_copy_path(root)
    if not path.is_file():
        return None
    with sqlite3.connect(path.as_uri() + _READ_ONLY_URI_SUFFIX, uri=True) as connection:
        rows = connection.execute(_GITHUB_STATUS_QUERY, _STATUS_VALUES).fetchall()
    return [
        (slug, status, delivered if isinstance(delivered, str) else None)
        for slug, status, delivered in rows
        if isinstance(slug, str) and isinstance(status, str)
    ]


def get_workflow_transfer_source(project_root: str | Path) -> TransferSource | None:
    """Get the selected adapter's opaque transfer source."""
    root = todos_db_path(project_root).parent.parent
    if selected_workflow_store_backend(root) is TodoStoreBackend.GITHUB:
        raise WorkflowStoreNotTransferable(_TRANSFER_UNAVAILABLE)
    return get_local_transfer_source(root)


def workflow_store_database_location(project_root: str | Path) -> str | None:
    """Resolve a destination location through the selected adapter boundary."""
    root = todos_db_path(project_root).parent.parent
    if selected_workflow_store_backend(root) is TodoStoreBackend.GITHUB:
        raise WorkflowStoreNotTransferable(_TRANSFER_UNAVAILABLE)
    return local_database_location(root)


def check_workflow_store_integrity(project_root: str | Path) -> tuple[StoreIntegrityStatus, str]:
    """Run the selected adapter's read-only integrity check."""
    root = todos_db_path(project_root).parent.parent
    if selected_workflow_store_backend(root) is TodoStoreBackend.LOCAL:
        return check_local_database_integrity(root)
    path = github_working_copy_path(root)
    if not path.is_file():
        return StoreIntegrityStatus.ABSENT, _WORKING_COPY_MISSING
    try:
        with sqlite3.connect(path.as_uri() + _READ_ONLY_URI_SUFFIX, uri=True) as connection:
            result = connection.execute(_INTEGRITY_CHECK_SQL).fetchone()
    except sqlite3.Error:
        return StoreIntegrityStatus.FAILED, _WORKING_COPY_UNREADABLE
    if result is None or result[0] != StoreIntegrityStatus.OK.value:
        return StoreIntegrityStatus.FAILED, str(result[0]) if result else _INTEGRITY_NO_RESULT
    return StoreIntegrityStatus.OK, StoreIntegrityStatus.OK.value


def _github_store_presence(project_root: Path) -> StorePresence:
    path = github_working_copy_path(project_root)
    if not path.is_file():
        return StorePresence(StorePresenceKind.ABSENT)
    try:
        with sqlite3.connect(path.as_uri() + _READ_ONLY_URI_SUFFIX, uri=True) as connection:
            connection.execute(_SCHEMA_VERSION_SQL).fetchone()
    except sqlite3.Error:
        return StorePresence(StorePresenceKind.INVALID, _WORKING_COPY_UNREADABLE)
    return StorePresence(StorePresenceKind.PRESENT)
