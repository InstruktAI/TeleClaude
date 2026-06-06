"""Handler for ``telec todo show``."""

from __future__ import annotations

import json as _json

from teleclaude.cli.tool_client import tool_api_request
from teleclaude.project_root import resolve_invocation_cwd

__all__ = ["_handle_todo_show"]

_USAGE = "Usage: telec todo show <slug> [--include-removed] [--include-artifact-content]"


def _handle_todo_show(args: list[str]) -> None:
    """Display the diagnostic todo state payload as JSON."""
    if not args or args[0].startswith("-"):
        print(_USAGE)
        raise SystemExit(1)

    slug = args[0]
    include_artifact_content = False
    include_removed = False
    for arg in args[1:]:
        if arg == "--include-artifact-content":
            include_artifact_content = True
        elif arg == "--include-removed":
            include_removed = True
        else:
            print(_USAGE)
            raise SystemExit(1)

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
