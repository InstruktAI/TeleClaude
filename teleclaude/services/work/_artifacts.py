"""Artifact operations — read, write, digest, list, versions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from teleclaude.services.work._base import WorkServiceBase


class ArtifactOps:
    """Artifact reads and mutations.

    Held by SqliteWorkService and accessed as `svc.artifacts`.
    """

    def __init__(self, base: WorkServiceBase) -> None:
        self._base = base

    # -- reads ----------------------------------------------------------------

    async def read(self, slug: str, name: str) -> str:
        db = await self._base._ensure_db()
        return await db.read_artifact(slug, name)

    async def exists(self, slug: str, name: str) -> bool:
        db = await self._base._ensure_db()
        return await db.artifact_exists(slug, name)

    async def digest(self, slug: str, name: str) -> str:
        db = await self._base._ensure_db()
        return await db.artifact_digest(slug, name)

    async def list_names(self, slug: str) -> list[str]:
        db = await self._base._ensure_db()
        return await db.list_artifacts(slug)

    # guard: loose-dict-func - artifact version rows
    async def versions(self, slug: str, name: str, *, limit: int = 50) -> list[dict[str, Any]]:
        db = await self._base._ensure_db()
        rows = await db.artifact_versions(slug, name, limit=limit)
        return [{"content": r["content"], "created_at": r["created_at"]} for r in rows]

    # -- mutations ------------------------------------------------------------

    async def write(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
    ) -> None:
        db = await self._base._ensure_db()
        await db.write_artifact(slug, name, content, updated_by=updated_by)

    async def delete_all(self, slug: str) -> None:
        db = await self._base._ensure_db()
        await db.delete_artifacts(slug)
