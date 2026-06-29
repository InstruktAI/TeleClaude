"""Todo state persistence mixin."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger
from sqlalchemy import update
from sqlmodel import Session as SqlSession
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import ARTIFACT_DEFERRALS, WORKTREE_DIR
from teleclaude.core.next_machine.kinds import FAST_TRACK_PREPARED_KINDS, KIND_BUG
from teleclaude.core.next_machine.lifecycle import READY_BAND_PHASES, coerce_lifecycle_phase, is_ready_band_eligible
from teleclaude.types.state_value import StateValue

from ._errors import HolderWriteRefused
from ._migration_logs import record_v2_to_v3_migration
from ._models import TODO_DEPS_TABLE, TODO_STATE_TABLE, TODO_TABLE, Todo, TodoDep, TodoStateModel
from ._upcycle import _detect_schema_version, canonicalize_state_for_storage, upcycle_state_dict

logger = get_logger(__name__)

_V2_PREPARE_PHASES = {
    "draft",
    "input_assessment",
    "triangulation",
    "requirements_review",
    "requirements_human_approval",
    "test_spec_build",
    "test_spec_review",
    "plan_drafting",
    "plan_review",
    "gate",
    "grounding_check",
    "re_grounding",
    "prepared",
}


def _rename_breakdown_todos(
    state: dict[str, StateValue],
    old_slug: str,
    new_slug: str,
) -> dict[str, StateValue]:
    """Re-key typed BreakdownState.todos refs without touching prose fields."""
    breakdown = state.get("breakdown")
    if not isinstance(breakdown, dict):
        return state

    todos = breakdown.get("todos")
    if not isinstance(todos, list):
        return state

    renamed_todos = [new_slug if todo == old_slug else todo for todo in todos]
    renamed_breakdown = dict(breakdown)
    renamed_breakdown["todos"] = renamed_todos
    renamed_state = dict(state)
    renamed_state["breakdown"] = renamed_breakdown
    return renamed_state


class TodosDbStateMixin:
    """Read/write todo lifecycle state (replaces state_io.py)."""

    _on_mutation: Callable[[str, Mapping[str, object] | None], None]
    _on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None]

    def _stored_lifecycle_phase(self, state_model: TodoStateModel | None) -> str:
        if state_model is None:
            return ""
        raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
        payload = upcycle_state_dict(raw_state)
        phase = payload.get("lifecycle_phase")
        return phase if isinstance(phase, str) else ""

    def _payload_lifecycle_phase(self, payload: Mapping[str, StateValue]) -> str:
        phase = payload.get("lifecycle_phase")
        return phase if isinstance(phase, str) else ""

    def _payload_kind(self, payload: Mapping[str, StateValue]) -> str | None:
        kind = payload.get("kind")
        return kind if isinstance(kind, str) else None

    def _payload_is_ready_candidate(self, payload: Mapping[str, StateValue]) -> bool:
        kind = self._payload_kind(payload)
        phase = coerce_lifecycle_phase(payload.get("lifecycle_phase"))
        return kind in FAST_TRACK_PREPARED_KINDS or phase in READY_BAND_PHASES

    def _project_root(self) -> Path:
        db_path = cast(Path, self._db_path)  # type: ignore[attr-defined]
        return db_path.parent.parent if db_path.parent.name == ".teleclaude" else db_path.parent

    def _record_v2_to_v3_if_needed(
        self,
        slug: str,
        raw_state: dict[str, StateValue],
        payload: dict[str, StateValue],
    ) -> bool:
        if _detect_schema_version(raw_state) != 2:
            return False
        from_phase = raw_state.get("lifecycle_phase")
        if not isinstance(from_phase, str) or from_phase not in _V2_PREPARE_PHASES:
            return False

        project_root = self._project_root()
        worktree_abandoned = (project_root / WORKTREE_DIR / slug).exists()
        to_phase = payload.get("lifecycle_phase")
        kind = payload.get("kind")
        record_v2_to_v3_migration(
            slug,
            from_lifecycle_phase=from_phase,
            to_lifecycle_phase=to_phase if isinstance(to_phase, str) else "",
            kind=kind if isinstance(kind, str) else "",
            worktree_abandoned=worktree_abandoned,
            project_root=str(project_root),
        )
        return True

    async def _resolve_active_row_id(self, session: SqlAsyncSession, slug: str) -> str | None:
        """Resolve a live (active or icebox) todo slug to its stable row id.

        Excludes delivered and removed rows so state reads/writes never resolve
        a soft-removed todo.
        """
        result = await session.exec(
            select(Todo.id)
            .where(TODO_TABLE.c.slug == slug)
            .where(TODO_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        )
        row_id = result.one_or_none()
        return str(row_id) if row_id is not None else None

    async def _is_state_holder_slug(self, session: SqlAsyncSession, slug: str) -> bool:
        """Return whether any live child group-references ``slug``."""
        result = await session.exec(
            select(Todo.id)
            .where(TODO_TABLE.c.group_slug == slug)
            .where(TODO_TABLE.c.slug != slug)
            .where(TODO_TABLE.c.status != "removed")
            .limit(1)
        )
        return result.first() is not None

    async def is_holder(self, slug: str) -> bool:
        """Whether ``slug`` is a structural holder (has grouped children).

        Holders carry no todo_state or artifacts — their children own those.
        Public predicate so callers (e.g. the API) can refuse holder writes with
        a clean 409 before attempting one.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            return await self._is_state_holder_slug(session, slug)

    async def _stamp_ready_since_for_payload(
        self,
        session: SqlAsyncSession,
        *,
        slug: str,
        row_id: str,
        payload: Mapping[str, StateValue],
        when: str,
    ) -> None:
        if not self._payload_is_ready_candidate(payload):
            return
        deps_result = await session.exec(select(TodoDep.depends_on).where(TODO_DEPS_TABLE.c.slug == slug))
        delivered_result = await session.exec(select(Todo.slug).where(TODO_TABLE.c.status == "delivered"))
        after_deps = [str(dep) for dep in deps_result.all()]
        delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
        if not is_ready_band_eligible(
            kind=self._payload_kind(payload),
            lifecycle_phase=self._payload_lifecycle_phase(payload),
            after_deps=after_deps,
            delivered_slugs=delivered_slugs,
        ):
            return
        await session.exec(
            update(Todo)
            .where(TODO_TABLE.c.id == row_id)
            .where(TODO_TABLE.c.ready_since.is_(None))
            .values(ready_since=when)
        )

    def _stamp_ready_since_for_payload_sync(
        self,
        session: SqlSession,
        *,
        slug: str,
        row_id: str,
        payload: Mapping[str, StateValue],
        when: str,
    ) -> None:
        if not self._payload_is_ready_candidate(payload):
            return
        deps_result = session.exec(select(TodoDep.depends_on).where(TODO_DEPS_TABLE.c.slug == slug))
        delivered_result = session.exec(select(Todo.slug).where(TODO_TABLE.c.status == "delivered"))
        after_deps = [str(dep) for dep in deps_result.all()]
        delivered_slugs = {str(delivered_slug) for delivered_slug in delivered_result.all()}
        if not is_ready_band_eligible(
            kind=self._payload_kind(payload),
            lifecycle_phase=self._payload_lifecycle_phase(payload),
            after_deps=after_deps,
            delivered_slugs=delivered_slugs,
        ):
            return
        session.exec(
            update(Todo)
            .where(TODO_TABLE.c.id == row_id)
            .where(TODO_TABLE.c.ready_since.is_(None))
            .values(ready_since=when)
        )

    def _is_state_holder_slug_sync(self, slug: str) -> bool:
        """Sync counterpart of :meth:`_is_state_holder_slug`."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            result = session.exec(
                select(Todo.id)
                .where(TODO_TABLE.c.group_slug == slug)
                .where(TODO_TABLE.c.slug != slug)
                .where(TODO_TABLE.c.status != "removed")
                .limit(1)
            )
            return result.first() is not None

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        """Read state JSON for a slug (active/icebox). Returns None if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            if await self._is_state_holder_slug(session, slug):
                return None
            row_id = await self._resolve_active_row_id(session, slug)
            if row_id is None:
                return None
            state_model = await session.get(TodoStateModel, row_id)
            if state_model is None:
                return None
            raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
            payload = upcycle_state_dict(raw_state)
            if self._record_v2_to_v3_if_needed(slug, raw_state, payload):
                state_model.state = json.dumps(payload, default=str)
                state_model.updated_at = datetime.now(UTC).isoformat()
                session.add(state_model)
                await session.commit()
                self._on_mutation("todo_updated", None)
            return payload

    async def read_state_by_id(self, todo_id: str) -> dict[str, StateValue] | None:
        """Read state JSON for a specific todo row id, including terminal rows."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await session.get(Todo, todo_id)
            if entry is None:
                return None
            state_model = await session.get(TodoStateModel, todo_id)
            if state_model is None:
                return None
            raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
            payload = upcycle_state_dict(raw_state)
            if self._record_v2_to_v3_if_needed(entry.slug, raw_state, payload):
                state_model.state = json.dumps(payload, default=str)
                state_model.updated_at = datetime.now(UTC).isoformat()
                session.add(state_model)
                await session.commit()
                self._on_mutation("todo_updated", None)
            return payload

    async def get_state(self, slug: str) -> dict[str, StateValue] | None:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.read_state(slug)

    async def write_state_by_id(
        self,
        todo_id: str,
        state: dict[str, StateValue],
        *,
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Write the typed state payload for a specific todo row id."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            entry = await db_session.get(Todo, todo_id)
            if entry is None:
                raise ValueError(f"Todo row {todo_id} not found")

            # Upcycle and canonicalize before storage
            canonical = canonicalize_state_for_storage(state)
            now = datetime.now(UTC).isoformat()

            # Upsert state model
            state_model = await db_session.get(TodoStateModel, todo_id)
            if state_model is None:
                state_model = TodoStateModel(
                    id=todo_id,
                    slug=entry.slug,
                    state=json.dumps(canonical),
                    created_at=now,
                    updated_at=now,
                )
                db_session.add(state_model)
            else:
                state_model.state = json.dumps(canonical)
                state_model.updated_at = now
                db_session.add(state_model)

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()

    async def write_state(
        self,
        slug: str,
        state: dict[str, StateValue],
        *,
        session: SqlAsyncSession | None = None,
    ) -> None:
        """Upsert state JSON for a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            payload = canonicalize_state_for_storage(state)
            row_id = await self._resolve_active_row_id(db_session, slug)
            if row_id is None:
                msg = f"write_state: no active/icebox todo for slug {slug!r}"
                raise ValueError(msg)
            if await self._is_state_holder_slug(db_session, slug):
                msg = f"write_state: holder slug {slug!r} cannot have todo_state"
                raise HolderWriteRefused(msg)

            now = datetime.now(UTC).isoformat()
            state_model = await db_session.get(TodoStateModel, row_id)
            prior_phase = self._stored_lifecycle_phase(state_model)
            if state_model is None:
                state_model = TodoStateModel(
                    id=row_id,
                    slug=slug,
                    state=json.dumps(payload, default=str),
                    created_at=now,
                    updated_at=now,
                )
            else:
                state_model.slug = slug
                state_model.state = json.dumps(payload, default=str)
                state_model.updated_at = now
            db_session.add(state_model)
            await self._stamp_ready_since_for_payload(db_session, slug=slug, row_id=row_id, payload=payload, when=now)
            if not owns_session:
                # Caller-owned sessions commit outside this boundary, so the post-commit hook cannot fire here.
                return
            await db_session.commit()
            logger.info(
                "todo state written",
                slug=slug,
                lifecycle_phase=str(payload.get("lifecycle_phase", "")),
                kind=str(payload.get("kind", "")),
                mode="async",
            )
            self._on_mutation("todo_updated", None)
            new_phase = self._payload_lifecycle_phase(payload)
            if prior_phase != new_phase:
                self._on_phase_transition(slug, prior_phase, new_phase, payload)
        finally:
            if owns_session:
                await db_session.close()

    async def write_prepare_artifact_with_claim(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None,
        claimant_session_id: str,
        resolve_live_holder: Callable[[str | None], Awaitable[str | None]],
    ) -> str | None:
        """Atomically claim an unheld slug and write a prepare artifact.

        Closes the first-writer race by taking the write lock with
        ``BEGIN IMMEDIATE`` *before* re-reading the holder — the same atomic
        read-modify-write boundary the soft-delete path uses. Under the lock:

        1. re-read the slug's ``active_runner`` claim,
        2. resolve the current live holder via ``resolve_live_holder`` (the caller
           supplies the sessions-registry-aware resolver),
        3. if a *different* live session holds the slug, roll back and return the
           holder id **before any mutation** — the caller maps this to a conflict,
        4. else, when no *different* session holds the slug and
           ``claimant_session_id`` is a non-empty TeleClaude session id, bind it as
           ``active_runner`` (claim-on-write) — covering both an unheld slug and a
           session re-writing its own claim; a human-identity caller (empty id)
           writes without claiming,
        5. write the artifact and commit state + artifact in one transaction.

        Returns the conflicting holder's session id when refused, else ``None`` on
        a successful write. The lock serializes two unheld writers: the loser
        blocks until the winner commits, re-reads the winner's claim, and is
        refused — it never mutates from a stale snapshot nor surfaces a
        storage-busy error.
        """
        db_session = self._session()  # type: ignore[attr-defined]
        try:
            connection = await db_session.connection()
            await connection.exec_driver_sql("BEGIN IMMEDIATE")
            row_id = await self._resolve_active_row_id(db_session, slug)
            payload: dict[str, StateValue] | None = None
            active_runner: str | None = None
            if row_id is not None:
                state_model = await db_session.get(TodoStateModel, row_id)
                if state_model is not None:
                    payload = upcycle_state_dict(cast(dict[str, StateValue], json.loads(state_model.state)))
                    runner = payload.get("active_runner")
                    active_runner = runner if isinstance(runner, str) and runner else None
            holder = await resolve_live_holder(active_runner)
            if holder is not None and holder != claimant_session_id:
                await db_session.rollback()
                return holder
            if claimant_session_id and holder in (None, claimant_session_id) and payload is not None:
                payload["active_runner"] = claimant_session_id
                await self.write_state(slug, payload, session=db_session)
            await self.write_artifact(  # type: ignore[attr-defined]
                slug, name, content, updated_by=updated_by, session=db_session
            )
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise
        finally:
            await db_session.close()
        self.on_committed("todo_updated")  # type: ignore[attr-defined]
        return None

    async def set_state(self, slug: str, state: str | dict[str, StateValue]) -> None:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        if isinstance(state, str):
            parsed = json.loads(state)
            if not isinstance(parsed, dict):
                msg = "set_state expects a JSON object payload"
                raise ValueError(msg)
            typed_state: dict[str, StateValue] = parsed
        else:
            typed_state = state
        await self.write_state(slug, typed_state)

    async def read_state_delivered(self, slug: str) -> dict[str, StateValue] | None:
        """Read state for a delivered slug via todo ID join."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(TODO_STATE_TABLE.c.state)
                .join(TODO_TABLE, TODO_STATE_TABLE.c.id == TODO_TABLE.c.id)
                .where(TODO_TABLE.c.slug == slug)
                .where(TODO_TABLE.c.status == "delivered")
                .order_by(TODO_TABLE.c.delivered_at.desc())
                .limit(1)
            )
            state_json = result.one_or_none()
            if state_json is None:
                return None
            return upcycle_state_dict(cast(dict[str, StateValue], json.loads(str(state_json))))

    async def delete_state(self, slug: str, *, session: SqlAsyncSession | None = None) -> None:
        """Delete state for a slug."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            row_id = await self._resolve_active_row_id(db_session, slug)
            if row_id is None:
                return
            state_model = await db_session.get(TodoStateModel, row_id)
            if state_model is not None:
                await db_session.delete(state_model)
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
        finally:
            if owns_session:
                await db_session.close()

    async def rename_state_slug(
        self,
        old_slug: str,
        new_slug: str,
        *,
        session: SqlAsyncSession | None = None,
    ) -> bool:
        """Re-key the live state row and typed structured slug refs."""
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            row_id = await self._resolve_active_row_id(db_session, old_slug)
            if row_id is None:
                return False

            state_model = await db_session.get(TodoStateModel, row_id)
            if state_model is None:
                return True

            raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
            payload = _rename_breakdown_todos(raw_state, old_slug, new_slug)
            state_model.slug = new_slug
            state_model.state = json.dumps(payload, default=str)
            state_model.updated_at = datetime.now(UTC).isoformat()
            db_session.add(state_model)

            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated", None)
            return True
        finally:
            if owns_session:
                await db_session.close()

    async def list_slugs(self) -> list[str]:
        """Return all slugs with stored state, excluding soft-removed todos.

        State rows are retained when a todo is removed, so this enumeration must
        join the todo row and gate out ``removed`` — otherwise a removed todo
        leaks back in through the state-derived slug list.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(TodoStateModel.slug)
                .join(Todo, TODO_STATE_TABLE.c.id == TODO_TABLE.c.id)
                .where(TODO_TABLE.c.status != "removed")
                .order_by(TODO_STATE_TABLE.c.slug)
            )
            return [str(slug) for slug in result.all()]

    async def is_bug_todo(self, slug: str) -> bool:
        """Check whether a todo has the canonical bug kind."""
        state = await self.read_state(slug)
        if state is None:
            return False
        return state.get("kind") == KIND_BUG

    async def has_pending_deferrals(self, slug: str) -> bool:
        """Check if deferrals artifact exists and deferrals_processed is not True."""
        state = await self.read_state(slug)
        if state is None:
            return False
        if state.get("deferrals_processed") is True:
            return False
        exists: bool = await self.artifact_exists(slug, ARTIFACT_DEFERRALS)  # type: ignore[attr-defined]
        return exists

    def read_state_sync(self, slug: str) -> dict[str, StateValue] | None:
        """Sync version of read_state for use from worker threads."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            holder = session.exec(
                select(Todo.id)
                .where(TODO_TABLE.c.group_slug == slug)
                .where(TODO_TABLE.c.slug != slug)
                .where(TODO_TABLE.c.status != "removed")
                .limit(1)
            ).first()
            if holder is not None:
                return None
            row_id = session.exec(
                select(Todo.id)
                .where(TODO_TABLE.c.slug == slug)
                .where(TODO_TABLE.c.status.in_(("active", "icebox")))
                .limit(1)
            ).one_or_none()
            if row_id is None:
                return None
            state_model = session.get(TodoStateModel, str(row_id))
            if state_model is None:
                return None
            raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
            payload = upcycle_state_dict(raw_state)
            if self._record_v2_to_v3_if_needed(slug, raw_state, payload):
                state_model.state = json.dumps(payload, default=str)
                state_model.updated_at = datetime.now(UTC).isoformat()
                session.add(state_model)
                session.commit()
                self._on_mutation("todo_updated", None)
            return payload

    def write_state_sync(self, slug: str, state: dict[str, StateValue]) -> None:
        """Sync version of write_state for use from worker threads."""
        payload = canonicalize_state_for_storage(state)
        with self._sync_session() as session:  # type: ignore[attr-defined]
            row_id = session.exec(
                select(Todo.id)
                .where(TODO_TABLE.c.slug == slug)
                .where(TODO_TABLE.c.status.in_(("active", "icebox")))
                .limit(1)
            ).one_or_none()
            if row_id is None:
                msg = f"write_state_sync: no active/icebox todo for slug {slug!r}"
                raise ValueError(msg)
            holder = session.exec(
                select(Todo.id)
                .where(TODO_TABLE.c.group_slug == slug)
                .where(TODO_TABLE.c.slug != slug)
                .where(TODO_TABLE.c.status != "removed")
                .limit(1)
            ).first()
            if holder is not None:
                msg = f"write_state_sync: holder slug {slug!r} cannot have todo_state"
                raise HolderWriteRefused(msg)

            now = datetime.now(UTC).isoformat()
            state_model = session.get(TodoStateModel, str(row_id))
            prior_phase = self._stored_lifecycle_phase(state_model)
            if state_model is None:
                state_model = TodoStateModel(
                    id=str(row_id),
                    slug=slug,
                    state=json.dumps(payload, default=str),
                    created_at=now,
                    updated_at=now,
                )
            else:
                state_model.slug = slug
                state_model.state = json.dumps(payload, default=str)
                state_model.updated_at = now
            session.add(state_model)
            self._stamp_ready_since_for_payload_sync(session, slug=slug, row_id=str(row_id), payload=payload, when=now)
            session.commit()
        logger.info(
            "todo state written",
            slug=slug,
            lifecycle_phase=str(payload.get("lifecycle_phase", "")),
            kind=str(payload.get("kind", "")),
            mode="sync",
        )
        self._on_mutation("todo_updated", None)
        new_phase = self._payload_lifecycle_phase(payload)
        if prior_phase != new_phase:
            self._on_phase_transition(slug, prior_phase, new_phase, payload)
