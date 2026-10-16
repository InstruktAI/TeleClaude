"""Compound local adapter operations that retain existing transaction boundaries."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import ARTIFACT_INPUT, ARTIFACT_LOG, TodoStatus
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.todos_db._converted_rows import insert_converted_row, is_converted_row
from teleclaude.core.todos_db._models import TODO_STATE_TABLE, TODO_TABLE, Todo, TodoStateModel
from teleclaude.core.workflow_store.types import (
    ArtifactRevisionMismatch,
    ItemChange,
    PendingEffectItem,
    TodoDiagnosticRecord,
)
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, stored_holder, with_claim_change, workflow_record_of
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY, LIFECYCLE_PHASE_STATE_KEY

_TODO_UPDATED_EVENT = "todo_updated"
_BEGIN_IMMEDIATE_SQL = "BEGIN IMMEDIATE"
_PENDING_EFFECTS_MARKER = '%"pending_effects": [{%'  # the serialized form of a non-empty pending-effect list
_STATE_RENAME_FAILURE = "state rename failed for {slug!r}"
_ARTIFACT_RENAME_FAILURE = "artifact rename failed for {slug!r}"
_TODO_RENAME_FAILURE = "todo rename failed for {slug!r}"


StatePrecondition = Callable[[dict[str, StateValue] | None], None]


class _SessionHost(Protocol):
    def _session(self) -> AbstractAsyncContextManager[SqlAsyncSession]: ...

    async def read_state_in_session(self, slug: str, session: SqlAsyncSession) -> dict[str, StateValue] | None: ...


@asynccontextmanager
async def immediate_transaction(host: _SessionHost) -> AsyncIterator[SqlAsyncSession]:
    """One write transaction taken under the writer lock up front, committed on success and rolled back otherwise."""
    async with host._session() as session:
        connection = await session.connection()
        await connection.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def _check_precondition(
    host: _SessionHost, slug: str, session: SqlAsyncSession, precondition: StatePrecondition | None
) -> None:
    """Judge the state as read now, inside the transaction; the precondition raises to refuse."""
    if precondition is not None:
        precondition(await host.read_state_in_session(slug, session))


async def _record_conversion(host: _CreateItemHost, slug: str, change: ItemChange, session: SqlAsyncSession) -> None:
    """Insert the converted-row record of a change that converted the row, in the change's own transaction."""
    if not change.converted_from:
        return
    row_id = await host._resolve_active_row_id(session, slug)
    if row_id is not None:
        await insert_converted_row(session, row_id, change.converted_from, change.conversion_path)


def _after_item_commit(
    host: _CreateItemHost, slug: str, prior: dict[str, StateValue] | None, change: ItemChange | None
) -> None:
    """The observers a committed item change owes: the update notice, a phase move and a claim change."""
    host.on_committed(_TODO_UPDATED_EVENT)
    if change is None:
        return
    prior_state = prior or {}
    prior_phase = prior_state.get(LIFECYCLE_PHASE_STATE_KEY)
    new_phase = change.state.get(LIFECYCLE_PHASE_STATE_KEY)
    if isinstance(new_phase, str) and new_phase != prior_phase:
        host._on_phase_transition(slug, prior_phase if isinstance(prior_phase, str) else "", new_phase, change.state)
    prior_holder = prior_state.get(ACTIVE_RUNNER_STATE_KEY)
    holder = change.state.get(ACTIVE_RUNNER_STATE_KEY)
    prior_holder = prior_holder if isinstance(prior_holder, str) and prior_holder else None
    holder = holder if isinstance(holder, str) and holder else None
    if prior_holder != holder:
        host._on_claim_changed(slug, prior_holder, holder)


class _CreateItemHost(Protocol):
    def _session(self) -> AbstractAsyncContextManager[SqlAsyncSession]: ...

    async def add_to_todo(
        self,
        slug: str,
        *,
        lineage: str,
        group_slug: str | None,
        after: list[str] | None,
        description: str | None,
        schedule: str | None,
        status: TodoStatus,
        entry_point: str | None,
        human_involved: bool,
        context: str | None,
        cwd: str,
        session: SqlAsyncSession,
    ) -> bool: ...

    async def write_state(
        self,
        slug: str,
        state: dict[str, StateValue],
        *,
        session: SqlAsyncSession,
        owns_workflow_record: bool = False,
    ) -> None: ...

    async def write_artifact(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None,
        session: SqlAsyncSession,
    ) -> None: ...

    async def delete_artifact(self, slug: str, name: str, *, session: SqlAsyncSession) -> object: ...

    async def read_state_in_session(self, slug: str, session: SqlAsyncSession) -> dict[str, StateValue] | None: ...

    async def _resolve_active_row_id(self, session: SqlAsyncSession, slug: str) -> str | None: ...

    async def read_artifact_in_session(self, slug: str, name: str, session: SqlAsyncSession) -> str: ...

    async def artifact_digest_in_session(self, slug: str, name: str, session: SqlAsyncSession) -> str: ...

    def on_committed(self, event_hint: str, event_data: Mapping[str, object] | None = None) -> None: ...

    _on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None]
    _on_claim_changed: Callable[[str, str | None, str | None], None]


class _RenameItemHost(Protocol):
    def _session(self) -> AbstractAsyncContextManager[SqlAsyncSession]: ...

    async def read_state_in_session(self, slug: str, session: SqlAsyncSession) -> dict[str, StateValue] | None: ...

    async def rename_state_slug(self, old_slug: str, new_slug: str, *, session: SqlAsyncSession) -> bool: ...

    async def rename_artifacts_slug(self, old_slug: str, new_slug: str, *, session: SqlAsyncSession) -> bool: ...

    async def rename_todo_slug(self, old_slug: str, new_slug: str, *, session: SqlAsyncSession) -> bool: ...


class _DiagnosticRecordHost(Protocol):
    async def _list_todo_models(
        self,
        *,
        include_icebox: bool = False,
        include_delivered: bool = False,
        include_holders: bool = False,
    ) -> list[Todo]: ...


class _EffectHost(Protocol):
    _on_claim_changed: Callable[[str, str | None, str | None], None]

    def _session(self) -> AbstractAsyncContextManager[SqlAsyncSession]: ...


class TodosDbWorkflowOperationsMixin:
    async def list_items_with_pending_effects(self: _EffectHost) -> list[PendingEffectItem]:
        """Every item row, whatever its status, whose state holds effects the machine has not finished."""
        async with self._session() as session:
            rows = await session.exec(
                select(TODO_STATE_TABLE.c.id, TODO_STATE_TABLE.c.slug, TODO_TABLE.c.status)
                .join(TODO_TABLE, TODO_STATE_TABLE.c.id == TODO_TABLE.c.id)
                .where(TODO_STATE_TABLE.c.state.like(_PENDING_EFFECTS_MARKER))
            )
            return [PendingEffectItem(todo_id=row[0], slug=row[1], status=str(row[2])) for row in rows.all()]

    async def release_claim_by_id(self: _EffectHost, todo_id: str, session_id: str) -> bool:
        """Release the claim an item row holds for the session, under the writer lock; False when it holds another.

        The claim change commits with the state as its pending effect, like every other holder change.
        """
        async with self._session() as session:
            connection = await session.connection()
            await connection.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)
            try:
                state_model = await session.get(TodoStateModel, todo_id)
                entry = await session.get(Todo, todo_id)
                if state_model is None or entry is None:
                    await session.rollback()
                    return False
                payload = json.loads(state_model.state)
                prior = stored_holder(payload)
                if prior != session_id:
                    await session.rollback()
                    return False
                payload[ACTIVE_RUNNER_STATE_KEY] = None
                payload = with_claim_change(payload, prior)
                state_model.state = json.dumps(payload, default=str)
                state_model.updated_at = datetime.now(UTC).isoformat()
                session.add(state_model)
                await session.commit()
                slug = entry.slug
            except BaseException:
                await session.rollback()
                raise
        self._on_claim_changed(slug, prior, None)
        return True

    async def clear_pending_effect(self: _EffectHost, todo_id: str, effect_id: str) -> None:
        """Remove one finished effect from an item row addressed by its durable id, under the writer lock."""
        async with self._session() as session:
            connection = await session.connection()
            await connection.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)
            try:
                state_model = await session.get(TodoStateModel, todo_id)
                if state_model is None:
                    await session.rollback()
                    return
                payload = json.loads(state_model.state)
                record = workflow_record_of(payload)
                updated = record.without_effect(effect_id)
                if updated == record:
                    await session.rollback()
                    return
                payload[WORKFLOW_STATE_KEY] = updated.to_state()
                state_model.state = json.dumps(payload, default=str)
                state_model.updated_at = datetime.now(UTC).isoformat()
                session.add(state_model)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def read_todo_diagnostic_record(
        self: _DiagnosticRecordHost,
        slug: str,
    ) -> TodoDiagnosticRecord | None:
        """Read the complete persisted row with the diagnostic surface's wire shape."""
        rows = await self._list_todo_models(include_icebox=True, include_delivered=True, include_holders=True)
        for row in rows:
            if row.slug == slug:
                return TodoDiagnosticRecord(
                    id=row.id,
                    slug=row.slug,
                    ready_since=row.ready_since,
                    schedule=row.schedule,
                    group_id=row.group_id,
                    description=row.description,
                    status=row.status,
                    delivered_at=row.delivered_at,
                    delivered_commit=row.delivered_commit,
                    children=row.children,
                    lineage=row.lineage,
                    entry_point=row.entry_point,
                    human_involved=row.human_involved,
                    context=row.context,
                    removed_at=row.removed_at,
                    prev_status=row.prev_status,
                    removed_deps=row.removed_deps,
                    removed_claim=row.removed_claim,
                    removed_doc_reconciliation=row.removed_doc_reconciliation,
                    pending_purge_paths=row.pending_purge_paths,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
        return None

    async def create_item_with_initial_artifact(
        self: _CreateItemHost,
        slug: str,
        state: dict[str, StateValue],
        *,
        lineage: str,
        group_slug: str | None,
        after: list[str] | None,
        description: str | None,
        schedule: str | None,
        status: TodoStatus,
        entry_point: str | None,
        human_involved: bool,
        context: str | None,
        cwd: str,
        artifact_name: str,
        artifact_body: str,
        updated_by: str | None,
    ) -> bool:
        """Atomically create the item, initial state and first artifact version."""
        async with self._session() as session:
            async with session.begin():
                created = await self.add_to_todo(
                    slug,
                    lineage=lineage,
                    group_slug=group_slug,
                    after=after,
                    description=description,
                    schedule=schedule,
                    status=status,
                    entry_point=entry_point,
                    human_involved=human_involved,
                    context=context,
                    cwd=cwd,
                    session=session,
                )
                await self.write_state(slug, state, session=session)
                await self.write_artifact(
                    slug,
                    artifact_name,
                    artifact_body,
                    updated_by=updated_by,
                    session=session,
                )
        self.on_committed(_TODO_UPDATED_EVENT)
        return created

    async def replace_item_state_and_artifacts(
        self: _CreateItemHost,
        slug: str,
        *,
        decide: Callable[[dict[str, StateValue] | None, bool], dict[str, StateValue]],
        replacement_input: str | None,
        deleted_artifacts: list[str],
    ) -> None:
        """Commit a kind migration's state and artifact changes together.

        ``decide`` derives the new state from the row read under the writer lock, so a claim or a hold that landed
        meanwhile is carried and not overwritten, and learns whether the row was converted; it may raise to write
        nothing.
        """
        async with immediate_transaction(self) as session:
            row_id = await self._resolve_active_row_id(session, slug)
            converted = row_id is not None and await is_converted_row(session, row_id)
            state = decide(await self.read_state_in_session(slug, session), converted)
            if replacement_input is not None:
                await self.write_artifact(slug, ARTIFACT_INPUT, replacement_input, updated_by=None, session=session)
            for artifact_name in deleted_artifacts:
                await self.delete_artifact(slug, artifact_name, session=session)
            await self.write_state(slug, state, session=session)

    async def rename_item(
        self: _RenameItemHost, old_slug: str, new_slug: str, precondition: StatePrecondition | None = None
    ) -> None:
        """Rename persisted workflow rows in their existing shared transaction.

        ``precondition`` judges the state read under the writer lock and may raise to write nothing.
        """
        async with immediate_transaction(self) as session:
            await _check_precondition(self, old_slug, session, precondition)
            if not await self.rename_state_slug(old_slug, new_slug, session=session):
                raise RuntimeError(_STATE_RENAME_FAILURE.format(slug=old_slug))
            if not await self.rename_artifacts_slug(old_slug, new_slug, session=session):
                raise RuntimeError(_ARTIFACT_RENAME_FAILURE.format(slug=old_slug))
            if not await self.rename_todo_slug(old_slug, new_slug, session=session):
                raise RuntimeError(_TODO_RENAME_FAILURE.format(slug=old_slug))

    async def commit_item_change(
        self: _CreateItemHost,
        slug: str,
        *,
        expect_digests: Mapping[str, str],
        mutate: Callable[[dict[str, StateValue] | None, Mapping[str, str]], ItemChange | None],
        updated_by: str | None,
    ) -> ItemChange | None:
        """Apply one change to an item under the writer lock, or write nothing.

        A mutation that returns None decided there is nothing to write.

        The artifact revisions, the state read, the mutation, the state write and the log append
        share one write transaction. A revision that differs from the expected one raises before any
        write, naming both. The phase and claim observers fire after the commit.
        """
        async with self._session() as session:
            connection = await session.connection()
            await connection.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)
            try:
                prior = await self.read_state_in_session(slug, session)
                digests = {name: await self.artifact_digest_in_session(slug, name, session) for name in expect_digests}
                for name, expected in expect_digests.items():
                    if digests[name] != expected:
                        raise ArtifactRevisionMismatch(name, expected, digests[name])
                change = mutate(prior, digests)
                if change is None:
                    await session.rollback()
                    return None
                await self.write_state(slug, change.state, session=session, owns_workflow_record=True)
                await _record_conversion(self, slug, change, session)
                if change.log_entry:
                    existing = await self.read_artifact_in_session(slug, ARTIFACT_LOG, session)
                    await self.write_artifact(
                        slug, ARTIFACT_LOG, existing + change.log_entry, updated_by=updated_by, session=session
                    )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        _after_item_commit(self, slug, prior, change)
        return change

    async def write_artifact_with_state_change(
        self: _CreateItemHost,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None,
        mutate: Callable[[dict[str, StateValue] | None], ItemChange | None],
    ) -> ItemChange | None:
        """Write an artifact and the state change decided on the row read under the writer lock, in one transaction.

        ``mutate`` may raise to write nothing; None writes the artifact alone.
        """
        async with immediate_transaction(self) as session:
            prior = await self.read_state_in_session(slug, session)
            change = mutate(prior)
            await self.write_artifact(slug, name, content, updated_by=updated_by, session=session)
            if change is not None:
                await self.write_state(slug, change.state, session=session, owns_workflow_record=True)
                await _record_conversion(self, slug, change, session)
        _after_item_commit(self, slug, prior, change)
        return change

    async def update_state_with_artifact_evidence(
        self: _CreateItemHost,
        slug: str,
        artifact_names: list[str],
        update: Callable[[dict[str, StateValue] | None, dict[str, str]], dict[str, StateValue]],
    ) -> dict[str, StateValue]:
        """Read evidence and persist its derived state inside one write transaction taken up front.

        The writer lock is held from the read, so no other writer commits between the state this reads and the state
        it writes; the evidence and the state it is derived from are one reading.
        """
        async with immediate_transaction(self) as session:
            raw_state = await self.read_state_in_session(slug, session)
            digests = {name: await self.artifact_digest_in_session(slug, name, session) for name in artifact_names}
            payload = update(raw_state, digests)
            await self.write_state(slug, payload, session=session)
        self.on_committed(_TODO_UPDATED_EVENT)
        return payload
