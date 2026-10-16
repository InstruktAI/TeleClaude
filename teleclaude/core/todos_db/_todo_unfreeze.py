"""Evidence-bound unfreeze mutation for todo lifecycle entry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.documentation_evidence import (
    DocumentationEvidenceRefused,
    require_reviewed_pending_documentation,
)
from teleclaude.core.todos_db._identity_pin import apply_todo_identity_pin
from teleclaude.core.todos_db._models import TODO_TABLE, Todo
from teleclaude.core.workflow_store.types import DocumentationEvidenceSnapshot
from teleclaude.docs_reconcile import pending_document_carriers
from teleclaude.git_lock import main_branch_lock_async

_UNFREEZE_EVIDENCE_REQUIRED = "pending documentation requires a current evidence snapshot before unfreeze"
_UNFREEZE_EVIDENCE_CHANGED = "documentation evidence changed before unfreeze; submit a fresh request"
_TODO_UPDATED_EVENT = "todo_updated"


class _TodoUnfreezeHost(Protocol):
    db_path: str
    _on_mutation: Callable[[str, Mapping[str, object] | None], None]

    @property
    def project_root(self) -> Path: ...

    def _session(self) -> AbstractAsyncContextManager[SqlAsyncSession]: ...

    async def _stamp_ready_since_for_slug_if_eligible(
        self,
        session: SqlAsyncSession,
        slug: str,
        *,
        delivered_slugs: set[str],
    ) -> None: ...


class TodosDbTodoUnfreezeMixin:
    async def unfreeze(
        self: _TodoUnfreezeHost,
        slug: str,
        *,
        evidence_snapshot: DocumentationEvidenceSnapshot | None = None,
    ) -> bool:
        """Restore an iceboxed todo only while its checked evidence remains current."""
        async with main_branch_lock_async():
            async with self._session() as session:
                async with session.begin():
                    if evidence_snapshot is None:
                        if pending_document_carriers(self.project_root, slug):
                            raise DocumentationEvidenceRefused(_UNFREEZE_EVIDENCE_REQUIRED)
                    else:
                        current_evidence = await require_reviewed_pending_documentation(
                            self.project_root,
                            self,
                            evidence_snapshot.checked_slugs,
                            session=session,
                        )
                        if current_evidence != evidence_snapshot:
                            raise DocumentationEvidenceRefused(_UNFREEZE_EVIDENCE_CHANGED)
                    statement = (
                        select(Todo)
                        .where(
                            TODO_TABLE.c.slug == slug,
                            TODO_TABLE.c.status == TodoStatus.ICEBOX.value,
                        )
                        .limit(1)
                    )
                    result = await session.exec(apply_todo_identity_pin(statement, self, slug))
                    entry = result.first()
                    if entry is None:
                        return False
                    entry.status = TodoStatus.ACTIVE.value
                    entry.updated_at = datetime.now(UTC).isoformat()
                    session.add(entry)
                    delivered_result = await session.exec(
                        select(Todo.slug).where(TODO_TABLE.c.status == TodoStatus.DELIVERED.value)
                    )
                    delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
                    await self._stamp_ready_since_for_slug_if_eligible(
                        session,
                        slug,
                        delivered_slugs=delivered_slugs,
                    )
        self._on_mutation(_TODO_UPDATED_EVENT, None)
        return True
