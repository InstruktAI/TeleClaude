"""Todo state persistence mixin."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from sqlalchemy import Update, func, update
from sqlmodel import Session as SqlSession
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.constants import ARTIFACT_DEFERRALS, WORKTREE_DIR, TodoStatus
from teleclaude.core.next_machine.kinds import FAST_TRACK_PREPARED_KINDS, KIND_BUG
from teleclaude.core.next_machine.lifecycle import READY_BAND_PHASES, coerce_lifecycle_phase, is_ready_band_eligible
from teleclaude.core.workflow_store.types import WorkItemStateRead as TodoStatusStateRead
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, stored_holder, with_claim_change
from teleclaude.types.state_value import StateValue

from ._errors import HolderWriteRefused
from ._identity_pin import apply_todo_identity_pin
from ._migration_logs import record_v2_to_v3_migration
from ._models import TODO_DEPS_TABLE, TODO_STATE_TABLE, TODO_TABLE, Todo, TodoDep, TodoStateModel
from ._upcycle import _detect_schema_version, canonicalize_state_for_storage, upcycle_state_dict

if TYPE_CHECKING:
    from ._base import TodosDbBase

logger = get_logger(__name__)
_BEGIN_IMMEDIATE_SQL = "BEGIN IMMEDIATE"
_ACTIVE_RUNNER_JSON_PATH = "$.active_runner"
_RUNNER_RELEASE_PATCH = json.dumps({"active_runner": None, "manually_started": False})
_TODO_UPDATED_MUTATION = "todo_updated"

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


def _v2_upcycle_statement(todo_id: str, original_json: str, payload: dict[str, StateValue], now: str) -> Update:
    """Persist an upcycled payload only while the row still holds the JSON the read upcycled.

    The read upcycled a state it saw; a writer that committed since holds newer state, and the old JSON upcycled would
    overwrite it. The expected-original condition makes the persistence a no-op then; the next read upcycles again.
    """
    return (
        update(TODO_STATE_TABLE)
        .where(TODO_STATE_TABLE.c.id == todo_id)
        .where(TODO_STATE_TABLE.c.state == original_json)
        .values(state=json.dumps(payload, default=str), updated_at=now)
    )


class TodosDbStateMixin:
    """Read/write todo lifecycle state (replaces state_io.py)."""

    _on_mutation: Callable[[str, Mapping[str, object] | None], None]
    _on_phase_transition: Callable[[str, str, str, Mapping[str, object]], None]
    _on_claim_changed: Callable[[str, str | None, str | None], None]
    db_path: str

    def _stored_lifecycle_phase(self, state_model: TodoStateModel | None) -> str:
        if state_model is None:
            return ""
        raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
        payload = upcycle_state_dict(raw_state)
        phase = payload.get("lifecycle_phase")
        return phase if isinstance(phase, str) else ""

    def _stored_holder(self, state_model: TodoStateModel | None) -> str | None:
        """The claim holder recorded in a persisted state row, or None."""
        if state_model is None:
            return None
        raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
        return self._payload_holder(raw_state)

    def _payload_holder(self, payload: Mapping[str, StateValue]) -> str | None:
        return stored_holder(payload)

    def _carry_workflow_record(
        self, payload: dict[str, StateValue], state_model: TodoStateModel | None
    ) -> dict[str, StateValue]:
        """Keep the machine-owned workflow record the row already holds; only the machine's own commit replaces it."""
        if state_model is None:
            return payload
        stored = cast(dict[str, StateValue], json.loads(state_model.state)).get(WORKFLOW_STATE_KEY)
        if stored is None:
            return payload
        return {**payload, WORKFLOW_STATE_KEY: stored}

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
            apply_todo_identity_pin(
                select(Todo.id).where(TODO_TABLE.c.slug == slug),
                self,
                slug,
            )
            .where(TODO_TABLE.c.status.in_(("active", "icebox")))
            .limit(1)
        )
        row_id = result.one_or_none()
        return str(row_id) if row_id is not None else None

    async def _is_holder_status(self, session: SqlAsyncSession, slug: str) -> bool:
        """Return whether ``slug``'s live row has status ``holder``."""
        result = await session.exec(
            apply_todo_identity_pin(
                select(Todo.id).where(TODO_TABLE.c.slug == slug),
                self,
                slug,
            )
            .where(TODO_TABLE.c.status == TodoStatus.HOLDER.value)
            .limit(1)
        )
        return result.first() is not None

    async def is_holder(self, slug: str) -> bool:
        """Whether ``slug`` is a structural holder (status == 'holder').

        Holders carry no `todo_state`; their artifacts are preserved as frozen,
        read-only evidence. Public predicate so callers (e.g. the API) can refuse
        holder writes with a clean 409 before attempting one.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            return await self._is_holder_status(session, slug)

    async def is_structural_group_holder(self, slug: str) -> bool:
        """Whether the item is a structural group parent, not a live claim holder."""
        return await self.is_holder(slug)

    def list_active_states_sync(self) -> list[tuple[str, dict[str, StateValue]]]:
        """Read active item states in the stable order used by bug listing."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            rows = session.exec(
                select(Todo.slug, TodoStateModel.state)
                .join(TodoStateModel, TODO_TABLE.c.id == TODO_STATE_TABLE.c.id)
                .where(TODO_TABLE.c.status == TodoStatus.ACTIVE.value)
                .order_by(TODO_TABLE.c.updated_at.desc())
            ).all()
        results: list[tuple[str, dict[str, StateValue]]] = []
        for slug, state_json in rows:
            raw_state = cast(dict[str, StateValue], json.loads(state_json)) if state_json else {}
            results.append((str(slug), upcycle_state_dict(raw_state)))
        return results

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

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        """Read state JSON for a slug (active/icebox). Returns None if not found.

        A holder slug resolves to None here structurally: its status is
        neither ``active`` nor ``icebox``, so ``_resolve_active_row_id``
        already excludes it — no separate holder check is needed.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_active_row_id(session, slug)
            if row_id is None:
                return None
            state_model = await session.get(TodoStateModel, row_id)
            if state_model is None:
                return None
            raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
            payload = upcycle_state_dict(raw_state)
            if self._record_v2_to_v3_if_needed(slug, raw_state, payload):
                persisted = await session.exec(
                    _v2_upcycle_statement(
                        str(state_model.id), state_model.state, payload, datetime.now(UTC).isoformat()
                    )
                )
                await session.commit()
                if persisted.rowcount:
                    self._on_mutation("todo_updated", None)
            return payload

    async def read_state_in_session(self, slug: str, session: SqlAsyncSession) -> dict[str, StateValue] | None:
        """Read an active todo state through a caller-owned transaction."""
        row_id = await self._resolve_active_row_id(session, slug)
        if row_id is None:
            return None
        state_model = await session.get(TodoStateModel, row_id)
        if state_model is None:
            return None
        raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
        return upcycle_state_dict(raw_state)

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
                persisted = await session.exec(
                    _v2_upcycle_statement(
                        str(state_model.id), state_model.state, payload, datetime.now(UTC).isoformat()
                    )
                )
                await session.commit()
                if persisted.rowcount:
                    self._on_mutation("todo_updated", None)
            return payload

    async def read_status_and_state_by_id(self, todo_id: str) -> TodoStatusStateRead:
        """Read a todo row's current status, holder classification, and state."""
        async with self._session() as session:  # type: ignore[attr-defined]
            entry = await session.get(Todo, todo_id)
            if entry is None:
                return TodoStatusStateRead(status=None, state=None, is_structural_group_holder=False)
            is_holder = entry.status == TodoStatus.HOLDER.value
            if is_holder:
                return TodoStatusStateRead(status=entry.status, state=None, is_structural_group_holder=True)
            state_model = await session.get(TodoStateModel, todo_id)
            if state_model is None:
                return TodoStatusStateRead(status=entry.status, state=None, is_structural_group_holder=False)
            raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
            payload = upcycle_state_dict(raw_state)
            if self._record_v2_to_v3_if_needed(entry.slug, raw_state, payload):
                persisted = await session.exec(
                    _v2_upcycle_statement(
                        str(state_model.id), state_model.state, payload, datetime.now(UTC).isoformat()
                    )
                )
                await session.commit()
                if persisted.rowcount:
                    self._on_mutation("todo_updated", None)
            return TodoStatusStateRead(status=entry.status, state=payload, is_structural_group_holder=is_holder)

    async def read_status_and_states_by_id(self, todo_ids: list[str]) -> dict[str, TodoStatusStateRead]:
        """Read current statuses and upcycled states for a corpus in one session."""
        if not todo_ids:
            return {}

        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(Todo, TodoStateModel)
                .outerjoin(TodoStateModel, TODO_TABLE.c.id == TODO_STATE_TABLE.c.id)
                .where(TODO_TABLE.c.id.in_(todo_ids))
            )
            reads: dict[str, TodoStatusStateRead] = {}
            migrated = False
            for entry, state_model in result.all():
                is_holder = entry.status == TodoStatus.HOLDER.value
                if is_holder or state_model is None:
                    reads[entry.id] = TodoStatusStateRead(
                        status=entry.status, state=None, is_structural_group_holder=is_holder
                    )
                    continue
                raw_state = cast(dict[str, StateValue], json.loads(state_model.state))
                payload = upcycle_state_dict(raw_state)
                if self._record_v2_to_v3_if_needed(entry.slug, raw_state, payload):
                    persisted = await session.exec(
                        _v2_upcycle_statement(
                            str(state_model.id), state_model.state, payload, datetime.now(UTC).isoformat()
                        )
                    )
                    migrated = migrated or bool(persisted.rowcount)
                reads[entry.id] = TodoStatusStateRead(
                    status=entry.status, state=payload, is_structural_group_holder=False
                )
            if migrated:
                await session.commit()
                self._on_mutation("todo_updated", None)
            return reads

    async def get_state(self, slug: str) -> dict[str, StateValue] | None:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.read_state(slug)

    async def clear_active_runner_if_matches(self, todo_id: str, session_id: str) -> bool:
        """Patch the current stored driver fields only while ownership still matches."""
        statement = (
            update(TODO_STATE_TABLE)
            .where(
                TODO_STATE_TABLE.c.id == todo_id,
                func.json_extract(TODO_STATE_TABLE.c.state, _ACTIVE_RUNNER_JSON_PATH) == session_id,
            )
            .values(
                state=func.json_patch(TODO_STATE_TABLE.c.state, _RUNNER_RELEASE_PATCH),
                updated_at=datetime.now(UTC).isoformat(),
            )
            .returning(TODO_STATE_TABLE.c.id)
        )
        async with cast("TodosDbBase", self)._session() as session:
            result = await session.exec(statement)
            changed = result.first() is not None
            await session.commit()
        if changed:
            self._on_mutation(_TODO_UPDATED_MUTATION, None)
        return changed

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
            prior_holder = self._stored_holder(state_model)
            canonical = with_claim_change(self._carry_workflow_record(canonical, state_model), prior_holder)
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
                holder = self._payload_holder(canonical)
                if prior_holder != holder:
                    self._on_claim_changed(entry.slug, prior_holder, holder)
        finally:
            if owns_session:
                await db_session.close()

    async def merge_state_by_id(
        self,
        todo_id: str,
        merge: Callable[[dict[str, StateValue]], dict[str, StateValue] | None],
    ) -> bool:
        """Turn a row\'s stored state into the state to write, decided on the state this transaction reads.

        The row is addressed by its durable id, whatever its status. The write transaction is taken up front, so no
        other writer commits between the read and the write; ``merge`` may raise to write nothing, and returns None
        when the state needs no write. True when a state was written.
        """
        async with self._session() as session:  # type: ignore[attr-defined]
            connection = await session.connection()
            await connection.exec_driver_sql(_BEGIN_IMMEDIATE_SQL)
            try:
                state_model = await session.get(TodoStateModel, todo_id)
                if state_model is None:
                    await session.rollback()
                    return False
                prior_holder = self._stored_holder(state_model)
                merged = merge(upcycle_state_dict(cast(dict[str, StateValue], json.loads(state_model.state))))
                if merged is None:
                    await session.rollback()
                    return False
                await self.write_state_by_id(todo_id, merged, session=session)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
        slug = str(state_model.slug)
        self._on_mutation("todo_updated", None)
        holder = self._payload_holder(merged)
        if prior_holder != holder:
            self._on_claim_changed(slug, prior_holder, holder)
        return True

    async def write_state(
        self,
        slug: str,
        state: dict[str, StateValue],
        *,
        session: SqlAsyncSession | None = None,
        owns_workflow_record: bool = False,
    ) -> None:
        """Upsert state JSON for a slug.

        The item's workflow record is carried forward from the stored row unless the caller is the
        workflow machine's own commit (``owns_workflow_record``).
        """
        owns_session = session is None
        db_session = session or self._session()  # type: ignore[attr-defined]
        try:
            payload = canonicalize_state_for_storage(state)
            row_id = await self._resolve_active_row_id(db_session, slug)
            if row_id is None:
                if await self._is_holder_status(db_session, slug):
                    msg = f"write_state: holder slug {slug!r} cannot have todo_state"
                    raise HolderWriteRefused(msg)
                msg = f"write_state: no active/icebox todo for slug {slug!r}"
                raise ValueError(msg)

            now = datetime.now(UTC).isoformat()
            state_model = await db_session.get(TodoStateModel, row_id)
            prior_phase = self._stored_lifecycle_phase(state_model)
            prior_holder = self._stored_holder(state_model)
            if not owns_workflow_record:
                payload = self._carry_workflow_record(payload, state_model)
            payload = with_claim_change(payload, prior_holder)
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
            holder = self._payload_holder(payload)
            if prior_holder != holder:
                self._on_claim_changed(slug, prior_holder, holder)
        finally:
            if owns_session:
                await db_session.close()

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
                apply_todo_identity_pin(
                    select(TODO_STATE_TABLE.c.state)
                    .join(TODO_TABLE, TODO_STATE_TABLE.c.id == TODO_TABLE.c.id)
                    .where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
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
        """Sync version of read_state for use from worker threads.

        A holder slug resolves to None here structurally (see :meth:`read_state`).
        """
        with self._sync_session() as session:  # type: ignore[attr-defined]
            row_id = session.exec(
                apply_todo_identity_pin(
                    select(Todo.id).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
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
                persisted = session.exec(
                    _v2_upcycle_statement(
                        str(state_model.id), state_model.state, payload, datetime.now(UTC).isoformat()
                    )
                )
                session.commit()
                if persisted.rowcount:
                    self._on_mutation("todo_updated", None)
            return payload

    def write_state_sync(
        self,
        slug: str,
        state: dict[str, StateValue],
        *,
        merge: Callable[[dict[str, StateValue]], dict[str, StateValue]] | None = None,
    ) -> None:
        """Sync version of write_state for use from worker threads.

        ``merge``, when given, turns the stored state into the state to write, inside the same write transaction that
        reads it (taken up front, so no other writer commits between the read and the write); ``state`` is written
        as it is when the row has no stored state yet.
        """
        with self._sync_session() as session:  # type: ignore[attr-defined]
            if merge is not None:
                session.connection().exec_driver_sql(_BEGIN_IMMEDIATE_SQL)
            row_id = session.exec(
                apply_todo_identity_pin(
                    select(Todo.id).where(TODO_TABLE.c.slug == slug),
                    self,
                    slug,
                )
                .where(TODO_TABLE.c.status.in_(("active", "icebox")))
                .limit(1)
            ).one_or_none()
            if row_id is None:
                holder = session.exec(
                    apply_todo_identity_pin(
                        select(Todo.id).where(TODO_TABLE.c.slug == slug),
                        self,
                        slug,
                    )
                    .where(TODO_TABLE.c.status == TodoStatus.HOLDER.value)
                    .limit(1)
                ).first()
                if holder is not None:
                    msg = f"write_state_sync: holder slug {slug!r} cannot have todo_state"
                    raise HolderWriteRefused(msg)
                msg = f"write_state_sync: no active/icebox todo for slug {slug!r}"
                raise ValueError(msg)

            now = datetime.now(UTC).isoformat()
            state_model = session.get(TodoStateModel, str(row_id))
            if merge is not None and state_model is not None:
                state = merge(upcycle_state_dict(cast(dict[str, StateValue], json.loads(state_model.state))))
            payload = canonicalize_state_for_storage(state)
            prior_phase = self._stored_lifecycle_phase(state_model)
            prior_holder = self._stored_holder(state_model)
            payload = with_claim_change(self._carry_workflow_record(payload, state_model), prior_holder)
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
        holder = self._payload_holder(payload)
        if prior_holder != holder:
            self._on_claim_changed(slug, prior_holder, holder)
