"""Handler for ``telec todo return-to-work``."""

from __future__ import annotations

from http import HTTPMethod

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import TODO_RETURN_TO_WORK
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.types.todo_return import (
    TodoReturnToWorkApiRoute,
    TodoReturnToWorkRequestField,
    TodoReturnToWorkResponseField,
    TodoReturnToWorkResultStatus,
)

__all__ = ["_handle_todo_return_to_work"]

_RETURN_TO_WORK_USAGE = "Usage: telec todo return-to-work <slug> --reason <reason> --evidence <address>"
_RETURN_REASON_EVIDENCE_REQUIRED = "Error: --reason and --evidence must both be non-empty"
_RETURN_SUCCESS_TEMPLATE = (
    "Returned {slug} to the existing work cycle; hold, candidate, preparation, and review history were preserved"
)
_API_RESPONSE_STATUS_KEY = TodoReturnToWorkResponseField.STATUS


def _handle_todo_return_to_work(args: list[str]) -> None:
    """Send an evidence-bearing return request to the workflow owner."""
    parsed = parse_command_args(TODO_RETURN_TO_WORK, args)
    if len(parsed.positionals) != 1:
        print(_RETURN_TO_WORK_USAGE)
        raise SystemExit(1)

    slug = parsed.positionals[0]
    reason = parsed.value(F.FLAG_TODO_RETURN_REASON)
    evidence = parsed.value(F.FLAG_TODO_RETURN_EVIDENCE)
    if not reason or not reason.strip() or not evidence or not evidence.strip():
        print(_RETURN_REASON_EVIDENCE_REQUIRED)
        print(_RETURN_TO_WORK_USAGE)
        raise SystemExit(1)

    response = tool_api_call(
        HTTPMethod.POST,
        TodoReturnToWorkApiRoute.PATH,
        json_body={
            TodoReturnToWorkRequestField.SLUG: slug,
            TodoReturnToWorkRequestField.REASON: reason,
            TodoReturnToWorkRequestField.EVIDENCE: evidence,
            TodoReturnToWorkRequestField.CWD: project_reference(),
        },
    )
    if isinstance(response, dict) and response.get(_API_RESPONSE_STATUS_KEY) == TodoReturnToWorkResultStatus.OK:
        print(_RETURN_SUCCESS_TEMPLATE.format(slug=slug))
        return
    print_json(response)
    raise SystemExit(1)
