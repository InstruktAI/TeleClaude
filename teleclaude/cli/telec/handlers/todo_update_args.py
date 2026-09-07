"""Argument parsing for `telec todo update`."""

from __future__ import annotations

from typing import TypedDict

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import TODO_UPDATE


class ParsedTodoUpdate(TypedDict):
    slug: str
    new_slug: str | None
    raw_after: list[str]
    after_present: bool
    schedule: str | None
    kind: str | None
    force: bool
    hold: bool
    reason: str | None
    release: bool
    unclaim: bool


def _parse_todo_update_args(args: list[str]) -> ParsedTodoUpdate:
    parsed = parse_command_args(TODO_UPDATE, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one slug is allowed.")
        raise SystemExit(1)
    if not positionals:
        print("Missing required slug.")
        print(_usage("todo", "update"))
        raise SystemExit(1)

    return {
        "slug": positionals[0],
        "new_slug": parsed.value(F.FLAG_TODO_UPDATE_SLUG),
        "raw_after": list(parsed.values(F.FLAG_TODO_UPDATE_AFTER)),
        "after_present": parsed.has(F.FLAG_TODO_UPDATE_AFTER),
        "schedule": parsed.value(F.FLAG_TODO_UPDATE_SCHEDULE),
        "kind": parsed.value(F.FLAG_TODO_UPDATE_KIND),
        "force": parsed.has(F.FLAG_TODO_UPDATE_FORCE),
        "hold": parsed.has(F.FLAG_TODO_UPDATE_HOLD),
        "reason": parsed.value(F.FLAG_TODO_UPDATE_REASON),
        "release": parsed.has(F.FLAG_TODO_UPDATE_RELEASE),
        "unclaim": parsed.has(F.FLAG_TODO_UPDATE_UNCLAIM),
    }


__all__ = ["ParsedTodoUpdate", "_parse_todo_update_args"]
