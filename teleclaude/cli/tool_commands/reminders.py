"""Reminder subcommand handlers for the declarative telec surface."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import TypedDict

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import REMINDERS_CANCEL, REMINDERS_SET
from teleclaude.cli.tool_client import print_json, tool_api_call

_GET = "GET"
_POST = "POST"
_DELETE = "DELETE"
_REMINDERS_PATH = "/reminders"
_HELP_FLAGS = frozenset({"-h", "--help"})
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


def _parse_set_body(args: list[str]) -> _SetReminderBody | None:
    parsed = parse_command_args(REMINDERS_SET, args)
    positionals = parsed.positionals
    if len(positionals) == 0:
        print(_SET_USAGE)
        return None
    if len(positionals) != 1:
        print(f"Invalid reminder set argument: {positionals[-1]}", file=sys.stderr)
        raise SystemExit(1)

    body = _SetReminderBody(slug=positionals[0])
    after = parsed.value(F.FLAG_REMINDER_AFTER)
    if after is not None:
        body["after"] = after
    at = parsed.value(F.FLAG_REMINDER_AT)
    if at is not None:
        body["at"] = at
    intent = parsed.value(F.FLAG_REMINDER_INTENT)
    if intent is not None:
        body["intent"] = intent
    if parsed.has(F.FLAG_REMINDER_REPEAT):
        body["repeat"] = True
    target_slug = parsed.value(F.FLAG_REMINDER_SLUG)
    if target_slug is not None:
        body["target_slug"] = target_slug
    return body


def handle_reminders(args: list[str]) -> None:
    """Handle telec reminders set/list/cancel."""
    if not args or args[0] in _HELP_FLAGS:
        print(_USAGE)
        return
    subcommand = args[0]
    rest = args[1:]
    if subcommand == "set":
        body = _parse_set_body(rest)
        if body is None:
            return
        _print_presentation(tool_api_call(_POST, _REMINDERS_PATH, json_body=body))
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
    parsed = parse_command_args(REMINDERS_CANCEL, args)
    positionals = parsed.positionals
    cancel_all = parsed.has(F.FLAG_REMINDER_CANCEL_ALL)

    if not positionals and not cancel_all:
        print(_CANCEL_USAGE)
        return
    if cancel_all and positionals:
        print(_CANCEL_USAGE, file=sys.stderr)
        raise SystemExit(1)

    if cancel_all:
        payload = tool_api_call(_DELETE, _REMINDERS_PATH, params={"all": "true"})
        if isinstance(payload, list):
            for item in payload:
                _print_presentation(item)
            if not payload:
                print_json(payload)
        else:
            print_json(payload)
        return

    if len(positionals) != 1:
        print(_CANCEL_USAGE, file=sys.stderr)
        raise SystemExit(1)
    payload = tool_api_call(_DELETE, f"{_REMINDERS_PATH}/{positionals[0]}")
    _print_presentation(payload)
