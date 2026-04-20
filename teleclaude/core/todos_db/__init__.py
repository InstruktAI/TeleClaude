"""Todo lifecycle database for roadmap state and text artifacts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ._artifacts import TodosDbArtifactsMixin
from ._base import TodosDbBase
from ._roadmap import TodosDbRoadmapMixin
from ._rows import ArtifactVersionRow, RoadmapRow
from ._state import TodosDbStateMixin


class TodosDb(
    TodosDbArtifactsMixin,
    TodosDbRoadmapMixin,
    TodosDbStateMixin,
    TodosDbBase,
):
    """Database interface for todo lifecycle state and artifacts."""


_instances: dict[str, TodosDb] = {}

# Optional hook called whenever get_todos_db or _get_todos_db_sync creates a new
# instance. The hook receives (instance, project_root) and is responsible for
# setting instance._on_mutation to a callable that invalidates the daemon cache.
# Defaults to None (no-op in CLI and test contexts).
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


async def get_todos_db(project_root: str) -> TodosDb:
    """Return a TodosDb instance for the given project root, creating if needed."""
    db_path = str(Path(project_root) / ".teleclaude" / "todos.db")
    if db_path not in _instances:
        instance = TodosDb(db_path)
        await instance.initialize()
        if _new_instance_hook is not None:
            _new_instance_hook(instance, project_root)
        _instances[db_path] = instance
    return _instances[db_path]


__all__ = ["ArtifactVersionRow", "RoadmapRow", "TodosDb", "get_todos_db", "set_todos_mutation_hook"]
