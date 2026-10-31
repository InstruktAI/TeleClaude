"""Run synchronous CLI todo reads against the local workflow store."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import NoReturn

from teleclaude.cli.telec.handlers._todo_roots import _resolve_project_root_or_exit
from teleclaude.core.workflow_store.store import WorkflowStore, close_workflow_stores, get_workflow_store
from teleclaude.core.workflow_store.store_refusal import STORE_REFUSALS, describe_store_refusal


def run_todo_read[T](operation: Callable[[WorkflowStore], Awaitable[T]]) -> T:
    """Run one workflow-store read for the invocation project after CLI clearance.

    A GitHub workflow-store refusal exits with a clean CLI error naming its cause and door.
    """
    project_root = _resolve_project_root_or_exit()

    async def run() -> T:
        todos_db = await get_workflow_store(project_root)
        try:
            return await operation(todos_db)
        finally:
            await close_workflow_stores()

    try:
        return asyncio.run(run())
    except STORE_REFUSALS as refused:
        _exit_refused(describe_store_refusal(refused, project_root), refused)


def _exit_refused(detail: str, refused: Exception) -> NoReturn:
    print(f"Error: {detail}", file=sys.stderr)
    raise SystemExit(1) from refused
