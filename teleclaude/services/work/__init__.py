"""Work service package — SQLite implementation of the work domain.

Public exports:
    SqliteWorkService — the service class
    get_work_service  — factory with per-project caching

Sub-services (accessible via svc.todo, svc.state, svc.artifacts):
    TodoOps, StateOps, ArtifactOps
"""

from teleclaude.services.work._artifacts import ArtifactOps
from teleclaude.services.work._state import StateOps
from teleclaude.services.work._todo import TodoOps
from teleclaude.services.work.service import SqliteWorkService, get_work_service

__all__ = [
    "ArtifactOps",
    "SqliteWorkService",
    "StateOps",
    "TodoOps",
    "get_work_service",
]
