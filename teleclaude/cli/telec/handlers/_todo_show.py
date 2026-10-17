"""Handler for ``telec todo show``."""

from __future__ import annotations

import json as _json

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import TODO_SHOW

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

    from teleclaude.cli.tool_client import tool_api_call  # noqa: PLC0415 - command boundary: daemon API client.

    # The standing of an item names the live sessions of earlier claims, which only the daemon that holds the session
    # store can read; a CLI process holds no such store, so the daemon answers for every show, local or addressed.
    shown = tool_api_call(
        "GET",
        f"/todos/show/{slug}",
        params={
            "cwd": project_reference(),
            "include_removed": include_removed,
            "include_artifact_content": include_artifact_content,
        },
    )
    print(_json.dumps(shown, indent=2))
