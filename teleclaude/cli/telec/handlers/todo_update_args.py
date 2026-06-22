"""Argument parsing for `telec todo update`."""

from __future__ import annotations

from typing import TypedDict

from teleclaude.cli.telec.help import _usage


class ParsedTodoUpdate(TypedDict):
    slug: str
    new_slug: str | None
    raw_after: list[str]
    after_present: bool
    schedule: str | None
    kind: str | None
    force: bool
    hold: bool
    release: bool


def _parse_todo_update_args(args: list[str]) -> ParsedTodoUpdate:
    slug: str | None = None
    new_slug: str | None = None
    raw_after: list[str] = []
    after_present = False
    schedule: str | None = None
    kind: str | None = None
    force = False
    hold = False
    release = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            new_slug = args[i + 1]
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            raw_after.append(args[i + 1])
            after_present = True
            i += 2
        elif arg == "--schedule" and i + 1 < len(args):
            schedule = args[i + 1]
            i += 2
        elif arg == "--kind" and i + 1 < len(args):
            kind = args[i + 1]
            i += 2
        elif arg == "--force":
            force = True
            i += 1
        elif arg == "--hold":
            hold = True
            i += 1
        elif arg == "--release":
            release = True
            i += 1
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "update"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if slug is None:
        print("Missing required slug.")
        print(_usage("todo", "update"))
        raise SystemExit(1)
    return {
        "slug": slug,
        "new_slug": new_slug,
        "raw_after": raw_after,
        "after_present": after_present,
        "schedule": schedule,
        "kind": kind,
        "force": force,
        "hold": hold,
        "release": release,
    }


__all__ = ["ParsedTodoUpdate", "_parse_todo_update_args"]
