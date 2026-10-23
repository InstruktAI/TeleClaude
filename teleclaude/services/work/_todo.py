"""Todo operations — list, add, freeze, deliver, deps."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.api_models import BugListEntryDTO, TodoDTO
from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, coerce_lifecycle_phase
from teleclaude.core.next_machine.marker_reconciliation import MarkerMoment, reconcile_lifecycle_markers
from teleclaude.core.next_machine.review_evidence import BuildReviewVerdict
from teleclaude.core.todo import assemble_todo_from_db
from teleclaude.core.workflow_store.store import get_workflow_store_sync
from teleclaude.core.workflow_store.types import WorkItemId
from teleclaude.types.todo_kind import TodoKind

if TYPE_CHECKING:
    from teleclaude.services.work._base import WorkServiceBase


logger = get_logger(__name__)


class _TodoStateField(StrEnum):
    KIND = "kind"
    LIFECYCLE_PHASE = "lifecycle_phase"
    BUILD_REVIEW = "build_review"
    FINALIZE = "finalize"
    VERDICT = "verdict"
    STATUS = "status"


class BugFixStatus(StrEnum):
    APPROVED = "approved"
    FIXING = "fixing"
    REVIEWING = "reviewing"
    BUILDING = "building"
    PENDING = "pending"


_EMPTY_TEXT = ""
_PENDING_FINALIZE_STATUSES = frozenset({_EMPTY_TEXT, TodoStatus.PENDING.value})


class TodoOps:
    """Todo reads and mutations.

    Held by SqliteWorkService and accessed as `svc.todo`.
    """

    def __init__(self, base: WorkServiceBase) -> None:
        self._base = base

    # -- reads ----------------------------------------------------------------

    def entries(
        self,
        *,
        include_icebox: bool = False,
        icebox_only: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
        delivered_since: str | None = None,
        include_removed: bool = False,
        removed_only: bool = False,
    ) -> list[TodoDTO]:
        """Return todo entries as TodoDTOs. Synchronous."""
        return assemble_todo_from_db(
            self._base.project_root,
            include_icebox=include_icebox,
            icebox_only=icebox_only,
            include_delivered=include_delivered,
            delivered_only=delivered_only,
            delivered_since=delivered_since,
            include_removed=include_removed,
            removed_only=removed_only,
        )

    def bug_entries(self) -> list[BugListEntryDTO]:
        """Return active bug todos with their workflow progress labels."""
        rows = get_workflow_store_sync(self._base.project_root).list_active_states_sync()

        bugs: list[BugListEntryDTO] = []
        for slug, state in rows:
            if state.get(_TodoStateField.KIND) != TodoKind.BUG:
                continue
            lifecycle_phase = coerce_lifecycle_phase(state.get(_TodoStateField.LIFECYCLE_PHASE))
            build_review = state.get(_TodoStateField.BUILD_REVIEW, {})
            finalize = state.get(_TodoStateField.FINALIZE, {})

            verdict = (
                str(build_review.get(_TodoStateField.VERDICT, _EMPTY_TEXT))
                if isinstance(build_review, dict)
                else _EMPTY_TEXT
            )
            finalize_status = (
                str(finalize.get(_TodoStateField.STATUS, _EMPTY_TEXT)) if isinstance(finalize, dict) else _EMPTY_TEXT
            )

            if verdict == BuildReviewVerdict.APPROVE or finalize_status not in _PENDING_FINALIZE_STATUSES:
                status = BugFixStatus.APPROVED
            elif verdict == BuildReviewVerdict.CHANGES_REQUESTED:
                status = BugFixStatus.FIXING
            elif lifecycle_phase is LifecyclePhase.BUILD_COMPLETE:
                status = BugFixStatus.REVIEWING
            elif lifecycle_phase is LifecyclePhase.BUILD_STARTED:
                status = BugFixStatus.BUILDING
            else:
                status = BugFixStatus.PENDING

            bugs.append(BugListEntryDTO(slug=slug, status=status.value))
        return bugs

    def get_entry(self, slug: str, *, include_icebox: bool = True, include_delivered: bool = True) -> TodoDTO | None:
        """Return a single todo entry as a TodoDTO, or None if not found.

        Uses the same rich projection as entries() — callers get consistent
        domain types whether they ask for one or many.
        """
        for todo in self.entries(
            include_icebox=include_icebox,
            include_delivered=include_delivered,
        ):
            if todo.slug == slug:
                return todo
        return None

    async def dependencies(self, slug: str) -> list[str]:
        db = await self._base._ensure_db()
        return await db.get_deps(slug)

    async def dependents(self, slug: str) -> list[str]:
        db = await self._base._ensure_db()
        all_deps = await db.load_deps()
        return [s for s, deps in all_deps.items() if slug in deps]

    async def all_dependencies(self) -> dict[str, list[str]]:
        db = await self._base._ensure_db()
        return await db.load_deps()

    async def delivered_slugs(self) -> set[str]:
        db = await self._base._ensure_db()
        return await db.delivered_slugs()

    # -- mutations ------------------------------------------------------------

    async def add(
        self,
        slug: str,
        *,
        lineage: str,
        description: str = "",
        group: str | None = None,
        after: str | list[str] | None = None,
    ) -> WorkItemId:
        """Add a new todo entry.

        ``lineage`` is the caller's resolved Creation Record chain — this
        primitive has no door of its own, so the caller supplies it.
        """
        db = await self._base._ensure_db()
        after_list: list[str] | None
        if isinstance(after, str):
            after_list = [p.strip() for p in after.split(",") if p.strip()]
        else:
            after_list = after
        return await db.add_to_todo(
            slug,
            lineage=lineage,
            group_slug=group,
            after=after_list,
            description=description,
            cwd=self._base.project_root,
        )

    async def remove(self, slug: str) -> bool:
        db = await self._base._ensure_db()
        return await db.soft_remove_from_todo(slug, cwd=self._base.project_root)

    async def set_dependencies(self, slug: str, *, after: list[str]) -> None:
        db = await self._base._ensure_db()
        await db.set_deps(slug, after=after)

    async def freeze(self, slug: str) -> bool:
        db = await self._base._ensure_db()
        return await db.freeze(slug)

    async def unfreeze(self, slug: str) -> bool:
        db = await self._base._ensure_db()
        return await db.unfreeze(slug)

    async def deliver(self, slug: str, *, commit: str | None = None) -> bool:
        db = await self._base._ensure_db()
        receipt = reconcile_lifecycle_markers(Path(self._base.project_root), slug, MarkerMoment.DELIVER)
        if not receipt.succeeded:
            # The boolean says it failed; without the reason a caller cannot tell a
            # dirty path awaiting its owner from a genuine reconciliation fault.
            logger.error(
                "Delivery marker reconciliation did not apply",
                slug=slug,
                reason=receipt.reason,
                project_root=str(self._base.project_root),
            )
            return False
        return await db.deliver(
            slug,
            reconciliation_receipt=receipt,
            reconciliation_root=Path(self._base.project_root),
            commit=commit,
        )
