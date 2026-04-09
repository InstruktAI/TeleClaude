"""Work service — SQLite implementation wrapping TodosDb.

This is the first service implementation. It wraps the existing TodosDb
behind the WorkReader/WorkWriter protocols, proving the service pattern
without changing any business logic.

Callers import this module and call get_work_service(project_root) to
obtain a service instance. The service delegates to TodosDb internally.
"""
# pylint: disable=missing-function-docstring,too-many-arguments,too-many-public-methods

from __future__ import annotations

from pathlib import Path
from typing import Any

from teleclaude.api_models import TodoDTO
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.roadmap import assemble_roadmap_from_db
from teleclaude.core.todos_db import TodosDb


# guard: loose-dict-func - v2 service wrapper; row shapes match TodosDb and will be typed later
class SqliteWorkService:
    """Work service backed by the existing TodosDb (SQLite).

    Implements WorkReader and WorkWriter protocols via delegation.
    No new logic — just the interface seam between callers and storage.
    """

    def __init__(self, project_root: str) -> None:
        self._project_root = project_root
        self._db: TodosDb | None = None

    async def _ensure_db(self) -> TodosDb:
        if self._db is None:
            db_path = str(Path(self._project_root) / ".teleclaude" / "todos.db")
            db = TodosDb(db_path)
            await db.initialize()
            self._db = db
        return self._db

    # -- WorkReader: roadmap reads --------------------------------------------

    def list_roadmap(
        self,
        *,
        include_icebox: bool = False,
        icebox_only: bool = False,
        include_delivered: bool = False,
        delivered_only: bool = False,
    ) -> list[TodoDTO]:
        """List roadmap entries. Synchronous — mirrors assemble_roadmap_from_db."""
        return assemble_roadmap_from_db(
            self._project_root,
            include_icebox=include_icebox,
            icebox_only=icebox_only,
            include_delivered=include_delivered,
            delivered_only=delivered_only,
        )

    async def get_roadmap_entry(self, slug: str) -> dict[str, Any] | None:
        db = await self._ensure_db()
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

    async def get_dependencies(self, slug: str) -> list[str]:
        db = await self._ensure_db()
        return await db.get_deps(slug)

    async def get_dependents(self, slug: str) -> list[str]:
        db = await self._ensure_db()
        all_deps = await db.load_deps()
        return [s for s, deps in all_deps.items() if slug in deps]

    async def get_all_dependencies(self) -> dict[str, list[str]]:
        db = await self._ensure_db()
        return await db.load_deps()

    async def delivered_slugs(self) -> set[str]:
        db = await self._ensure_db()
        return await db.delivered_slugs()

    # -- WorkReader: todo state reads -----------------------------------------

    async def get_todo(self, slug: str) -> dict[str, StateValue] | None:
        db = await self._ensure_db()
        return await db.read_state(slug)

    async def list_slugs(self) -> list[str]:
        db = await self._ensure_db()
        return await db.list_slugs()

    async def is_bug_todo(self, slug: str) -> bool:
        db = await self._ensure_db()
        return await db.is_bug_todo(slug)

    async def has_pending_deferrals(self, slug: str) -> bool:
        db = await self._ensure_db()
        return await db.has_pending_deferrals(slug)

    # -- WorkReader: artifact reads -------------------------------------------

    async def read_artifact(self, slug: str, name: str) -> str:
        db = await self._ensure_db()
        return await db.read_artifact(slug, name)

    async def artifact_exists(self, slug: str, name: str) -> bool:
        db = await self._ensure_db()
        return await db.artifact_exists(slug, name)

    async def artifact_digest(self, slug: str, name: str) -> str:
        db = await self._ensure_db()
        return await db.artifact_digest(slug, name)

    async def list_artifacts(self, slug: str) -> list[str]:
        db = await self._ensure_db()
        return await db.list_artifacts(slug)

    async def artifact_versions(self, slug: str, name: str, *, limit: int = 50) -> list[dict[str, Any]]:
        db = await self._ensure_db()
        rows = await db.artifact_versions(slug, name, limit=limit)
        return [{"content": r["content"], "created_at": r["created_at"]} for r in rows]

    # -- WorkWriter: roadmap mutations ----------------------------------------

    async def add_roadmap_entry(
        self,
        slug: str,
        *,
        domain: str = "sdlc",
        description: str = "",
        kind: str = "feature",
        group: str | None = None,
        before: str | None = None,
        after: str | None = None,
        parent_id: str | None = None,
    ) -> str:
        del domain, kind, parent_id  # v2 protocol params; underlying TodosDb does not yet consume them
        db = await self._ensure_db()
        await db.add_to_roadmap(
            slug,
            group_slug=group,
            after=after.split(",") if isinstance(after, str) else after,
            description=description,
            before=before,
        )
        return slug

    async def remove_roadmap_entry(self, slug: str) -> bool:
        db = await self._ensure_db()
        return await db.remove_from_roadmap(slug)

    async def move_roadmap_entry(self, slug: str, *, before: str | None = None, after: str | None = None) -> bool:
        db = await self._ensure_db()
        return await db.move_in_roadmap(slug, before=before, after=after)

    async def set_dependencies(self, slug: str, *, after: list[str]) -> None:
        db = await self._ensure_db()
        await db.set_deps(slug, after=after)

    async def freeze(self, slug: str) -> bool:
        db = await self._ensure_db()
        return await db.freeze(slug)

    async def unfreeze(self, slug: str) -> bool:
        db = await self._ensure_db()
        return await db.unfreeze(slug)

    async def deliver(self, slug: str, *, commit: str | None = None) -> bool:
        db = await self._ensure_db()
        return await db.deliver(slug, commit=commit)

    # -- WorkWriter: todo state mutations -------------------------------------

    async def write_state(self, slug: str, state: dict[str, StateValue]) -> None:
        db = await self._ensure_db()
        await db.write_state(slug, state)

    async def delete_state(self, slug: str) -> None:
        db = await self._ensure_db()
        await db.delete_state(slug)

    # -- WorkWriter: artifact mutations ---------------------------------------

    async def write_artifact(
        self,
        slug: str,
        name: str,
        content: str,
        *,
        updated_by: str | None = None,
    ) -> None:
        db = await self._ensure_db()
        await db.write_artifact(slug, name, content, updated_by=updated_by)

    async def delete_artifacts(self, slug: str) -> None:
        db = await self._ensure_db()
        await db.delete_artifacts(slug)


# -- Service factory ----------------------------------------------------------

_instances: dict[str, SqliteWorkService] = {}


def get_work_service(project_root: str) -> SqliteWorkService:
    """Return a WorkService for the given project root, cached per path."""
    resolved = str(Path(project_root).resolve())
    if resolved not in _instances:
        _instances[resolved] = SqliteWorkService(resolved)
    return _instances[resolved]
