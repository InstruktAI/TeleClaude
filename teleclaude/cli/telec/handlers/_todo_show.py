"""Handler for ``telec todo show``."""

from __future__ import annotations

import json as _json

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import addressed_computer, project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._todo_read import run_todo_read
from teleclaude.cli.telec.surface import TODO_SHOW
from teleclaude.constants import SLUG_NOT_FOUND_DETAIL
from teleclaude.core.todos_db._show import ShowPayload
from teleclaude.core.workflow_machine.standing import assemble_item_show
from teleclaude.core.workflow_store.store import WorkflowStore

__all__ = ["_handle_todo_show"]

_USAGE = "Usage: telec todo show <slug> [--include-removed] [--include-artifact-content]"


def _handle_todo_show(args: list[str]) -> None:
    """Display the diagnostic todo state payload as JSON."""
    parsed = parse_command_args(TODO_SHOW, args)
    positionals = parsed.positionals
    if len(positionals) != 1:
        print(_USAGE)
        raise SystemExit(1)
    slug = positionals[0]
    include_artifact_content = parsed.has(F.FLAG_TODO_SHOW_INCLUDE_ARTIFACT_CONTENT)
    include_removed = parsed.has(F.FLAG_TODO_SHOW_INCLUDE_REMOVED)

    async def read_show(todos_db: WorkflowStore) -> ShowPayload | None:
        return await assemble_item_show(
            todos_db,
            slug,
            include_removed=include_removed,
            include_artifact_content=include_artifact_content,
        )

    if addressed_computer() is not None:
        from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.

        remote = tool_api_call(
            "GET",
            f"/todos/show/{slug}",
            params={
                "cwd": project_reference(),
                "include_removed": include_removed,
                "include_artifact_content": include_artifact_content,
            },
        )
        print(_json.dumps(remote, indent=2))
        return

    result = run_todo_read(read_show)
    if result is not None:
        print(_json.dumps(result, indent=2))
    else:
        print(f"Error: {SLUG_NOT_FOUND_DETAIL.format(slug=slug)}")
        raise SystemExit(1)
