"""Base holder for WorkService — owns the TodosDb connection.

Sub-services (todo, state, artifacts) hold a reference to this base
and call _ensure_db() to get a ready TodosDb instance. The base exists
so sub-services don't each own their own connection lifecycle.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.todos_db import TodosDb


class WorkServiceBase:
    """Owns the TodosDb lifecycle for all work sub-services."""

    def __init__(self, project_root: str) -> None:
        self._project_root = project_root
        self._db: TodosDb | None = None

    async def _ensure_db(self) -> TodosDb:
        if self._db is None:
            db_path = str(Path(self._project_root) / ".teleclaude" / "todos.db")
            db = TodosDb(db_path)
            await db.initialize()
            self._db = db
        return self._db

    @property
    def project_root(self) -> str:
        return self._project_root
