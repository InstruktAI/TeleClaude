"""CLI adapters for transferring workflow todo databases between computers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from enum import StrEnum
from typing import NoReturn

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import TODO_SYNC, TODO_SYNC_REPLICA

_LIST_SEPARATOR = ","
_USAGE_ERROR = "{usage}"
_REQUIRED_FLAGS_ERROR = "Both --project and --to are required"
_EMPTY_LIST_ITEM_ERROR = "{flag} must contain non-empty comma-separated values"
_PREFLIGHT_ERROR = "Todo state transfer refused: {detail}"
_OUTCOME_LINE = "{project} → {computer}: {status}: {detail}"
_MODE_ERROR = "Expected helper mode 'locate' or 'check'"
_SLUG_ERROR = "Project slug must be a lowercase kebab-case value"


class _ReplicaMode(StrEnum):
    """Closed set of operations accepted by the hidden target helper."""

    LOCATE = "locate"
    CHECK = "check"


def handle_todo_sync(args: list[str]) -> None:
    """Copy named project todo databases to each named target."""
    parsed = parse_command_args(TODO_SYNC, args)
    project_values = parsed.value(F.FLAG_TODO_SYNC_PROJECT)
    computer_values = parsed.value(F.FLAG_TODO_SYNC_TO)
    if project_values is None or computer_values is None:
        _print_usage_error(_REQUIRED_FLAGS_ERROR, "sync")

    try:
        projects = _parse_list(project_values, F.FLAG_TODO_SYNC_PROJECT.long)
        computers = _parse_computers(computer_values)
    except ValueError as error:
        _print_usage_error(str(error), "sync")

    from teleclaude.core.todo_state_transfer import (  # noqa: PLC0415 - load transfer and Redis dependencies only for this command.
        TransferStatus,
        transfer_todo_state,
    )

    try:
        outcomes = asyncio.run(transfer_todo_state(projects, computers))
    except (RuntimeError, ValueError) as error:
        print(_PREFLIGHT_ERROR.format(detail=error))
        raise SystemExit(1) from error

    for outcome in outcomes:
        print(
            _OUTCOME_LINE.format(
                project=outcome.project,
                computer=outcome.computer,
                status=outcome.status.value,
                detail=outcome.detail,
            )
        )
    if any(outcome.status is TransferStatus.FAILED for outcome in outcomes):
        raise SystemExit(1)


def handle_todo_sync_replica(args: list[str]) -> None:
    """Answer the remote sync helper's local database lookup or integrity check."""
    parsed = parse_command_args(TODO_SYNC_REPLICA, args)
    if len(parsed.positionals) != 2:
        _print_usage_error(_MODE_ERROR, "sync-replica")
    try:
        mode = _ReplicaMode(parsed.positionals[0])
    except ValueError:
        _print_usage_error(_MODE_ERROR, "sync-replica")
    project_slug = parsed.positionals[1]
    if not project_slug or project_slug != project_slug.strip():
        print(_SLUG_ERROR)
        raise SystemExit(1)

    from teleclaude.core.todo_state_transfer import (  # noqa: PLC0415 - keep target workflow access command-local.
        check_todo_database,
        locate_todo_database,
    )

    try:
        if mode is _ReplicaMode.LOCATE:
            output = json.dumps(asdict(locate_todo_database(project_slug)))
        else:
            output = json.dumps(asdict(check_todo_database(project_slug)))
    except ValueError as error:
        print(_SLUG_ERROR)
        raise SystemExit(1) from error
    print(output)


def _parse_list(value: str, flag: str) -> list[str]:
    """Split one comma-separated CLI value and reject empty or padded entries."""
    items = value.split(_LIST_SEPARATOR)
    if not items or any(not item or item != item.strip() for item in items):
        raise ValueError(_EMPTY_LIST_ITEM_ERROR.format(flag=flag))
    return items


def _parse_computers(value: str) -> list[str]:
    """Split target names, allowing spaces around each comma-delimited name."""
    items = [item.strip() for item in value.split(_LIST_SEPARATOR)]
    if not items or any(not item for item in items):
        raise ValueError(_EMPTY_LIST_ITEM_ERROR.format(flag=F.FLAG_TODO_SYNC_TO.long))
    return items


def _print_usage_error(message: str, subcommand: str) -> NoReturn:
    print(message)
    print(_USAGE_ERROR.format(usage=_usage("todo", subcommand)))
    raise SystemExit(1)
