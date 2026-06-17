"""Dependency validation helpers for todo route mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from teleclaude.core.next_machine.dep_graph import holder_ancestors

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


async def validate_requested_dependencies(todos_db: TodosDb, slug: str, requested_after: list[str]) -> None:
    for dep in requested_after:
        if not await todos_db.slug_in_roadmap(dep):
            raise HTTPException(status_code=404, detail=f"dependency '{dep}' not found in todo list")

    roadmap = await todos_db.list_roadmap(include_icebox=True, include_delivered=True)
    group_slugs = {entry["slug"]: entry["group_slug"] for entry in roadmap}
    illegal_holders = holder_ancestors(group_slugs, slug).intersection(requested_after)
    if not illegal_holders:
        return

    holder = sorted(illegal_holders)[0]
    raise HTTPException(
        status_code=409,
        detail=(
            f"todo '{slug}' cannot depend on holder '{holder}': group membership and an after dependency "
            "on the same holder are mutually exclusive"
        ),
    )
