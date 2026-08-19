"""Reminder subcommand handlers for the declarative telec surface."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import TypedDict

from teleclaude.cli.tool_client import print_json, tool_api_call

_GET = "GET"
_POST = "POST"
_DELETE = "DELETE"
_REMINDERS_PATH = "/reminders"
_HELP_FLAGS = frozenset({"-h", "--help"})
_VALUE_FLAGS: dict[str, str] = {
    "--after": "after",
    "--at": "at",
    "--intent": "intent",
    "--slug": "target_slug",
}
_USAGE = "telec reminders set|list|cancel"
_SET_USAGE = "telec reminders set <slug> [flags]"
_CANCEL_USAGE = "telec reminders cancel <slug>|--all"


class _SetReminderBody(TypedDict, total=False):
    slug: str
    after: str
    at: str
    intent: str
    repeat: bool
    target_slug: str


def _print_presentation(payload: object) -> None:
    if isinstance(payload, Mapping):
        presentation = payload.get("presentation")
        if isinstance(presentation, str) and presentation:
            print(presentation)
            return
    print_json(payload)


def _parse_set_body(args: list[str]) -> _SetReminderBody:
    if not args or args[0] in _HELP_FLAGS:
        print(_SET_USAGE)
        raise SystemExit(0)
    body = _SetReminderBody(slug=args[0])
    index = 1
    while index < len(args):
        token = args[index]
        if token == "--repeat":
            body["repeat"] = True
            index += 1
            continue
        field = _VALUE_FLAGS.get(token)
        if field is None or index + 1 >= len(args):
            print(f"Invalid reminder set argument: {token}", file=sys.stderr)
            raise SystemExit(1)
        body[field] = args[index + 1]  # type: ignore[literal-required]
        index += 2
    return body


def handle_reminders(args: list[str]) -> None:
    """Handle telec reminders set/list/cancel."""
    if not args or args[0] in _HELP_FLAGS:
        print(_USAGE)
        return
    subcommand = args[0]
    rest = args[1:]
    if subcommand == "set":
        _print_presentation(tool_api_call(_POST, _REMINDERS_PATH, json_body=_parse_set_body(rest)))
        return
    if subcommand == "list":
        print_json(tool_api_call(_GET, _REMINDERS_PATH))
        return
    if subcommand == "cancel":
        _handle_cancel(rest)
        return
    print(f"Unknown reminders subcommand: {subcommand}", file=sys.stderr)
    raise SystemExit(1)


def _handle_cancel(args: list[str]) -> None:
    if not args or args[0] in _HELP_FLAGS:
        print(_CANCEL_USAGE)
        return
    if args == ["--all"]:
        payload = tool_api_call(_DELETE, _REMINDERS_PATH, params={"all": "true"})
        if isinstance(payload, list):
            for item in payload:
                _print_presentation(item)
            if not payload:
                print_json(payload)
        else:
            print_json(payload)
        return
    if len(args) != 1:
        print(_CANCEL_USAGE, file=sys.stderr)
        raise SystemExit(1)
    payload = tool_api_call(_DELETE, f"{_REMINDERS_PATH}/{args[0]}")
    _print_presentation(payload)
