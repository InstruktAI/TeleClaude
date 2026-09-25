"""Run synchronous CLI todo reads against the local workflow store."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable

from teleclaude.cli.session_auth import require_cli_clearance
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.project_root import resolve_invocation_cwd, resolve_project_root


def run_todo_read[T](command_path: str, operation: Callable[[TodosDb], Awaitable[T]]) -> T:
    """Authorize and run one workflow-store read for the invocation project."""
    require_cli_clearance(command_path)
    try:
        project_root = resolve_project_root(resolve_invocation_cwd())
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
