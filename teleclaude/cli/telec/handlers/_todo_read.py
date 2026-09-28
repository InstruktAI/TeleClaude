"""Run synchronous CLI todo reads against the local workflow store."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable

from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.project_root import resolve_invocation_roots


def run_todo_read[T](operation: Callable[[TodosDb], Awaitable[T]]) -> T:
    """Run one workflow-store read for the invocation project after CLI clearance."""
    try:
        project_root = resolve_invocation_roots().require_project_root()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    async def run() -> T:
        todos_db = await get_todos_db(project_root)
        try:
            return await operation(todos_db)
        finally:
            await close_todos_db_instances()

    return asyncio.run(run())
