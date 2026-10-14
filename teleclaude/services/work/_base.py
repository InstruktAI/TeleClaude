"""Base holder for WorkService — resolves the workflow store.

Sub-services (todo, state, artifacts) hold a reference to this base
and call _ensure_db() to get the canonical project store. The base exists
so sub-services share its canonical-root identity.
"""

from __future__ import annotations

from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store


class WorkServiceBase:
    """Resolves the canonical workflow store for all work sub-services."""

    def __init__(self, project_root: str) -> None:
        self._project_root = project_root
        self._db: WorkflowStore | None = None

    async def _ensure_db(self) -> WorkflowStore:
        if self._db is None:
            self._db = await get_workflow_store(self._project_root)
        return self._db

    @property
    def project_root(self) -> str:
        return self._project_root
