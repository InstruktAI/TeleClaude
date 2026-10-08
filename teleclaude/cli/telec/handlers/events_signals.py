"""Handlers for telec events and signals commands."""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Any, cast

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    EVENTS_LIST,
    EVENTS_SCHEMA,
    EventCommand,
)
from teleclaude.events.catalog import EventCatalog, EventDeclaration
from teleclaude.paths import EVENTS_DB_PATH

__all__ = [
    "_handle_events",
    "_handle_events_list",
    "_handle_signals",
    "_handle_signals_status",
]


_EVENT_SCHEMA_NOT_FOUND = "Unknown event type {event}; see telec events list."
_EVENTS_LIST_SCHEMA_FOOTER = "Inspect declared fields with: telec events schema <event>"
_SCHEMA_EVENT_USAGE = "telec events schema <event>"
_UNKNOWN_EVENTS_SUBCOMMAND_TEMPLATE = "Unknown events subcommand: {subcommand}"
_UNEXPECTED_ARGUMENT_TEMPLATE = "Unexpected argument: {argument}"
_NO_EVENT_TYPES = "No event types found."
_EVENT_OWNER_SEPARATOR = "."
_ANY_SUBJECT_KIND = "any"
_NO_HOME = "none (belongs to no registered home)"
_LIST_HEADERS = ("EVENT TYPE", "VERSION", "ABOUT", "DESCRIPTION")
_LIST_COLUMN_WIDTHS = (55, 8, 18, 70)
_LIST_COLUMN_SEPARATOR = "  "
_SCHEMA_HEADER_TEMPLATE = "{name} — {description} (version: {version})"
_SCHEMA_SUBJECT_TEMPLATE = "Subject: {kind}"
_SCHEMA_HOME_TEMPLATE = "Home: {kinds}"
_SCHEMA_RELATED_TEMPLATE = "Related: {kinds}"
_SCHEMA_STATE_TEMPLATE = "State: {state} ({standing}) in family {family}"
_SCHEMA_FIELD_TEMPLATE = "{name}: {kind} (nullable: {nullable})"
_SCHEMA_FIELDS_EMPTY = "No data fields are declared."
_COMMA_SEPARATOR = ", "


def _build_default_catalog() -> EventCatalog:
    return cast(EventCatalog, importlib.import_module("teleclaude.events").build_default_catalog())


def _load_signal_runtime() -> tuple[Any, Any]:
    aiosqlite = importlib.import_module("aiosqlite")
    signal_db = importlib.import_module("teleclaude.events.signal.db").SignalDB
    return aiosqlite, signal_db


def _handle_events(args: list[str]) -> None:
    """Handle telec events subcommands."""
    if not args:
        print(_usage("events"))
        return

    subcommand = args[0]
    if subcommand == EventCommand.LIST.value:
        _handle_events_list(args[1:])
    elif subcommand == EventCommand.SCHEMA.value:
        _handle_events_schema(args[1:])
    else:
        print(_UNKNOWN_EVENTS_SUBCOMMAND_TEMPLATE.format(subcommand=subcommand))
        print(_usage("events"))
        raise SystemExit(1)


def _subject_kind_label(declaration: EventDeclaration) -> str:
    return declaration.subject_kind.value if declaration.subject_kind is not None else _ANY_SUBJECT_KIND


def _handle_events_list(args: list[str]) -> None:
    """List every declared event type, narrowed to one owner on request."""
    parsed = parse_command_args(EVENTS_LIST, args)
    if parsed.positionals:
        print(_UNEXPECTED_ARGUMENT_TEMPLATE.format(argument=parsed.positionals[0]))
        print(_usage("events", "list"))
        raise SystemExit(1)
    owner_filter = parsed.value(F.FLAG_EVENTS_DOMAIN)

    declarations = _build_default_catalog().list_all()
    if owner_filter:
        declarations = [d for d in declarations if d.name.split(_EVENT_OWNER_SEPARATOR, 1)[0] == owner_filter]

    if not declarations:
        print(_NO_EVENT_TYPES)
        return

    print(_LIST_COLUMN_SEPARATOR.join(h.ljust(w) for h, w in zip(_LIST_HEADERS, _LIST_COLUMN_WIDTHS, strict=True)))
    print("-" * (sum(_LIST_COLUMN_WIDTHS) + len(_LIST_COLUMN_SEPARATOR) * (len(_LIST_COLUMN_WIDTHS) - 1)))
    for declaration in declarations:
        cells = (declaration.name, str(declaration.version), _subject_kind_label(declaration), declaration.description)
        print(_LIST_COLUMN_SEPARATOR.join(cell.ljust(w) for cell, w in zip(cells, _LIST_COLUMN_WIDTHS, strict=True)))
    print()
    print(_EVENTS_LIST_SCHEMA_FOOTER)


def _handle_events_schema(args: list[str]) -> None:
    """Show the generated declaration for one event type."""
    parsed = parse_command_args(EVENTS_SCHEMA, args)
    if len(parsed.positionals) != 1:
        print(_SCHEMA_EVENT_USAGE, file=sys.stderr)
        raise SystemExit(1)
    event_type = parsed.positionals[0]
    declaration = _build_default_catalog().get(event_type)
    if declaration is None:
        print(_EVENT_SCHEMA_NOT_FOUND.format(event=event_type), file=sys.stderr)
        raise SystemExit(1)

    print(
        _SCHEMA_HEADER_TEMPLATE.format(
            name=declaration.name,
            description=declaration.description,
            version=declaration.version,
        )
    )
    print(_SCHEMA_SUBJECT_TEMPLATE.format(kind=_subject_kind_label(declaration)))
    home = _COMMA_SEPARATOR.join(kind.value for kind in declaration.home_kinds) or _NO_HOME
    print(_SCHEMA_HOME_TEMPLATE.format(kinds=home))
    print(
        _SCHEMA_RELATED_TEMPLATE.format(kinds=_COMMA_SEPARATOR.join(kind.value for kind in declaration.related_kinds))
    )
    if declaration.state is not None:
        print(
            _SCHEMA_STATE_TEMPLATE.format(
                state=declaration.state.state.value,
                standing=declaration.state.standing.value,
                family=declaration.state.family,
            )
        )
    if not declaration.data_fields:
        print(_SCHEMA_FIELDS_EMPTY)
        return
    for field in declaration.data_fields:
        print(_SCHEMA_FIELD_TEMPLATE.format(name=field.name, kind=field.kind.value, nullable=field.nullable))


def _handle_signals(args: list[str]) -> None:
    """Handle telec signals subcommands."""
    if not args or args[0] == "status":
        _handle_signals_status()
    else:
        print(f"Unknown signals subcommand: {args[0]}")
        print(_usage("signals"))
        raise SystemExit(1)


def _handle_signals_status() -> None:
    """Show signal pipeline item/cluster/synthesis counts and last ingest time."""

    async def _query() -> None:
        aiosqlite, signal_db = _load_signal_runtime()
        async with aiosqlite.connect(str(EVENTS_DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            sdb = signal_db(conn)
            db_error: type[Exception] = getattr(aiosqlite, "Error", RuntimeError)
            try:
                counts = await sdb.get_signal_counts()
                last_ingest = await sdb.get_last_ingest_time()
            except (db_error, OSError, RuntimeError, ValueError):
                print("Signal tables not initialized. Start the daemon to enable signal ingestion.")
                return

        print("Signal Pipeline Status")
        print("----------------------")
        print(f"Items ingested:  {counts['items']}")
        print(f"Clusters formed: {counts['clusters']}")
        print(f"Syntheses ready: {counts['syntheses']}")
        print(f"Pending cluster: {counts['pending']}")
        print(f"Last ingest:     {last_ingest or 'never'}")

    asyncio.run(_query())
