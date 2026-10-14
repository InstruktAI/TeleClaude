"""Handler for ``telec todo return-to-work``."""

from __future__ import annotations

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import TODO_RETURN_TO_WORK
from teleclaude.cli.tool_client import print_json, tool_api_call

__all__ = ["_handle_todo_return_to_work"]


def _handle_todo_return_to_work(args: list[str]) -> None:
    """Send an evidence-bearing return request to the workflow owner."""
    parsed = parse_command_args(TODO_RETURN_TO_WORK, args)
    if len(parsed.positionals) != 1:
        print("Usage: telec todo return-to-work <slug> --reason <reason> --evidence <address>")
        raise SystemExit(1)

    slug = parsed.positionals[0]
    reason = parsed.value(F.FLAG_TODO_RETURN_REASON)
    evidence = parsed.value(F.FLAG_TODO_RETURN_EVIDENCE)
    if not reason or not reason.strip() or not evidence or not evidence.strip():
        print("Error: --reason and --evidence must both be non-empty")
        raise SystemExit(1)

    response = tool_api_call(
        "POST",
        "/todos/return-to-work",
        json_body={
            "slug": slug,
            "reason": reason,
            "evidence": evidence,
            "cwd": project_reference(),
        },
    )
    if isinstance(response, dict) and response.get("status") == "ok":
        print(f"Returned {slug} to build_started; hold, candidate, preparation, and review history were preserved")
        return
    print_json(response)
    raise SystemExit(1)
