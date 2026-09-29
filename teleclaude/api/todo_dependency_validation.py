"""Dependency validation helpers for todo route mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from teleclaude.core.todos_db import GroupDependencyConflict

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


async def validate_requested_dependencies(
    todos_db: TodosDb,
    slug: str,
    requested_after: list[str],
    *,
    check_membership: bool = True,
) -> None:
    for dep in requested_after:
        if not await todos_db.slug_in_todo(dep):
            raise HTTPException(status_code=404, detail=f"dependency '{dep}' not found in todo list")

    if check_membership:
        try:
            await todos_db.check_membership_update(
                slug,
                group_present=False,
                after=requested_after,
            )
        except GroupDependencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
