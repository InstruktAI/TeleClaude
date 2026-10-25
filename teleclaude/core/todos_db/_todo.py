"""Todo persistence mixin."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy import delete, update
from sqlmodel import Session as SqlSession
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import TodoStatus
from teleclaude.core.next_machine.lifecycle import (
    apply_authoritative_signal,
    coerce_lifecycle_phase,
    is_ready_band_eligible,
    lifecycle_phase_index,
)
from teleclaude.core.next_machine.marker_reconciliation import (
    MarkerMoment,
    MarkerReceipt,
    reconcile_lifecycle_markers,
    restore_lifecycle_markers,
)
from teleclaude.core.todos_db._errors import (
    DeliveryProvenanceRefused,
    HolderReconciliationRefused,
    HolderTransitionRefused,
)
from teleclaude.core.todos_db._identity_pin import apply_todo_identity_pin
from teleclaude.core.todos_db._models import (
    TODO_DEPS_TABLE,
    TODO_TABLE,
    Todo,
    TodoDep,
    TodoStateModel,
)
from teleclaude.core.todos_db._rows import TodoRow
from teleclaude.core.todos_db._schema_bootstrap import _generate_id
from teleclaude.core.todos_db._todo_documentation_transfer import (
    DocumentationTransferWriter,
    persist_documentation_transfers,
    validate_documentation_admission,
)
from teleclaude.core.todos_db._todo_membership import TodosDbTodoMembershipMixin
from teleclaude.core.todos_db._todo_state_helpers import collect_entry_updates, readiness_state_fields
from teleclaude.core.todos_db._upcycle import canonicalize_state_for_storage, upcycle_state_dict
from teleclaude.core.workflow_store.types import DocumentationAdmission, WorkItemId
from teleclaude.docs_reconcile import pending_document_carriers
from teleclaude.types.lifecycle import LIFECYCLE_PHASE_ORDER, LifecyclePhase
from teleclaude.types.todo_kind import TodoKind
from teleclaude.types.todos import DependencyEntry, TodoState

_ACTIVE_TODO_STATUS = "active"
_ACTIVE_OR_ICEBOX = (TodoStatus.ACTIVE.value, TodoStatus.ICEBOX.value)
_UNKNOWN_GROUP_TEMPLATE = "cannot group under unknown todo: {slug!r}"
_GROUP_ADMISSION_CHANGED = "todo {slug!r} changed after documentation admission; resubmit the create request"
_GROUP_PENDING_DOCS_UNADMITTED = (
    "todo {slug!r} carries pending documentation; use active creation after its review evidence is current"
)


def _require_delivery_receipt(receipt: MarkerReceipt | None) -> None:
    """Prevent persistence callers from bypassing marker reconciliation."""
    if receipt is None or receipt.moment is not MarkerMoment.DELIVER or not receipt.succeeded:
        raise ValueError("delivery requires a successful marker reconciliation receipt")


def _require_delivery_provenance(slug: str, state_model: TodoStateModel | None, commit: str | None) -> None:
    """Require commit provenance for every delivery except a task terminal."""
    if commit and commit.strip():
        return
    try:
        kind = (
            TodoState.model_validate(upcycle_state_dict(json.loads(state_model.state))).kind
            if state_model is not None
            else None
        )
    except (TypeError, ValueError):
        kind = None
    if kind != TodoKind.TASK:
        raise DeliveryProvenanceRefused(slug, kind)


def _delivered_state(raw_state: str) -> str:
    """Apply delivery through the lifecycle authority before persisting state.

    Supplies no artifact write timestamps: this is a synchronous string
    transform with no ``TodosDb`` to read them from, and the ``delivery_evidence``
    signal branches to its terminal transition before either derivation site
    that would consult the mapping.
    """
    state = TodoState.model_validate(upcycle_state_dict(json.loads(raw_state)))
    apply_authoritative_signal(state, "delivery_evidence", artifact_write_timestamps={})
    return json.dumps(canonicalize_state_for_storage(state.model_dump(exclude_none=True)))


def _todo_row(model: Todo) -> TodoRow:
    """Convert a todo ORM model to the public typed row shape."""
    children = json.loads(model.children) if model.children else None
    return TodoRow(
        id=model.id,
        slug=model.slug,
        ready_since=model.ready_since,
        schedule=model.schedule,
        group_id=model.group_id,
        description=model.description,
        status=model.status,
        delivered_at=model.delivered_at,
        delivered_commit=model.delivered_commit,
        updated_at=model.updated_at,
        created_at=model.created_at,
        removed_at=model.removed_at,
        children=children if isinstance(children, list) else None,
        lineage=model.lineage,
        entry_point=model.entry_point,
        human_involved=model.human_involved,
        context=model.context,
    )


class TodosDbTodoMixin(TodosDbTodoMembershipMixin):
    """Todo CRUD, ordering, deps, delivery, icebox (replaces todo.yaml)."""

    _on_mutation: Callable[[str, Mapping[str, object] | None], None]
    _on_delivered: Callable[[str, str | None, str], None]
    db_path: str

    async def _active_entry(self, session: SqlAsyncSession, slug: str) -> Todo | None:
        """Return the live (active or icebox) todo entry for a slug.

        Excludes both ``delivered`` and ``removed``: a soft-removed row is
        invisible to every default resolver, mirroring the closed-session model.
        """
        statement = select(Todo).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
        result = await session.exec(apply_todo_identity_pin(statement, self, slug))
        return result.first()

    async def _resolve_group_parent(self, session: SqlAsyncSession, group_slug: str) -> Todo | None:
        """Resolve a ``--group`` target: active, icebox, or an already-existing holder."""
        statement = (
            select(Todo)
            .where(
                TODO_TABLE.c.slug == group_slug,
                TODO_TABLE.c.status.in_(("active", "icebox", TodoStatus.HOLDER.value)),
            )
            .limit(1)
        )
        result = await session.exec(apply_todo_identity_pin(statement, self, group_slug))
        return result.first()

    async def _upgrade_to_holder(
        self,
        session: SqlAsyncSession,
        group_slug: str,
        *,
        first_child_slug: str,
        project_root: Path,
        documentation_admission: DocumentationAdmission | None = None,
        allow_unreviewed_transfer: bool = False,
    ) -> tuple[str, MarkerReceipt | None]:
        """Promote an eligible live target to holder, returning its id and split receipt.

        Existing holders attach unchanged. Other targets must be pre-prepared; their
        lifecycle state is removed and artifacts remain frozen. Missing, invalid,
        unordered, or at/past-prepared phases refuse because conversion removes state.
        """
        parent = await self._resolve_group_parent(session, group_slug)
        if parent is None:
            raise ValueError(_UNKNOWN_GROUP_TEMPLATE.format(slug=group_slug))
        if documentation_admission is not None:
            if documentation_admission.parent_slug != group_slug:
                raise HolderTransitionRefused(_GROUP_ADMISSION_CHANGED.format(slug=group_slug))
            if documentation_admission.parent_id != parent.id or (
                documentation_admission.parent_status is None
                or documentation_admission.parent_status.value != parent.status
            ):
                raise HolderTransitionRefused(_GROUP_ADMISSION_CHANGED.format(slug=group_slug))
        if parent.status == TodoStatus.HOLDER.value:
            return parent.id, None
        if (
            documentation_admission is None
            and pending_document_carriers(project_root, group_slug)
            and not allow_unreviewed_transfer
        ):
            raise HolderTransitionRefused(_GROUP_PENDING_DOCS_UNADMITTED.format(slug=group_slug))

        if documentation_admission is not None and documentation_admission.parent_slug is not None:
            validate_documentation_admission(project_root, documentation_admission)

        state_model = await self._validate_holder_transition(session, parent, group_slug)
        receipt = reconcile_lifecycle_markers(
            project_root,
            group_slug,
            MarkerMoment.SPLIT,
            new_slug=first_child_slug,
        )
        if not receipt.succeeded:
            raise HolderReconciliationRefused(
                f"cannot group under {group_slug!r}: marker reconciliation failed ({receipt.reason})"
            )

        parent.status = TodoStatus.HOLDER.value
        parent.updated_at = datetime.now(UTC).isoformat()
        session.add(parent)
        if state_model is not None:
            await session.delete(state_model)
        return parent.id, receipt

    async def _validate_holder_transition(
        self,
        session: SqlAsyncSession,
        parent: Todo,
        group_slug: str,
    ) -> TodoStateModel | None:
        """Return the target state after confirming it may become a holder."""
        state_model = await session.get(TodoStateModel, parent.id)
        _, lifecycle_phase = readiness_state_fields(state_model)
        phase = coerce_lifecycle_phase(lifecycle_phase)
        if (
            phase is None
            or phase not in LIFECYCLE_PHASE_ORDER
            or lifecycle_phase_index(phase) >= lifecycle_phase_index(LifecyclePhase.PREPARED)
        ):
            raise HolderTransitionRefused(
                f"todo '{group_slug}' cannot become a holder because its lifecycle_phase "
                f"({lifecycle_phase!r}) is missing, invalid, or at/past 'prepared' — a todo cannot "
                "exit the lifecycle mid-build"
            )
        return state_model

    async def _list_todo_models(
        self,
        *,
        include_icebox: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
        include_removed: bool = False,
        removed_only: bool = False,
        include_holders: bool = False,
        session: SqlAsyncSession | None = None,
    ) -> list[Todo]:
        """Fetch todo ORM rows for the requested visibility filters.

        ``include_holders`` adds ``status='holder'`` rows to the result — a
        holder never appears under the other filters, so callers that need to
        resolve a group_id→slug label (or the holder's own artifacts) opt in
        explicitly. Ignored under ``delivered_only``/``removed_only``, which
        already name a single exclusive status.
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            stmt = select(Todo)
            if delivered_only:
                stmt = stmt.where(TODO_TABLE.c.status == "delivered").order_by(TODO_TABLE.c.delivered_at.desc())
            elif removed_only:
                stmt = stmt.where(TODO_TABLE.c.status == "removed").order_by(TODO_TABLE.c.removed_at.desc())
            else:
                allowed = ["active"]
                if include_icebox:
                    allowed.append("icebox")
                if include_delivered:
                    allowed.append("delivered")
                if include_removed:
                    allowed.append("removed")
                if include_holders:
                    allowed.append(TodoStatus.HOLDER.value)
                stmt = stmt.where(TODO_TABLE.c.status.in_(allowed)).order_by(TODO_TABLE.c.id)
            result = await db_session.exec(stmt)
            return list(result.all())
        finally:
            if owns_session:
                await db_session.close()

    async def list_todo(
        self,
        *,
        include_icebox: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
        include_removed: bool = False,
        removed_only: bool = False,
        include_holders: bool = False,
    ) -> list[TodoRow]:
        """List todo entries ordered by stable row id or delivery date."""
        models = await self._list_todo_models(
            include_icebox=include_icebox,
            include_delivered=include_delivered,
            delivered_only=delivered_only,
            include_holders=include_holders,
            include_removed=include_removed,
            removed_only=removed_only,
        )
        return [_todo_row(model) for model in models]

    async def list_entries(self) -> list[Todo]:
        """Return active todo entries as ORM models."""
        return await self._list_todo_models()

    async def add_to_todo(
        self,
        slug: str,
        *,
        lineage: str,
        group_slug: str | None = None,
        after: list[str] | None = None,
        description: str | None = None,
        schedule: str | None = None,
        status: TodoStatus = TodoStatus.ACTIVE,
        entry_point: str | None = None,
        human_involved: bool = False,
        context: str | None = None,
        cwd: str,
        session: SqlAsyncSession | None = None,
        documentation_admission: DocumentationAdmission | None = None,
        reconciliation_receipts: list[MarkerReceipt] | None = None,
    ) -> WorkItemId:
        """Add or update a slug in the todo and return its canonical identity.

        ``status`` sets the new entry's todo status (``TodoStatus.ICEBOX``
        parks it at creation); re-adding an existing slug never re-parks it.
        ``lineage``, ``entry_point``, ``human_involved``, and ``context`` are
        the Creation Record: stamped once on insert, audit-only, and never
        part of the idempotent update value set. ``lineage`` is required —
        the caller resolves it before insert; a create with no resolvable
        lineage never reaches this primitive.

        ``group_slug`` names the parent by slug (the caller-facing handle);
        it is resolved to the parent's durable id and, on first grouping,
        transitions the parent to a holder — see :meth:`_upgrade_to_holder`.
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        split_receipt: MarkerReceipt | None = None
        try:
            group_id: str | None = None
            if group_slug and group_slug != slug:
                project_root = Path(cwd)
                group_id, split_receipt = await self._upgrade_to_holder(
                    db_session,
                    group_slug,
                    first_child_slug=slug,
                    project_root=project_root,
                    documentation_admission=documentation_admission,
                    allow_unreviewed_transfer=status is TodoStatus.ICEBOX,
                )
                if split_receipt is not None and reconciliation_receipts is not None:
                    reconciliation_receipts.append(split_receipt)
                if (
                    split_receipt is not None
                    and documentation_admission is not None
                    and documentation_admission.parent_slug is not None
                    and documentation_admission.parent_id is not None
                    and (documentation_admission.sources or documentation_admission.carrier_path_blobs)
                ):
                    persist_documentation_transfers(
                        cast(DocumentationTransferWriter, self),
                        db_session,
                        documentation_admission,
                        split_receipt,
                        slug,
                        project_root,
                    )

            existing = await self._active_entry(db_session, slug)
            if existing is not None:
                values = collect_entry_updates(existing, group_id=group_id, description=description)
                if values:
                    values["updated_at"] = datetime.now(UTC).isoformat()
                    statement = update(Todo).where(
                        TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)
                    )
                    await db_session.exec(apply_todo_identity_pin(statement.values(**values), self, slug))
                if owns_session:
                    await db_session.commit()
                    self._on_mutation("todo_updated", None)
                return WorkItemId(slug)

            now = datetime.now(UTC).isoformat()
            new_id = _generate_id()
            db_session.add(
                Todo(
                    id=new_id,
                    slug=slug,
                    group_id=group_id,
                    description=description,
                    schedule=schedule,
                    status=status.value,
                    lineage=lineage,
                    entry_point=entry_point,
                    human_involved=human_involved,
                    context=context,
                    created_at=now,
                    updated_at=now,
                )
            )

            for dep in after or []:
                db_session.add(TodoDep(slug=slug, depends_on=dep))

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return WorkItemId(slug)
        except Exception:
            if split_receipt is not None and split_receipt.plan is not None:
                restore_lifecycle_markers(Path(cwd), group_slug or slug, split_receipt.plan)
            raise
        finally:
            if owns_session:
                await db_session.close()

    async def read_lineage(self, slug: str) -> str | None:
        """Return the live entry's persisted Creation Record lineage, or None."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            return entry.lineage if entry is not None else None

    async def get_schedule(self, slug: str) -> str | None:
        """Return the live entry's task schedule, or None."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            return entry.schedule if entry is not None else None

    async def get_created_at(self, slug: str) -> str | None:
        """Return the live entry's creation timestamp, or None."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            return entry.created_at if entry is not None else None

    async def resolve_id(self, slug: str) -> str | None:
        """Resolve an active/icebox slug to its todo id. Returns None if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            return entry.id if entry is not None else None

    def resolve_id_sync(self, slug: str) -> str | None:
        """Sync version of resolve_id. Excludes delivered and removed rows."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            statement = (
                select(Todo.id).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
            )
            entry_id = session.exec(apply_todo_identity_pin(statement, self, slug)).first()
            return str(entry_id) if entry_id is not None else None

    def resolve_store_address_sync(self, slug: str) -> str | None:
        """Resolve adapter row addressing separately from canonical slug identity."""
        return self.resolve_id_sync(slug)

    async def deliver(
        self,
        slug: str,
        *,
        reconciliation_receipt: MarkerReceipt | None,
        reconciliation_root: Path,
        commit: str | None = None,
        children: list[str] | None = None,
        delivered_at: str | None = None,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Mark a slug as delivered and persist delivered coarse item state."""
        _require_delivery_receipt(reconciliation_receipt)
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        db_commit_landed = False
        try:
            entry = await self._active_entry(db_session, slug)
            if entry is None:
                if reconciliation_receipt is not None and reconciliation_receipt.plan is not None:
                    restore_lifecycle_markers(reconciliation_root, slug, reconciliation_receipt.plan)
                return False

            state_model = await db_session.get(TodoStateModel, entry.id)
            _require_delivery_provenance(slug, state_model, commit)

            now = delivered_at or datetime.now(UTC).isoformat()
            entry.status = "delivered"
            entry.delivered_at = now
            entry.delivered_commit = commit
            entry.children = json.dumps(children) if children else None
            entry.ready_since = None
            entry.updated_at = now
            db_session.add(entry)

            if state_model is not None:
                state_model.state = _delivered_state(state_model.state)
                state_model.updated_at = now
                db_session.add(state_model)

            delivered_result = await db_session.exec(select(Todo.slug).where(TODO_TABLE.c.status == "delivered"))
            delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
            delivered_slugs.add(slug)
            dependent_result = await db_session.exec(
                select(TodoDep.slug).where(TODO_DEPS_TABLE.c.depends_on == slug).order_by(TodoDep.slug)
            )
            for dependent_slug in [str(dependent) for dependent in dependent_result.all()]:
                await self._stamp_ready_since_for_slug_if_eligible(
                    db_session,
                    dependent_slug,
                    delivered_slugs=delivered_slugs,
                )

            if owns_session:
                await db_session.commit()
                db_commit_landed = True
                self._on_mutation("todo_updated", None)
                self._on_delivered(slug, commit, now)
            return True
        except DeliveryProvenanceRefused:
            if owns_session:
                await db_session.rollback()
            if reconciliation_receipt is not None and reconciliation_receipt.plan is not None:
                restore_lifecycle_markers(reconciliation_root, slug, reconciliation_receipt.plan)
            raise
        except Exception:
            if (
                owns_session
                and not db_commit_landed
                and reconciliation_receipt is not None
                and reconciliation_receipt.plan is not None
            ):
                await db_session.rollback()
                restore_lifecycle_markers(reconciliation_root, slug, reconciliation_receipt.plan)
            raise
        finally:
            if owns_session:
                await db_session.close()

    async def delivered_slugs(self) -> set[str]:
        """Return set of delivered slugs."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(select(Todo.slug).where(TODO_TABLE.c.status == "delivered"))
            return {str(slug) for slug in result.all()}

    async def _stamp_ready_since_for_slug_if_eligible(
        self,
        session: SqlAsyncSession,
        slug: str,
        *,
        delivered_slugs: set[str],
    ) -> None:
        entry = await self._active_entry(session, slug)
        if entry is None:
            return
        state_model = await session.get(TodoStateModel, entry.id)
        kind, lifecycle_phase = readiness_state_fields(state_model)
        deps_result = await session.exec(select(TodoDep.depends_on).where(TODO_DEPS_TABLE.c.slug == slug))
        after_deps = [str(dep) for dep in deps_result.all()]
        if is_ready_band_eligible(
            kind=kind,
            lifecycle_phase=lifecycle_phase,
            after_deps=after_deps,
            delivered_slugs=delivered_slugs,
        ):
            await self.stamp_ready_since_if_null(slug, session=session)

    def _stamp_ready_since_for_slug_if_eligible_sync(
        self,
        session: SqlSession,
        slug: str,
        *,
        delivered_slugs: set[str],
    ) -> None:
        statement = select(Todo).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
        entry = session.exec(apply_todo_identity_pin(statement, self, slug)).first()
        if entry is None:
            return
        state_model = session.get(TodoStateModel, entry.id)
        kind, lifecycle_phase = readiness_state_fields(state_model)
        deps_result = session.exec(select(TodoDep.depends_on).where(TODO_DEPS_TABLE.c.slug == slug))
        after_deps = [str(dep) for dep in deps_result.all()]
        if is_ready_band_eligible(
            kind=kind,
            lifecycle_phase=lifecycle_phase,
            after_deps=after_deps,
            delivered_slugs=delivered_slugs,
        ):
            self.stamp_ready_since_if_null_sync(slug, session=session)

    async def stamp_ready_since_if_null(
        self,
        slug: str,
        when: str | None = None,
        *,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Stamp the ready-band entry timestamp once."""
        timestamp = when or datetime.now(UTC).isoformat()
        if session is None:
            async with self._session() as owned_session:  # type: ignore[attr-defined]
                changed = await self.stamp_ready_since_if_null(slug, timestamp, session=owned_session)
                await owned_session.commit()
            if changed:
                self._on_mutation("todo_updated", None)
            return changed

        statement = select(Todo).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
        result = await session.exec(apply_todo_identity_pin(statement, self, slug))
        entry = result.first()
        if entry is None or entry.ready_since is not None:
            return False
        entry.ready_since = timestamp
        session.add(entry)
        return True

    def stamp_ready_since_if_null_sync(
        self,
        slug: str,
        when: str | None = None,
        *,
        session: SqlSession | None = None,
    ) -> bool:
        """Sync sibling for stamping the ready-band entry timestamp once."""
        timestamp = when or datetime.now(UTC).isoformat()
        if session is None:
            with self._sync_session() as owned_session:  # type: ignore[attr-defined]
                changed = self.stamp_ready_since_if_null_sync(slug, timestamp, session=owned_session)
                owned_session.commit()
            if changed:
                self._on_mutation("todo_updated", None)
            return changed

        statement = select(Todo).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
        result = session.exec(apply_todo_identity_pin(statement, self, slug))
        entry = result.first()
        if entry is None or entry.ready_since is not None:
            return False
        entry.ready_since = timestamp
        session.add(entry)
        return True

    async def clear_ready_since(
        self,
        slug: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Clear the ready-band entry timestamp."""
        if session is None:
            async with self._session() as owned_session:  # type: ignore[attr-defined]
                await self.clear_ready_since(slug, session=owned_session)
                await owned_session.commit()
            self._on_mutation("todo_updated", None)
            return

        statement = select(Todo).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
        result = await session.exec(apply_todo_identity_pin(statement, self, slug))
        entry = result.first()
        if entry is None:
            return
        entry.ready_since = None
        session.add(entry)

    def clear_ready_since_sync(
        self,
        slug: str,
        *,
        session: SqlSession | None = None,
    ) -> None:
        """Sync sibling for clearing the ready-band entry timestamp."""
        if session is None:
            with self._sync_session() as owned_session:  # type: ignore[attr-defined]
                self.clear_ready_since_sync(slug, session=owned_session)
                owned_session.commit()
            self._on_mutation("todo_updated", None)
            return

        statement = select(Todo).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
        entry = session.exec(apply_todo_identity_pin(statement, self, slug)).first()
        if entry is None:
            return
        entry.ready_since = None
        session.add(entry)

    async def freeze(self, slug: str) -> bool:
        """Move a slug to icebox. Returns False if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            if entry is None:
                return False
            entry.status = "icebox"
            entry.ready_since = None
            entry.updated_at = datetime.now(UTC).isoformat()
            session.add(entry)
            await session.commit()
        self._on_mutation("todo_updated", None)
        return True

    async def set_deps(
        self,
        slug: str,
        *,
        after: list[str],
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Replace dependencies for a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await self._active_entry(db_session, slug)
            if entry is None:
                raise ValueError(f"no active/icebox todo for slug: {slug}")
            await db_session.exec(delete(TodoDep).where(TODO_DEPS_TABLE.c.slug == slug))
            for dep in after:
                db_session.add(TodoDep(slug=slug, depends_on=dep))
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()

    async def set_schedule(
        self,
        slug: str,
        *,
        schedule: str | None,
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Set or clear the task schedule for a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await self._active_entry(db_session, slug)
            if entry is None:
                raise ValueError(f"no active/icebox todo for slug: {slug}")
            entry.schedule = schedule
            entry.updated_at = datetime.now(UTC).isoformat()
            db_session.add(entry)
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()

    async def get_deps(self, slug: str) -> list[str]:
        """Return dependency slugs for one todo entry.

        A dependency target's status is widened to include ``holder``: an
        ``after`` edge naming a holder is a valid, still-blocking dependency
        (see :func:`effective_delivered_slugs_for_dependencies`) and must not
        be silently dropped here.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await self._active_entry(session, slug)
            if entry is None:
                return []
            result = await session.exec(
                select(TodoDep.depends_on)
                .join(Todo, TODO_TABLE.c.slug == TODO_DEPS_TABLE.c.depends_on)
                .where(TodoDep.slug == slug)
                .where(TODO_TABLE.c.status.in_(("active", "icebox", TodoStatus.HOLDER.value)))
                .order_by(TodoDep.depends_on)
            )
            return [str(dep) for dep in result.all()]

    async def get_deps_with_status(self, slug: str) -> list[DependencyEntry]:
        """Return immediate dependency slugs with each direct dep's current todo status."""
        child_todo = TODO_TABLE.alias("child_todo")
        dep_todo = TODO_TABLE.alias("dep_todo")
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(TODO_DEPS_TABLE.c.depends_on, dep_todo.c.status)
                .join(child_todo, child_todo.c.slug == TODO_DEPS_TABLE.c.slug)
                .join(dep_todo, dep_todo.c.slug == TODO_DEPS_TABLE.c.depends_on)
                .where(TODO_DEPS_TABLE.c.slug == slug)
                .where(child_todo.c.status.in_(("active", "icebox")))
                .where(dep_todo.c.status.in_(("active", "icebox", "delivered", TodoStatus.HOLDER.value)))
                .order_by(TODO_DEPS_TABLE.c.depends_on, dep_todo.c.status)
            )
            status_by_slug: dict[str, str] = {}
            for dep_slug, todo_status in result.all():
                if not isinstance(dep_slug, str) or not isinstance(todo_status, str):
                    continue
                current = status_by_slug.get(dep_slug)
                if current is None or (current == "delivered" and todo_status != "delivered"):
                    status_by_slug[dep_slug] = todo_status
            return [
                DependencyEntry(dep_slug=dep_slug, todo_status=TodoStatus(todo_status))
                for dep_slug, todo_status in sorted(status_by_slug.items())
            ]

    async def get_open_dependents(self, slug: str) -> list[str]:
        """Return active todos directly blocked by the named dependency."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(TodoDep.slug)
                .join(Todo, TODO_TABLE.c.slug == TODO_DEPS_TABLE.c.slug)
                .where(TODO_DEPS_TABLE.c.depends_on == slug)
                .where(TODO_TABLE.c.status == _ACTIVE_TODO_STATUS)
                .order_by(TODO_DEPS_TABLE.c.slug)
            )
            return [str(dependent_slug) for dependent_slug in result.all()]

    async def load_deps(self) -> dict[str, list[str]]:
        """Return dependency graph: {slug: [depends_on, ...]}."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(TodoDep)
                .join(Todo, TODO_TABLE.c.slug == TODO_DEPS_TABLE.c.slug)
                .where(TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX))
                .order_by(TodoDep.slug, TodoDep.depends_on)
            )
            deps: dict[str, list[str]] = {}
            for dep in result.all():
                deps.setdefault(dep.slug, []).append(dep.depends_on)
            if not deps:
                return deps

            live_dependency_rows = await session.exec(
                select(Todo.slug)
                .where(TODO_TABLE.c.status.in_(("active", "icebox", TodoStatus.HOLDER.value)))
                .where(TODO_TABLE.c.slug.in_({dep for deps_for_slug in deps.values() for dep in deps_for_slug}))
            )
            live_dependency_slugs = {str(slug) for slug in live_dependency_rows.all()}
            for slug in list(deps):
                filtered = [dep for dep in deps[slug] if dep in live_dependency_slugs]
                if filtered:
                    deps[slug] = filtered
                else:
                    deps.pop(slug)
            return deps

    async def clean_dep_references(self, slug: str, *, session: SqlAsyncSession | None = None) -> None:
        """Remove a slug from all dependency lists."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            await db_session.exec(delete(TodoDep).where(TODO_DEPS_TABLE.c.depends_on == slug))
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()

    async def rename_todo_slug(
        self,
        old_slug: str,
        new_slug: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Re-key the live todo row and structured todo slug references."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await self._active_entry(db_session, old_slug)
            if entry is None:
                return False

            now = datetime.now(UTC).isoformat()
            entry.slug = new_slug
            entry.updated_at = now
            db_session.add(entry)

            child_rows = await db_session.exec(
                select(Todo)
                .where(TODO_TABLE.c.children.is_not(None))
                .where(TODO_TABLE.c.status.notin_(("delivered", "removed")))
            )
            for row in child_rows.all():
                children = json.loads(row.children) if row.children else None
                if not isinstance(children, list) or old_slug not in children:
                    continue
                row.children = json.dumps([new_slug if child == old_slug else child for child in children])
                row.updated_at = now
                db_session.add(row)

            await db_session.exec(update(TodoDep).where(TODO_DEPS_TABLE.c.slug == old_slug).values(slug=new_slug))
            await db_session.exec(
                update(TodoDep).where(TODO_DEPS_TABLE.c.depends_on == old_slug).values(depends_on=new_slug)
            )

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return True
        finally:
            if owns_session:
                await db_session.close()

    def delivered_slugs_sync(self) -> set[str]:
        """Sync version of delivered_slugs for use from worker threads."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            result = session.exec(select(Todo.slug).where(TODO_TABLE.c.status == "delivered"))
            return {str(slug) for slug in result.all()}

    def deliver_sync(
        self,
        slug: str,
        *,
        reconciliation_receipt: MarkerReceipt | None,
        reconciliation_root: Path,
        commit: str | None = None,
        children: list[str] | None = None,
    ) -> bool:
        """Sync version of deliver for use from worker threads."""
        _require_delivery_receipt(reconciliation_receipt)
        db_commit_landed = False
        try:
            with self._sync_session() as session:  # type: ignore[attr-defined]
                statement = (
                    select(Todo).where(TODO_TABLE.c.slug == slug, TODO_TABLE.c.status.in_(_ACTIVE_OR_ICEBOX)).limit(1)
                )
                entry = session.exec(apply_todo_identity_pin(statement, self, slug)).first()
                if entry is None:
                    if reconciliation_receipt is not None and reconciliation_receipt.plan is not None:
                        restore_lifecycle_markers(reconciliation_root, slug, reconciliation_receipt.plan)
                    return False

                state_model = session.get(TodoStateModel, entry.id)
                _require_delivery_provenance(slug, state_model, commit)

                now = datetime.now(UTC).isoformat()
                entry.status = "delivered"
                entry.delivered_at = now
                entry.delivered_commit = commit
                entry.children = json.dumps(children) if children else None
                entry.ready_since = None
                entry.updated_at = now
                session.add(entry)

                if state_model is not None:
                    state_model.state = _delivered_state(state_model.state)
                    state_model.updated_at = now
                    session.add(state_model)

                delivered_result = session.exec(select(Todo.slug).where(TODO_TABLE.c.status == "delivered"))
                delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
                delivered_slugs.add(slug)
                dependent_result = session.exec(
                    select(TodoDep.slug).where(TODO_DEPS_TABLE.c.depends_on == slug).order_by(TodoDep.slug)
                )
                for dependent_slug in [str(dependent) for dependent in dependent_result.all()]:
                    self._stamp_ready_since_for_slug_if_eligible_sync(
                        session,
                        dependent_slug,
                        delivered_slugs=delivered_slugs,
                    )

                session.commit()
                db_commit_landed = True

        except DeliveryProvenanceRefused:
            if reconciliation_receipt is not None and reconciliation_receipt.plan is not None:
                restore_lifecycle_markers(reconciliation_root, slug, reconciliation_receipt.plan)
            raise
        except Exception:
            if not db_commit_landed and reconciliation_receipt is not None and reconciliation_receipt.plan is not None:
                restore_lifecycle_markers(reconciliation_root, slug, reconciliation_receipt.plan)
            raise

        self._on_mutation("todo_updated", None)
        self._on_delivered(slug, commit, now)
        return True
