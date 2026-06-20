"""SqliteWorkService — facade composing focused sub-services.

The service exposes sub-services as properties:
    svc.todo   — todo-list ordering/dependency storage operations
    svc.state     — todo state read, write, delete, list, classify
    svc.artifacts — artifact read, write, list, versions, digest

Callers get one service instance; each domain concern lives in its own
focused class. No mixins, no multiple inheritance.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.services.work._artifacts import ArtifactOps
from teleclaude.services.work._base import WorkServiceBase
from teleclaude.services.work._state import StateOps
from teleclaude.services.work._todo import TodoOps


class SqliteWorkService(WorkServiceBase):
    """Work service backed by TodosDb (SQLite).

    Composes TodoOps, StateOps, and ArtifactOps as sub-services.
    Each sub-service is a plain class with a focused responsibility.
    """

    def __init__(self, project_root: str) -> None:
        super().__init__(project_root)
        self._todo = TodoOps(self)
        self._state = StateOps(self)
        self._artifacts = ArtifactOps(self)

    @property
    def todo(self) -> TodoOps:
        return self._todo

    @property
    def state(self) -> StateOps:
        return self._state

    @property
    def artifacts(self) -> ArtifactOps:
        return self._artifacts


# -- Service factory ----------------------------------------------------------

_instances: dict[str, SqliteWorkService] = {}


def get_work_service(project_root: str) -> SqliteWorkService:
    """Return a cached WorkService for the given project root."""
    resolved = str(Path(project_root).resolve())
    if resolved not in _instances:
        _instances[resolved] = SqliteWorkService(resolved)
    return _instances[resolved]
