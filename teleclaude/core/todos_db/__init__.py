"""Todo lifecycle database for roadmap state and text artifacts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from teleclaude.project_root import resolve_state_root

from ._artifacts import TodosDbArtifactsMixin
from ._base import TodosDbBase
from ._roadmap import TodosDbRoadmapMixin
from ._roadmap_soft_delete import TodosDbRoadmapSoftDeleteMixin
from ._rows import ArtifactVersionRow, RoadmapRow
from ._state import TodosDbStateMixin


class TodosDb(
    TodosDbArtifactsMixin,
    TodosDbRoadmapMixin,
    TodosDbRoadmapSoftDeleteMixin,
    TodosDbStateMixin,
    TodosDbBase,
):
    """Database interface for todo lifecycle state and artifacts."""


_instances: dict[str, TodosDb] = {}

# Hook called whenever get_todos_db or get_todos_db_sync creates a new instance.
# The daemon registers a hook that wires instance._on_mutation to its cache
# refresh. None in CLI and test contexts.
_new_instance_hook: Callable[[TodosDb, str], None] | None = None


def set_todos_mutation_hook(hook: Callable[[TodosDb, str], None] | None) -> None:
    """Register (or clear) the hook called when a new TodosDb instance is created.

    The daemon uses this to wire cache invalidation into every TodosDb instance
    so that local DB mutations immediately refresh the TUI todos pane.

    Args:
        hook: Callable receiving (instance, project_root), or None to clear.
    """
    global _new_instance_hook
    _new_instance_hook = hook


async def get_todos_db(project_root_or_cwd: str | Path) -> TodosDb:
    """Return a TodosDb instance for the canonical state root, creating if needed."""
    project_root = str(resolve_state_root(project_root_or_cwd))
    db_path = str(Path(project_root) / ".teleclaude" / "todos.db")
    if db_path not in _instances:
        instance = TodosDb(db_path)
        await instance.initialize()
        if _new_instance_hook is not None:
            _new_instance_hook(instance, project_root)
        _instances[db_path] = instance
    return _instances[db_path]


async def close_todos_db_instances() -> None:
    """Close and clear memoized todo DB instances for one-shot CLI commands."""
    instances = list(_instances.values())
    _instances.clear()
    for instance in instances:
        await instance.close()


def get_todos_db_sync(project_root_or_cwd: str | Path) -> TodosDb:
    """Sync sibling of get_todos_db: resolve project root, return cached TodosDb."""
    project_root = str(resolve_state_root(project_root_or_cwd))
    db_path = str(Path(project_root) / ".teleclaude" / "todos.db")
    if db_path not in _instances:
        instance = TodosDb(db_path)
        instance.initialize_sync()
        if _new_instance_hook is not None:
            _new_instance_hook(instance, project_root)
        _instances[db_path] = instance
    return _instances[db_path]


__all__ = [
    "ArtifactVersionRow",
    "RoadmapRow",
    "TodosDb",
    "close_todos_db_instances",
    "get_todos_db",
    "get_todos_db_sync",
    "set_todos_mutation_hook",
]
