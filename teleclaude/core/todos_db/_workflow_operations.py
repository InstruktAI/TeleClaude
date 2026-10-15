"""Compound local adapter operations that retain existing transaction boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import ARTIFACT_INPUT, ARTIFACT_LOG, TodoStatus
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.todos_db._models import Todo
from teleclaude.core.workflow_store.types import ArtifactRevisionMismatch, ItemChange, TodoDiagnosticRecord
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY, LIFECYCLE_PHASE_STATE_KEY

_TODO_UPDATED_EVENT = "todo_updated"
_BEGIN_IMMEDIATE_SQL = "BEGIN IMMEDIATE"
_STATE_RENAME_FAILURE = "state rename failed for {slug!r}"
_ARTIFACT_RENAME_FAILURE = "artifact rename failed for {slug!r}"
_TODO_RENAME_FAILURE = "todo rename failed for {slug!r}"


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

    async def read_artifact_in_session(self, slug: str, name: str, session: SqlAsyncSession) -> str: ...

    async def artifact_digest_in_session(self, slug: str, name: str, session: SqlAsyncSession) -> str: ...

    def on_committed(self, event_hint: str, event_data: Mapping[str, object] | None = None) -> None: ...

    _on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None]
    _on_claim_changed: Callable[[str, str | None, str | None], None]


class _RenameItemHost(Protocol):
    def _session(self) -> AbstractAsyncContextManager[SqlAsyncSession]: ...

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


class TodosDbWorkflowOperationsMixin:
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
        state: dict[str, StateValue],
        *,
        replacement_input: str | None,
        deleted_artifacts: list[str],
    ) -> None:
        """Commit a kind migration's state and artifact changes together."""
        async with self._session() as session:
            async with session.begin():
                if replacement_input is not None:
                    await self.write_artifact(slug, ARTIFACT_INPUT, replacement_input, updated_by=None, session=session)
                for artifact_name in deleted_artifacts:
                    await self.delete_artifact(slug, artifact_name, session=session)
                await self.write_state(slug, state, session=session)

    async def rename_item(self: _RenameItemHost, old_slug: str, new_slug: str) -> None:
        """Rename persisted workflow rows in their existing shared transaction."""
        async with self._session() as session:
            async with session.begin():
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
        mutate: Callable[[dict[str, StateValue] | None, Mapping[str, str]], ItemChange],
        updated_by: str | None,
    ) -> ItemChange:
        """Apply one change to an item under the writer lock, or write nothing.

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
                await self.write_state(slug, change.state, session=session, owns_workflow_record=True)
                if change.log_entry:
                    existing = await self.read_artifact_in_session(slug, ARTIFACT_LOG, session)
                    await self.write_artifact(
                        slug, ARTIFACT_LOG, existing + change.log_entry, updated_by=updated_by, session=session
                    )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        self.on_committed(_TODO_UPDATED_EVENT)
        prior_state = prior or {}
        prior_phase = prior_state.get(LIFECYCLE_PHASE_STATE_KEY)
        new_phase = change.state.get(LIFECYCLE_PHASE_STATE_KEY)
        if isinstance(new_phase, str) and new_phase != prior_phase:
            self._on_phase_transition(
                slug, prior_phase if isinstance(prior_phase, str) else "", new_phase, change.state
            )
        prior_holder = prior_state.get(ACTIVE_RUNNER_STATE_KEY)
        holder = change.state.get(ACTIVE_RUNNER_STATE_KEY)
        prior_holder = prior_holder if isinstance(prior_holder, str) and prior_holder else None
        holder = holder if isinstance(holder, str) and holder else None
        if prior_holder != holder:
            self._on_claim_changed(slug, prior_holder, holder)
        return change

    async def update_state_with_artifact_evidence(
        self: _CreateItemHost,
        slug: str,
        artifact_names: list[str],
        update: Callable[[dict[str, StateValue] | None, dict[str, str]], dict[str, StateValue]],
    ) -> dict[str, StateValue]:
        """Read evidence and persist its derived state inside one transaction."""
        async with self._session() as session:
            raw_state = await self.read_state_in_session(slug, session)
            digests = {name: await self.artifact_digest_in_session(slug, name, session) for name in artifact_names}
            payload = update(raw_state, digests)
            await self.write_state(slug, payload, session=session)
            await session.commit()
        self.on_committed(_TODO_UPDATED_EVENT)
        return payload
