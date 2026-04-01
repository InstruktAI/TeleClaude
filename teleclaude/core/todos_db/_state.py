"""Todo state persistence mixin."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import StateValue

if TYPE_CHECKING:
    import aiosqlite


class TodosDbStateMixin:
    """Read/write todo lifecycle state (replaces state_io.py)."""

    conn: aiosqlite.Connection | None
    _on_mutation: Callable[[], None]

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        """Read state JSON for a slug (active/icebox). Returns None if not found."""
        assert self.conn is not None
        # Resolve slug → id via roadmap (prefer active/icebox)
        async with self.conn.execute(
            "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
            (slug,),
        ) as cursor:
            id_row = await cursor.fetchone()
        if id_row is None:
            # Fallback: try direct slug lookup in todo_state (delivered items)
            async with self.conn.execute(
                "SELECT state FROM todo_state WHERE slug = ? ORDER BY updated_at DESC LIMIT 1",  # guard: raw-sql
                (slug,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            result: dict[str, StateValue] = json.loads(row[0])
            return result

        async with self.conn.execute(
            "SELECT state FROM todo_state WHERE id = ?",  # guard: raw-sql
            (id_row[0],),
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

        # Resolve slug → id
        async with self.conn.execute(
            "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
            (slug,),
        ) as cursor:
            id_row = await cursor.fetchone()

        row_id = id_row[0] if id_row else slug  # fallback: use slug as id for orphaned state

        await self.conn.execute(
            "INSERT INTO todo_state (id, slug, state, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
            (row_id, slug, state_json, now, now),
        )
        await self.conn.commit()
        self._on_mutation()

    async def delete_state(self, slug: str) -> None:
        """Delete state for a slug."""
        assert self.conn is not None
        await self.conn.execute(
            "DELETE FROM todo_state WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        await self.conn.commit()
        self._on_mutation()

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

    # --- Sync methods for integration thread ---

    def read_state_sync(self, slug: str) -> dict[str, StateValue] | None:
        """Sync version of read_state for use from worker threads."""
        conn = self._sync_conn()  # type: ignore[attr-defined]
        try:
            # Resolve slug → id
            id_row = conn.execute(
                "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
                (slug,),
            ).fetchone()
            if id_row is None:
                # Fallback: direct slug lookup
                row = conn.execute(
                    "SELECT state FROM todo_state WHERE slug = ? ORDER BY updated_at DESC LIMIT 1",  # guard: raw-sql
                    (slug,),
                ).fetchone()
                if row is None:
                    return None
                fallback: dict[str, StateValue] = json.loads(row[0])
                return fallback

            row = conn.execute(
                "SELECT state FROM todo_state WHERE id = ?",  # guard: raw-sql
                (id_row[0],),
            ).fetchone()
            if row is None:
                return None
            result: dict[str, StateValue] = json.loads(row[0])
            return result
        finally:
            conn.close()

    def write_state_sync(self, slug: str, state: dict[str, StateValue]) -> None:
        """Sync version of write_state for use from worker threads."""
        now = datetime.now(UTC).isoformat()
        state_json = json.dumps(state, default=str)
        conn = self._sync_conn()  # type: ignore[attr-defined]
        try:
            # Resolve slug → id
            id_row = conn.execute(
                "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
                (slug,),
            ).fetchone()
            row_id = id_row[0] if id_row else slug

            conn.execute(
                "INSERT INTO todo_state (id, slug, state, created_at, updated_at) "  # guard: raw-sql
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at",
                (row_id, slug, state_json, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        self._on_mutation()
