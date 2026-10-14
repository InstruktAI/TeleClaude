"""Run synchronous CLI todo reads against the local workflow store."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from teleclaude.cli.telec.handlers._todo_roots import _resolve_project_root_or_exit
from teleclaude.core.workflow_store.store import WorkflowStore, close_workflow_stores, get_workflow_store


def run_todo_read[T](operation: Callable[[WorkflowStore], Awaitable[T]]) -> T:
    """Run one workflow-store read for the invocation project after CLI clearance."""
    project_root = _resolve_project_root_or_exit()

    async def run() -> T:
        todos_db = await get_workflow_store(project_root)
        try:
            return await operation(todos_db)
        finally:
            await close_workflow_stores()

    return asyncio.run(run())
