"""Handler for ``telec code stamp``, split out of code.py to respect module size."""

from __future__ import annotations

from typing import TypedDict

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import CliUsageError, parse_command_args
from teleclaude.cli.telec.surface import CODE_STAMP
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.hooks.checkpoint_flags import consume_authored_main_commit_flag
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.types.todos import CommitReviewVerdict

__all__ = ["handle_code_stamp"]

_STAMP_ROUTE = "/code/stamp"
_SHA_SEPARATOR = ","
_ERR_NO_SHAS = "telec code stamp requires at least one commit SHA"
_ERR_NO_VERDICT = "telec code stamp requires --verdict approve|request_changes"
_ERR_BAD_VERDICT = "--verdict must be one of: {allowed}; got {given!r}"
_VERDICT_SEPARATOR = ", "
_OUTCOME_TEMPLATE = "Stamped {verdict} on {count} commit(s); {target}"
_TARGET_TODO_TEMPLATE = "repository evidence for todo {slug}"
_TARGET_NO_TODO = "repository commit-review evidence"
_DISCHARGED_TEMPLATE = "Discharged the post-commit review prompt of session {session_id}"


class _StampBody(TypedDict):
    shas: list[str]
    verdict: str
    reason: str
    cwd: str


def handle_code_stamp(args: list[str]) -> None:
    """Record a commit-review outcome on each SHA and discharge the stamped sessions' review gate."""
    parsed = parse_command_args(CODE_STAMP, args)
    shas = [sha for token in parsed.positionals for sha in token.split(_SHA_SEPARATOR) if sha]
    if not shas:
        raise CliUsageError(_ERR_NO_SHAS)
    raw_verdict = parsed.value(F.FLAG_CODE_STAMP_VERDICT)
    if raw_verdict is None:
        raise CliUsageError(_ERR_NO_VERDICT)
    try:
        verdict = CommitReviewVerdict(raw_verdict)
    except ValueError as exc:
        allowed = _VERDICT_SEPARATOR.join(member.value for member in CommitReviewVerdict)
        raise CliUsageError(_ERR_BAD_VERDICT.format(allowed=allowed, given=raw_verdict)) from exc

    body: _StampBody = {
        "shas": shas,
        "verdict": verdict.value,
        "reason": parsed.value(F.FLAG_CODE_STAMP_REASON) or "",
        "cwd": str(resolve_invocation_cwd()),
    }
    response = tool_api_call("POST", _STAMP_ROUTE, json_body=body)
    if not isinstance(response, dict):
        print_json(response)
        return
    slug = response.get("slug")
    target = _TARGET_TODO_TEMPLATE.format(slug=slug) if isinstance(slug, str) else _TARGET_NO_TODO
    recorded = response.get("shas")
    count = len(recorded) if isinstance(recorded, list) else len(shas)
    print(_OUTCOME_TEMPLATE.format(verdict=verdict.value, count=count, target=target))
    discharged = response.get("discharged_sessions")
    for session_id in discharged if isinstance(discharged, list) else []:
        if isinstance(session_id, str) and consume_authored_main_commit_flag(session_id):
            print(_DISCHARGED_TEMPLATE.format(session_id=session_id))
