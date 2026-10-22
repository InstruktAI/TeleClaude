"""Backend selection and read-only adapter helpers for workflow state."""

from __future__ import annotations

from pathlib import Path

from teleclaude.config.loader import load_declared_project_config
from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.core.todos_db_path import todos_db_path

from .local import (
    check_local_database_integrity,
    get_local_transfer_source,
    local_database_location,
    local_store_presence,
    read_local_validation_status_rows,
)
from .types import StoreIntegrityStatus, StorePresence, TransferSource

_UNAVAILABLE_GITHUB_STORE = "Todo store 'github' is not available in this installation"


class StoreUnavailable(RuntimeError):
    """The project selected a workflow-store adapter that is not installed."""


def selected_workflow_store_backend(project_root: Path) -> TodoStoreBackend:
    """Read the declared backend for a project root without opening its store."""
    project = load_declared_project_config(project_root)
    return project.todos.store if project is not None else TodoStoreBackend.LOCAL


def _require_local_adapter(project_root: Path) -> None:
    """Select the project adapter before touching local storage."""
    if selected_workflow_store_backend(project_root) is TodoStoreBackend.GITHUB:
        raise StoreUnavailable(_UNAVAILABLE_GITHUB_STORE)


def inspect_workflow_store_presence(project_root: str | Path) -> StorePresence:
    """Read selected-store presence without creating or migrating local state."""
    path = todos_db_path(project_root)
    _require_local_adapter(path.parent.parent)
    return local_store_presence(project_root)


def read_workflow_validation_status_rows(project_root: str | Path) -> list[tuple[str, str, str | None]] | None:
    """Read validation facts through the selected adapter without bootstrapping."""
    path = todos_db_path(project_root)
    _require_local_adapter(path.parent.parent)
    return read_local_validation_status_rows(project_root)


def get_workflow_transfer_source(project_root: str | Path) -> TransferSource | None:
    """Get the selected adapter's opaque transfer source."""
    path = todos_db_path(project_root)
    _require_local_adapter(path.parent.parent)
    return get_local_transfer_source(project_root)


def workflow_store_database_location(project_root: str | Path) -> str | None:
    """Resolve a destination location through the selected adapter boundary."""
    path = todos_db_path(project_root)
    _require_local_adapter(path.parent.parent)
    return local_database_location(project_root)


def check_workflow_store_integrity(project_root: str | Path) -> tuple[StoreIntegrityStatus, str]:
    """Run the selected adapter's read-only integrity check."""
    path = todos_db_path(project_root)
    _require_local_adapter(path.parent.parent)
    return check_local_database_integrity(project_root)
