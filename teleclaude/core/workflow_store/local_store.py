"""Local persistence adapter over the current SQLite workflow store."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

from teleclaude.core.todos_db import (
    TodosDb,
    close_todos_db_instances,
    get_todos_db,
    get_todos_db_sync,
    set_todos_mutation_hook,
)

if TYPE_CHECKING:
    from .store import WorkflowStore


async def get_local_workflow_store(project_root_or_cwd: str | Path) -> WorkflowStore:
    """Resolve the canonical cached local implementation for async callers."""
    return cast(WorkflowStore, await get_todos_db(project_root_or_cwd))


def get_local_workflow_store_sync(project_root_or_cwd: str | Path) -> WorkflowStore:
    """Resolve the canonical cached local implementation for native sync callers."""
    return cast(WorkflowStore, get_todos_db_sync(project_root_or_cwd))


def set_local_workflow_store_hook(hook: Callable[[WorkflowStore, str], None] | None) -> None:
    """Attach the single instance hook used by the local adapter cache."""
    set_todos_mutation_hook(cast(Callable[[TodosDb, str], None] | None, hook))


async def close_local_workflow_stores() -> None:
    """Close the local adapter's canonical cached instances."""
    await close_todos_db_instances()
