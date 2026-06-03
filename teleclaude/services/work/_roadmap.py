"""Roadmap operations — list, add, freeze, deliver, deps."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.api_models import TodoDTO
from teleclaude.core.roadmap import assemble_roadmap_from_db

if TYPE_CHECKING:
    from teleclaude.services.work._base import WorkServiceBase


class RoadmapOps:
    """Roadmap reads and mutations.

    Held by SqliteWorkService and accessed as `svc.roadmap`.
    """

    def __init__(self, base: WorkServiceBase) -> None:
        self._base = base

    # -- reads ----------------------------------------------------------------

    def entries(
        self,
        *,
        include_icebox: bool = False,
        icebox_only: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
        delivered_since: str | None = None,
        include_removed: bool = False,
        removed_only: bool = False,
    ) -> list[TodoDTO]:
        """Return roadmap entries as TodoDTOs. Synchronous."""
        return assemble_roadmap_from_db(
            self._base.project_root,
            include_icebox=include_icebox,
            icebox_only=icebox_only,
            include_delivered=include_delivered,
            delivered_only=delivered_only,
            delivered_since=delivered_since,
            include_removed=include_removed,
            removed_only=removed_only,
        )

    def get_entry(self, slug: str, *, include_icebox: bool = True, include_delivered: bool = True) -> TodoDTO | None:
        """Return a single roadmap entry as a TodoDTO, or None if not found.

        Uses the same rich projection as entries() — callers get consistent
        domain types whether they ask for one or many.
        """
        for todo in self.entries(
            include_icebox=include_icebox,
            include_delivered=include_delivered,
        ):
            if todo.slug == slug:
                return todo
        return None

    async def dependencies(self, slug: str) -> list[str]:
        db = await self._base._ensure_db()
        return await db.get_deps(slug)

    async def dependents(self, slug: str) -> list[str]:
        db = await self._base._ensure_db()
        all_deps = await db.load_deps()
        return [s for s, deps in all_deps.items() if slug in deps]

    async def all_dependencies(self) -> dict[str, list[str]]:
        db = await self._base._ensure_db()
        return await db.load_deps()

    async def delivered_slugs(self) -> set[str]:
        db = await self._base._ensure_db()
        return await db.delivered_slugs()

    # -- mutations ------------------------------------------------------------

    async def add(
        self,
        slug: str,
        *,
        description: str = "",
        group: str | None = None,
        after: str | list[str] | None = None,
    ) -> str:
        """Add a new roadmap entry."""
        db = await self._base._ensure_db()
        after_list: list[str] | None
        if isinstance(after, str):
            after_list = [p.strip() for p in after.split(",") if p.strip()]
        else:
            after_list = after
        await db.add_to_roadmap(
            slug,
            group_slug=group,
            after=after_list,
            description=description,
        )
        return slug

    async def remove(self, slug: str) -> bool:
        db = await self._base._ensure_db()
        return await db.soft_remove_from_roadmap(slug, cwd=self._base.project_root)

    async def set_dependencies(self, slug: str, *, after: list[str]) -> None:
        db = await self._base._ensure_db()
        await db.set_deps(slug, after=after)

    async def freeze(self, slug: str) -> bool:
        db = await self._base._ensure_db()
        return await db.freeze(slug)

    async def unfreeze(self, slug: str) -> bool:
        db = await self._base._ensure_db()
        return await db.unfreeze(slug)

    async def deliver(self, slug: str, *, commit: str | None = None) -> bool:
        db = await self._base._ensure_db()
        return await db.deliver(slug, commit=commit)
