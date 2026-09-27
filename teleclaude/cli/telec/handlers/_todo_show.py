"""Handler for ``telec todo show``."""

from __future__ import annotations

import json as _json

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._todo_read import run_todo_read
from teleclaude.cli.telec.surface import TODO_SHOW
from teleclaude.constants import SLUG_NOT_FOUND_DETAIL
from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._show import ShowPayload, assemble_show_payload

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

    async def read_show(todos_db: TodosDb) -> ShowPayload | None:
        return await assemble_show_payload(
            todos_db,
            slug,
            include_removed=include_removed,
            include_artifact_content=include_artifact_content,
        )

    result = run_todo_read(read_show)
    if result is not None:
        print(_json.dumps(result, indent=2))
    else:
        print(f"Error: {SLUG_NOT_FOUND_DETAIL.format(slug=slug)}")
        raise SystemExit(1)
