"""Handler for ``telec todo show``."""

from __future__ import annotations

import json as _json

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import TODO_SHOW
from teleclaude.cli.tool_client import tool_api_request
from teleclaude.project_root import resolve_invocation_cwd

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

    params: dict[str, str] = {"cwd": str(resolve_invocation_cwd())}
    if include_artifact_content:
        params["include_artifact_content"] = "true"
    if include_removed:
        params["include_removed"] = "true"
    result = tool_api_request("GET", f"/todos/{slug}/show", params=params)

    if isinstance(result, dict) and "slug" in result:
        print(_json.dumps(result, indent=2))
    elif isinstance(result, dict) and result.get("detail"):
        print(f"Error: {result['detail']}")
        raise SystemExit(1)
    else:
        print(result)
