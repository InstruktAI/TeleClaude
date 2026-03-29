"""Todo lifecycle database — state, artifacts, and roadmap.

Replaces filesystem-based state.yaml, roadmap.yaml, delivered.yaml,
and todos/{slug}/*.md artifact files with a single SQLite store.
"""

from __future__ import annotations

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


async def get_todos_db(project_root: str) -> TodosDb:
    """Return a TodosDb instance for the given project root, creating if needed."""
    from pathlib import Path  # pylint: disable=import-outside-toplevel

    db_path = str(Path(project_root) / ".teleclaude" / "todos.db")
    if db_path not in _instances:
        instance = TodosDb(db_path)
        await instance.initialize()
        _instances[db_path] = instance
    return _instances[db_path]


__all__ = ["ArtifactVersionRow", "RoadmapRow", "TodosDb", "get_todos_db"]
