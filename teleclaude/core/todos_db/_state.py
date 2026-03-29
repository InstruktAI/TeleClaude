"""Todo state persistence mixin."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import StateValue

if TYPE_CHECKING:
    import aiosqlite


class TodosDbStateMixin:
    """Read/write todo lifecycle state (replaces state_io.py)."""

    conn: aiosqlite.Connection | None

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        """Read state JSON for a slug. Returns None if not found."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT state FROM todo_state WHERE slug = ?",  # guard: raw-sql
            (slug,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        result: dict[str, StateValue] = json.loads(row[0])
        return result

    async def write_state(self, slug: str, state: dict[str, StateValue]) -> None:
        """Upsert state JSON for a slug."""
        assert self.conn is not None
        now = datetime.now(UTC).isoformat()
        state_json = json.dumps(state, default=str)
        await self.conn.execute(
            "INSERT INTO todo_state (slug, state, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(slug) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
            (slug, state_json, now, now),
        )
        await self.conn.commit()

    async def delete_state(self, slug: str) -> None:
        """Delete state for a slug."""
        assert self.conn is not None
        await self.conn.execute(
            "DELETE FROM todo_state WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        await self.conn.commit()

    async def list_slugs(self) -> list[str]:
        """Return all slugs with stored state."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT slug FROM todo_state ORDER BY slug",  # guard: raw-sql
        ) as cursor:
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

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
