"""Todo artifact persistence mixin."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from teleclaude.core.todos_db._rows import ArtifactVersionRow

if TYPE_CHECKING:
    import aiosqlite


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TodosDbArtifactsMixin:
    """Read/write/version todo artifacts (replaces filesystem todos/{slug}/*.md)."""

    conn: aiosqlite.Connection | None

    async def read_artifact(self, slug: str, name: str) -> str:
        """Read artifact content. Returns empty string if not found."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT content FROM todo_artifacts WHERE slug = ? AND name = ?",  # guard: raw-sql
            (slug, name),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return ""
        result: str = row[0]
        return result

    async def write_artifact(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
    ) -> None:
        """Upsert artifact content and append to version history."""
        assert self.conn is not None
        now = datetime.now(UTC).isoformat()
        digest = _sha256(content)

        # Version history entry (append before upsert)
        await self.conn.execute(
            "INSERT INTO todo_artifact_versions "  # guard: raw-sql
            "(slug, name, content, digest, updated_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, content, digest, updated_by, now),
        )

        # Upsert current
        await self.conn.execute(
            "INSERT INTO todo_artifacts (slug, name, content, digest, updated_by, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(slug, name) DO UPDATE SET "
            "content = excluded.content, digest = excluded.digest, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (slug, name, content, digest, updated_by, now),
        )
        await self.conn.commit()

    async def artifact_digest(self, slug: str, name: str) -> str:
        """Return SHA-256 digest of current artifact content. Empty string if not found."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT digest FROM todo_artifacts WHERE slug = ? AND name = ?",  # guard: raw-sql
            (slug, name),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return ""
        digest: str = row[0]
        return digest

    async def artifact_exists(self, slug: str, name: str) -> bool:
        """Check if an artifact exists for a slug."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT 1 FROM todo_artifacts WHERE slug = ? AND name = ?",  # guard: raw-sql
            (slug, name),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def list_artifacts(self, slug: str) -> list[str]:
        """Return artifact names for a slug."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT name FROM todo_artifacts WHERE slug = ? ORDER BY name",  # guard: raw-sql
            (slug,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[ArtifactVersionRow]:
        """Return version history for an artifact, newest first."""
        assert self.conn is not None
        async with self.conn.execute(
            "SELECT content, digest, updated_by, created_at "  # guard: raw-sql
            "FROM todo_artifact_versions WHERE slug = ? AND name = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (slug, name, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            ArtifactVersionRow(
                content=row[0],
                digest=row[1],
                updated_by=row[2] or "",
                created_at=row[3],
            )
            for row in rows
        ]

    async def delete_artifacts(self, slug: str) -> None:
        """Delete all artifacts and version history for a slug."""
        assert self.conn is not None
        await self.conn.execute(
            "DELETE FROM todo_artifacts WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        await self.conn.execute(
            "DELETE FROM todo_artifact_versions WHERE slug = ?",  # guard: raw-sql
            (slug,),
        )
        await self.conn.commit()
