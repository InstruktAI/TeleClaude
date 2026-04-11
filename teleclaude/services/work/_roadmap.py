"""Roadmap operations — list, add, move, freeze, deliver, deps."""
# pylint: disable=missing-function-docstring,too-many-arguments

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    ) -> list[TodoDTO]:
        """Return roadmap entries as TodoDTOs. Synchronous."""
        return assemble_roadmap_from_db(
            self._base.project_root,
            include_icebox=include_icebox,
            icebox_only=icebox_only,
            include_delivered=include_delivered,
            delivered_only=delivered_only,
        )

    # guard: loose-dict-func - roadmap entry shape mirrors TodosDb row, typed wrapper TBD
    async def get_entry(self, slug: str) -> dict[str, Any] | None:
        """Return a single roadmap entry by slug, or None if not found."""
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        entries = await db.list_roadmap()
        for entry in entries:
            if entry["slug"] == slug:
                return {
                    "slug": entry["slug"],
                    "position": entry["position"],
                    "group": entry["group_slug"],
                    "description": entry["description"],
                    "status": entry["status"],
                    "delivered_at": entry["delivered_at"],
                }
        return None

    async def dependencies(self, slug: str) -> list[str]:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.get_deps(slug)

    async def dependents(self, slug: str) -> list[str]:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        all_deps = await db.load_deps()
        return [s for s, deps in all_deps.items() if slug in deps]

    async def all_dependencies(self) -> dict[str, list[str]]:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.load_deps()

    async def delivered_slugs(self) -> set[str]:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.delivered_slugs()

    # -- mutations ------------------------------------------------------------

    async def add(
        self,
        slug: str,
        *,
        description: str = "",
        group: str | None = None,
        before: str | None = None,
        after: str | list[str] | None = None,
    ) -> str:
        """Add a new roadmap entry."""
        db = await self._base._ensure_db()  # pylint: disable=protected-access
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
            before=before,
        )
        return slug

    async def remove(self, slug: str) -> bool:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.remove_from_roadmap(slug)

    async def move(
        self,
        slug: str,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> bool:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.move_in_roadmap(slug, before=before, after=after)

    async def set_dependencies(self, slug: str, *, after: list[str]) -> None:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        await db.set_deps(slug, after=after)

    async def freeze(self, slug: str) -> bool:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.freeze(slug)

    async def unfreeze(self, slug: str) -> bool:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.unfreeze(slug)

    async def deliver(self, slug: str, *, commit: str | None = None) -> bool:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.deliver(slug, commit=commit)
