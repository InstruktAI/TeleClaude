"""Roadmap persistence mixin."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.core.todos_db._rows import RoadmapRow

if TYPE_CHECKING:
    import aiosqlite


class TodosDbRoadmapMixin:
    """Roadmap CRUD, ordering, deps, delivery, icebox (replaces roadmap.yaml)."""

    conn: aiosqlite.Connection | None

    async def list_roadmap(
        self,
        *,
        include_icebox: bool = False,
        include_delivered: bool = False,
    ) -> list[RoadmapRow]:
        """List roadmap entries ordered by position."""
        assert self.conn is not None
        conditions = ["status = 'active'"]
        if include_icebox:
            conditions.append("status = 'icebox'")
        if include_delivered:
            conditions.append("status = 'delivered'")
        where = " OR ".join(conditions)
        async with self.conn.execute(
            f"SELECT slug, position, group_slug, description, status, "  # guard: raw-sql
            f"delivered_at, delivered_commit, children "
            f"FROM roadmap WHERE {where} ORDER BY position",
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            RoadmapRow(
                slug=row[0],
                position=row[1],
                group_slug=row[2],
                description=row[3],
                status=row[4],
                delivered_at=row[5],
                delivered_commit=row[6],
                children=json.loads(row[7]) if row[7] else None,
            )
            for row in rows
        ]

    async def _next_position(self) -> int:
        """Return the next available position value."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM roadmap",  # guard: raw-sql
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        position: int = row[0]
        return position

    async def add_to_roadmap(  # pylint: disable=too-many-arguments
        self,
        slug: str,
        *,
        group_slug: str | None = None,
        after: list[str] | None = None,
        description: str | None = None,
        before: str | None = None,
    ) -> bool:
        """Add a slug to the roadmap. Returns False if already exists."""
        assert self.conn is not None
        if await self.slug_in_roadmap(slug):
            return False

        now = datetime.now(UTC).isoformat()

        if before:
            # Insert before target: get target position, shift others down
            async with self.conn.execute(
                "SELECT position FROM roadmap WHERE slug = ?",  # guard: raw-sql
                (before,),
            ) as cursor:
                target_row = await cursor.fetchone()
            if target_row:
                position = target_row[0]
                await self.conn.execute(
                    "UPDATE roadmap SET position = position + 1 WHERE position >= ?",  # guard: raw-sql
                    (position,),
                )
            else:
                position = await self._next_position()
        else:
            position = await self._next_position()

        await self.conn.execute(
            "INSERT INTO roadmap "  # guard: raw-sql
            "(slug, position, group_slug, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (slug, position, group_slug, description, now, now),
        )

        if after:
            for dep in after:
                await self.conn.execute(
                    "INSERT OR IGNORE INTO roadmap_deps (slug, depends_on) VALUES (?, ?)",  # guard: raw-sql
                    (slug, dep),
                )

        await self.conn.commit()
        return True

    async def remove_from_roadmap(self, slug: str) -> bool:
        """Remove a slug from the roadmap. Returns False if not found."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT 1 FROM roadmap WHERE slug = ?",  # guard: raw-sql
            (slug,),
        ) as cursor:
            if await cursor.fetchone() is None:
                return False

        await self.conn.execute(
            "DELETE FROM roadmap WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        await self.conn.execute(
            "DELETE FROM roadmap_deps WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        await self.conn.commit()
        return True

    async def slug_in_roadmap(self, slug: str) -> bool:
        """Check if a slug exists in the roadmap."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT 1 FROM roadmap WHERE slug = ?",  # guard: raw-sql
            (slug,),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def deliver(
        self,
        slug: str,
        *,
        commit: str | None = None,
        children: list[str] | None = None,
        delivered_at: str | None = None,
    ) -> bool:
        """Mark a slug as delivered. Returns False if not found."""
        assert self.conn is not None
        now = delivered_at or datetime.now(UTC).isoformat()
        children_json = json.dumps(children) if children else None
        result = await self.conn.execute(
            "UPDATE roadmap SET status = 'delivered', delivered_at = ?, "  # guard: raw-sql
            "delivered_commit = ?, children = ?, updated_at = ? WHERE slug = ?",
            (now, commit, children_json, now, slug),
        )
        await self.conn.commit()
        return result.rowcount > 0

    async def delivered_slugs(self) -> set[str]:
        """Return set of delivered slugs."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT slug FROM roadmap WHERE status = 'delivered'",  # guard: raw-sql
        ) as cursor:
            rows = await cursor.fetchall()
        return {row[0] for row in rows}

    async def freeze(self, slug: str) -> bool:
        """Move a slug to icebox. Returns False if not found."""
        assert self.conn is not None
        now = datetime.now(UTC).isoformat()
        result = await self.conn.execute(
            "UPDATE roadmap SET status = 'icebox', updated_at = ? WHERE slug = ?",  # guard: raw-sql
            (now, slug),
        )
        await self.conn.commit()
        return result.rowcount > 0

    async def unfreeze(self, slug: str) -> bool:
        """Restore a slug from icebox to active. Returns False if not found."""
        assert self.conn is not None
        now = datetime.now(UTC).isoformat()
        result = await self.conn.execute(
            "UPDATE roadmap SET status = 'active', updated_at = ? WHERE slug = ?",  # guard: raw-sql
            (now, slug),
        )
        await self.conn.commit()
        return result.rowcount > 0

    async def set_deps(self, slug: str, *, after: list[str]) -> None:
        """Replace dependencies for a slug."""
        assert self.conn is not None
        await self.conn.execute(
            "DELETE FROM roadmap_deps WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        for dep in after:
            await self.conn.execute(
                "INSERT OR IGNORE INTO roadmap_deps (slug, depends_on) VALUES (?, ?)",  # guard: raw-sql
                (slug, dep),
            )
        await self.conn.commit()

    async def load_deps(self) -> dict[str, list[str]]:
        """Return dependency graph: {slug: [depends_on, ...]}."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT slug, depends_on FROM roadmap_deps ORDER BY slug, depends_on",  # guard: raw-sql
        ) as cursor:
            rows = await cursor.fetchall()
        deps: dict[str, list[str]] = {}
        for row in rows:
            deps.setdefault(row[0], []).append(row[1])
        return deps

    async def clean_dep_references(self, slug: str) -> None:
        """Remove a slug from all dependency lists."""
        assert self.conn is not None
        await self.conn.execute(
            "DELETE FROM roadmap_deps WHERE depends_on = ?",  # guard: raw-sql
            (slug,),
        )
        await self.conn.commit()

    async def move_in_roadmap(
        self,
        slug: str,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> bool:
        """Reorder a slug in the roadmap. Returns False if slug or target not found."""
        assert self.conn is not None

        # Get current position
        async with self.conn.execute(
            "SELECT position FROM roadmap WHERE slug = ?",  # guard: raw-sql
            (slug,),
        ) as cursor:
            source_row = await cursor.fetchone()
        if source_row is None:
            return False

        target_slug = before or after
        async with self.conn.execute(
            "SELECT position FROM roadmap WHERE slug = ?",  # guard: raw-sql
            (target_slug,),
        ) as cursor:
            target_row = await cursor.fetchone()
        if target_row is None:
            return False

        # Remove source from current position
        old_pos = source_row[0]
        await self.conn.execute(
            "UPDATE roadmap SET position = position - 1 WHERE position > ?",  # guard: raw-sql
            (old_pos,),
        )

        # Calculate new position
        # Re-read target position after shift
        async with self.conn.execute(
            "SELECT position FROM roadmap WHERE slug = ?",  # guard: raw-sql
            (target_slug,),
        ) as cursor:
            target_row = await cursor.fetchone()
        assert target_row is not None

        if before:
            new_pos = target_row[0]
        else:
            new_pos = target_row[0] + 1

        # Make room at new position
        await self.conn.execute(
            "UPDATE roadmap SET position = position + 1 WHERE position >= ? AND slug != ?",  # guard: raw-sql
            (new_pos, slug),
        )

        # Place slug at new position
        now = datetime.now(UTC).isoformat()
        await self.conn.execute(
            "UPDATE roadmap SET position = ?, updated_at = ? WHERE slug = ?",  # guard: raw-sql
            (new_pos, now, slug),
        )
        await self.conn.commit()
        return True

    # --- Sync methods for integration thread ---

    def deliver_sync(
        self,
        slug: str,
        *,
        commit: str | None = None,
        children: list[str] | None = None,
    ) -> bool:
        """Sync version of deliver for use from worker threads."""
        now = datetime.now(UTC).isoformat()
        children_json = json.dumps(children) if children else None
        conn = self._sync_conn()  # type: ignore[attr-defined]
        try:
            cursor = conn.execute(
                "UPDATE roadmap SET status = 'delivered', delivered_at = ?, "  # guard: raw-sql
                "delivered_commit = ?, children = ?, updated_at = ? WHERE slug = ?",
                (now, commit, children_json, now, slug),
            )
            conn.commit()
            delivered: bool = cursor.rowcount > 0
            return delivered
        finally:
            conn.close()
