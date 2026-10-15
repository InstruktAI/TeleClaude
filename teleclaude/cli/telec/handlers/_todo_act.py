"""Handler for ``telec todo act``."""

from __future__ import annotations

from http import HTTPMethod

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import TODO_ACT, TODO_CHILD
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.types.todo_act import TodoActApiRoute, TodoActRequestField, TodoActResponseField, TodoChildApiRoute
from teleclaude.types.workflow_record import Act

__all__ = ["_handle_todo_act", "_handle_todo_child"]

_ACT_USAGE = "Usage: telec todo act <item> <act> [<text>] [--sha <commit>] [--revision <digest>] [--person <slug>] [--finding <key>]"
_UNKNOWN_ACT_TEMPLATE = "Unknown act {act!r}; the acts are: {acts}"
_ACT_SEPARATOR = ", "
_PERFORMED_TEMPLATE = "Performed {act} on {item}: act {act_key}, phase {phase}, {state}"
_FINDING_TEMPLATE = "finding key: {key}"
_COMPLETE_STATE = "complete"
_IN_PROGRESS_STATE = "effects still running; repeat the act to complete them"
_NO_PHASE = "unknown"
_EXPOSED_ACTS = (
    Act.NOTE,
    Act.REVIEWED,
    Act.FINDING,
    Act.REPLY,
    Act.PREPARED,
    Act.WAITING,
    Act.DECISION,
    Act.KICKBACK,
    Act.RELEASE,
)


def _handle_todo_act(args: list[str]) -> None:
    """Send one act to the workflow owner and report its outcome."""
    parsed = parse_command_args(TODO_ACT, args)
    positionals = parsed.positionals
    if len(positionals) < 2 or len(positionals) > 3:
        print(_ACT_USAGE)
        raise SystemExit(1)
    item, raw_act = positionals[0], positionals[1]
    try:
        act = Act(raw_act)
    except ValueError:
        act = None
    if act is None or act not in _EXPOSED_ACTS:
        print(_UNKNOWN_ACT_TEMPLATE.format(act=raw_act, acts=_ACT_SEPARATOR.join(a.value for a in _EXPOSED_ACTS)))
        raise SystemExit(1)
    response = tool_api_call(
        HTTPMethod.POST,
        TodoActApiRoute.PATH,
        json_body={
            TodoActRequestField.ITEM: item,
            TodoActRequestField.ACT: act.value,
            TodoActRequestField.TEXT: positionals[2] if len(positionals) == 3 else "",
            TodoActRequestField.SHA: parsed.value(F.FLAG_ACT_SHA) or "",
            TodoActRequestField.REVISION: parsed.value(F.FLAG_ACT_REVISION) or "",
            TodoActRequestField.PERSON: parsed.value(F.FLAG_ACT_PERSON) or "",
            TodoActRequestField.FINDING: parsed.value(F.FLAG_ACT_FINDING) or "",
            TodoActRequestField.CWD: project_reference(),
        },
    )
    if not isinstance(response, dict) or response.get(TodoActResponseField.STATUS) != "ok":
        print_json(response)
        return
    state = _COMPLETE_STATE if response.get(TodoActResponseField.COMPLETE) else _IN_PROGRESS_STATE
    print(
        _PERFORMED_TEMPLATE.format(
            act=act.value,
            item=item,
            act_key=response.get(TodoActResponseField.ACT_KEY),
            phase=response.get(TodoActResponseField.PHASE) or _NO_PHASE,
            state=state,
        )
    )
    finding_key = response.get(TodoActResponseField.FINDING_KEY)
    if finding_key:
        print(_FINDING_TEMPLATE.format(key=finding_key))


_CHILD_USAGE = "Usage: telec todo child <item>"
_CHILD_STARTED_TEMPLATE = "Started {procedure} as session {session_id}"


def _handle_todo_child(args: list[str]) -> None:
    """Start the holding driver's child."""
    parsed = parse_command_args(TODO_CHILD, args)
    if len(parsed.positionals) != 1:
        print(_CHILD_USAGE)
        raise SystemExit(1)
    response = tool_api_call(
        HTTPMethod.POST,
        TodoChildApiRoute.PATH,
        json_body={TodoActRequestField.ITEM: parsed.positionals[0], TodoActRequestField.CWD: project_reference()},
    )
    if isinstance(response, dict) and response.get("status") == "ok":
        print(
            _CHILD_STARTED_TEMPLATE.format(procedure=response.get("procedure"), session_id=response.get("session_id"))
        )
        return
    print_json(response)
