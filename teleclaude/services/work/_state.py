"""Todo state operations — read/write phase state and classification."""
# pylint: disable=missing-function-docstring

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import StateValue

if TYPE_CHECKING:
    from teleclaude.services.work._base import WorkServiceBase


class StateOps:
    """Todo state reads and mutations.

    Held by SqliteWorkService and accessed as `svc.state`.
    """

    def __init__(self, base: WorkServiceBase) -> None:
        self._base = base

    async def read(self, slug: str) -> dict[str, StateValue] | None:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.read_state(slug)

    async def write(self, slug: str, state: dict[str, StateValue]) -> None:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        await db.write_state(slug, state)

    async def delete(self, slug: str) -> None:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        await db.delete_state(slug)

    async def list_slugs(self) -> list[str]:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.list_slugs()

    async def is_bug(self, slug: str) -> bool:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.is_bug_todo(slug)

    async def has_pending_deferrals(self, slug: str) -> bool:
        db = await self._base._ensure_db()  # pylint: disable=protected-access
        return await db.has_pending_deferrals(slug)
