"""Todo group and dependency membership updates."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.dep_graph import group_dependency_conflict
from teleclaude.core.next_machine.marker_reconciliation import (
    MarkerMoment,
    MarkerReceipt,
    reconcile_lifecycle_markers,
    restore_lifecycle_markers,
)
from teleclaude.core.todos_db._errors import (
    GroupCycleRefused,
    GroupDependencyConflict,
    HolderReconciliationRefused,
)
from teleclaude.core.todos_db._models import TODO_DEPS_TABLE, TODO_TABLE, Todo, TodoDep, TodoStateModel
from teleclaude.core.workflow_store.types import DocumentationAdmission


class _TodoMembershipHost(Protocol):
    """Todo aggregate capabilities used by the membership mixin."""

    def _session(self) -> SqlAsyncSession: ...

    def on_committed(
        self,
        event_hint: str = "todo_updated",
        event_data: Mapping[str, object] | None = None,
    ) -> None: ...

    async def _active_entry(self, session: SqlAsyncSession, slug: str) -> Todo | None: ...

    async def _resolve_group_parent(self, session: SqlAsyncSession, group_slug: str) -> Todo | None: ...

    async def _validate_holder_transition(
        self,
        session: SqlAsyncSession,
        parent: Todo,
        group_slug: str,
    ) -> TodoStateModel | None: ...

    async def _upgrade_to_holder(
        self,
        session: SqlAsyncSession,
        group_slug: str,
        *,
        first_child_slug: str,
        project_root: Path,
        documentation_admission: DocumentationAdmission | None = None,
        allow_unreviewed_transfer: bool = False,
    ) -> tuple[str, MarkerReceipt | None]: ...

    async def set_deps(self, slug: str, *, after: list[str], session: SqlAsyncSession | None = None) -> None: ...

    async def _check_membership_update(
        self,
        session: SqlAsyncSession,
        slug: str,
        *,
        group_slug: str | None,
        group_present: bool,
        after: list[str] | None,
    ) -> tuple[Todo, Todo | None]: ...


class TodosDbTodoMembershipMixin:
    """Membership mutation operations on the todo aggregate."""

    async def _check_membership_update(
        self: _TodoMembershipHost,
        session: SqlAsyncSession,
        slug: str,
        *,
        group_slug: str | None,
        group_present: bool,
        after: list[str] | None,
    ) -> tuple[Todo, Todo | None]:
        """Resolve and validate an effective group/dependency pair without writing."""
        entry = await self._active_entry(session, slug)
        if entry is None:
            raise ValueError(f"no active/icebox todo for slug: {slug}")

        target: Todo | None = None
        effective_group_id = entry.group_id
        if group_present:
            if group_slug:
                target = await self._resolve_group_parent(session, group_slug)
                if target is None:
                    raise ValueError(f"cannot group under unknown todo: {group_slug!r}")
                if target.id == entry.id:
                    raise GroupCycleRefused(f"todo '{slug}' cannot be grouped under itself")

                seen_ids: set[str] = set()
                ancestor: Todo | None = target
                while ancestor is not None:
                    if ancestor.id == entry.id:
                        raise GroupCycleRefused(
                            f"todo '{slug}' cannot be grouped under '{group_slug}': the target is in its holder chain"
                        )
                    if ancestor.id in seen_ids:
                        raise GroupCycleRefused(
                            f"todo '{slug}' cannot be grouped under '{group_slug}': "
                            "the target holder chain contains a cycle"
                        )
                    seen_ids.add(ancestor.id)
                    ancestor = await session.get(Todo, ancestor.group_id) if ancestor.group_id else None

                if target.status != TodoStatus.HOLDER.value:
                    await self._validate_holder_transition(session, target, group_slug)
                effective_group_id = target.id
            else:
                effective_group_id = None

        rows_result = await session.exec(
            select(Todo).where(
                TODO_TABLE.c.status.in_((TodoStatus.ACTIVE.value, TodoStatus.ICEBOX.value, TodoStatus.HOLDER.value))
            )
        )
        rows = rows_result.all()
        slug_by_id = {row.id: row.slug for row in rows}
        group_slugs = {row.slug: slug_by_id.get(row.group_id) if row.group_id is not None else None for row in rows}
        effective_group_slug = slug_by_id.get(effective_group_id) if effective_group_id is not None else None

        if after is None:
            deps_result = await session.exec(select(TodoDep.depends_on).where(TODO_DEPS_TABLE.c.slug == slug))
            effective_after = {str(dep) for dep in deps_result.all()}
        else:
            effective_after = set(after)

        conflict = group_dependency_conflict(group_slugs, slug, effective_group_slug, effective_after)
        if conflict is not None:
            raise GroupDependencyConflict(slug, conflict)
        return entry, target

    async def check_membership_update(
        self: _TodoMembershipHost,
        slug: str,
        *,
        group_slug: str | None = None,
        group_present: bool = True,
        after: list[str] | None = None,
    ) -> None:
        """Check a requested group/dependency pair before the update facade writes."""
        async with self._session() as session:
            await self._check_membership_update(
                session,
                slug,
                group_slug=group_slug,
                group_present=group_present,
                after=after,
            )

    async def update_membership(
        self: _TodoMembershipHost,
        slug: str,
        *,
        group_slug: str | None,
        after: list[str] | None,
        cwd: str,
    ) -> None:
        """Atomically replace a todo's group and optional dependency set."""
        project_root = Path(cwd)
        split_receipt: MarkerReceipt | None = None
        db_commit_landed = False
        async with self._session() as session:
            try:
                entry, target = await self._check_membership_update(
                    session,
                    slug,
                    group_slug=group_slug,
                    group_present=True,
                    after=after,
                )
                target_id: str | None = None
                if target is not None:
                    if target.status == TodoStatus.HOLDER.value:
                        target_id = target.id
                    else:
                        target_id, split_receipt = await self._upgrade_to_holder(
                            session,
                            group_slug or "",
                            first_child_slug=slug,
                            project_root=project_root,
                        )

                if entry.group_id != target_id:
                    entry.group_id = target_id
                    entry.updated_at = datetime.now(UTC).isoformat()
                    session.add(entry)
                if after is not None:
                    await self.set_deps(slug, after=after, session=session)

                await session.commit()
                db_commit_landed = True
                self.on_committed("todo_updated")
            except Exception:
                if not db_commit_landed:
                    await session.rollback()
                if split_receipt is not None and split_receipt.plan is not None:
                    restore_lifecycle_markers(project_root, group_slug or slug, split_receipt.plan)
                raise

        try:
            regroup_receipt = reconcile_lifecycle_markers(project_root, slug, MarkerMoment.REGROUP)
            if not regroup_receipt.succeeded:
                raise HolderReconciliationRefused(
                    f"cannot regroup todo {slug!r}: marker reconciliation failed ({regroup_receipt.reason})"
                )
        except Exception:
            if split_receipt is not None and split_receipt.plan is not None:
                restore_lifecycle_markers(project_root, group_slug or slug, split_receipt.plan)
            raise


__all__ = ["TodosDbTodoMembershipMixin"]
