"""Todo state persistence mixin."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.next_machine._types import StateValue

from ._models import ROADMAP_TABLE, TODO_STATE_TABLE, TodoRoadmap, TodoStateModel


class TodosDbStateMixin:
    """Read/write todo lifecycle state (replaces state_io.py)."""

    _on_mutation: Callable[[str], None]

    async def _resolve_active_row_id(self, session: SqlAsyncSession, slug: str) -> str | None:
        """Resolve an active or icebox roadmap slug to its stable row id."""
        result = await session.exec(
            select(TodoRoadmap.id)
            .where(ROADMAP_TABLE.c.slug == slug)
            .where(ROADMAP_TABLE.c.status != "delivered")
            .limit(1)
        )
        row_id = result.one_or_none()
        return str(row_id) if row_id is not None else None

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        """Read state JSON for a slug (active/icebox). Returns None if not found."""
        async with self._session() as session:  # type: ignore[attr-defined]
            row_id = await self._resolve_active_row_id(session, slug)
            if row_id is None:
                return None
            state_model = await session.get(TodoStateModel, row_id)
            if state_model is None:
                return None
            return cast(dict[str, StateValue], json.loads(state_model.state))

    async def get_state(self, slug: str) -> dict[str, StateValue] | None:
        """Compatibility wrapper used by the SQLAlchemy migration spec."""
        return await self.read_state(slug)

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
            row_id = await self._resolve_active_row_id(db_session, slug)
            if row_id is None:
                msg = f"write_state: no active/icebox roadmap entry for slug {slug!r}"
                raise ValueError(msg)

            now = datetime.now(UTC).isoformat()
            state_model = await db_session.get(TodoStateModel, row_id)
            if state_model is None:
                state_model = TodoStateModel(
                    id=row_id,
                    slug=slug,
                    state=json.dumps(state, default=str),
                    created_at=now,
                    updated_at=now,
                )
            else:
                state_model.slug = slug
                state_model.state = json.dumps(state, default=str)
                state_model.updated_at = now
            db_session.add(state_model)
            if owns_session:
                await db_session.commit()
                self._on_mutation("todo_updated")
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
        """Read state for a delivered slug via roadmap ID join."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(TODO_STATE_TABLE.c.state)
                .join(ROADMAP_TABLE, TODO_STATE_TABLE.c.id == ROADMAP_TABLE.c.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status == "delivered")
                .order_by(ROADMAP_TABLE.c.delivered_at.desc())
                .limit(1)
            )
            state_json = result.one_or_none()
            if state_json is None:
                return None
            return cast(dict[str, StateValue], json.loads(str(state_json)))

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
                self._on_mutation("todo_updated")
        finally:
            if owns_session:
                await db_session.close()

    async def list_slugs(self) -> list[str]:
        """Return all slugs with stored state."""
        async with self._session() as session:  # type: ignore[attr-defined]
            result = await session.exec(select(TodoStateModel.slug).order_by(TODO_STATE_TABLE.c.slug))
            return [str(slug) for slug in result.all()]

    async def is_bug_todo(self, slug: str) -> bool:
        """Check if a todo has kind='bug'."""
        state = await self.read_state(slug)
        if state is None:
            return False
        return state.get("kind") == "bug"

    async def has_pending_deferrals(self, slug: str) -> bool:
        """Check if deferrals artifact exists and deferrals_processed is not True."""
        state = await self.read_state(slug)
        if state is None:
            return False
        if state.get("deferrals_processed") is True:
            return False
        exists: bool = await self.artifact_exists(slug, "deferrals")  # type: ignore[attr-defined]
        return exists

    def read_state_sync(self, slug: str) -> dict[str, StateValue] | None:
        """Sync version of read_state for use from worker threads."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            row_id = session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status != "delivered")
                .limit(1)
            ).one_or_none()
            if row_id is None:
                return None
            state_model = session.get(TodoStateModel, str(row_id))
            if state_model is None:
                return None
            return cast(dict[str, StateValue], json.loads(state_model.state))

    def write_state_sync(self, slug: str, state: dict[str, StateValue]) -> None:
        """Sync version of write_state for use from worker threads."""
        with self._sync_session() as session:  # type: ignore[attr-defined]
            row_id = session.exec(
                select(TodoRoadmap.id)
                .where(ROADMAP_TABLE.c.slug == slug)
                .where(ROADMAP_TABLE.c.status != "delivered")
                .limit(1)
            ).one_or_none()
            if row_id is None:
                msg = f"write_state_sync: no active/icebox roadmap entry for slug {slug!r}"
                raise ValueError(msg)

            now = datetime.now(UTC).isoformat()
            state_model = session.get(TodoStateModel, str(row_id))
            if state_model is None:
                state_model = TodoStateModel(
                    id=str(row_id),
                    slug=slug,
                    state=json.dumps(state, default=str),
                    created_at=now,
                    updated_at=now,
                )
            else:
                state_model.slug = slug
                state_model.state = json.dumps(state, default=str)
                state_model.updated_at = now
            session.add(state_model)
            session.commit()
        self._on_mutation("todo_updated")
