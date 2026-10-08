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
from teleclaude.events.catalog import EventCatalog
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
_SCHEMA_HEADER_TEMPLATE = "{event_type} — {description} (level: {level}; domain: {domain}; visibility: {visibility}; actionable: {actionable})"
_SCHEMA_ASSIGNMENT_TEMPLATE = "Subject assignment ({kinds}): {about}"
_SCHEMA_FIELD_TEMPLATE = "{name}: {kind} (nullable: {nullable})"
_SCHEMA_FIELDS_EMPTY = "No payload fields are declared."
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


def _handle_events_list(args: list[str]) -> None:
    """List all registered event schemas."""
    parsed = parse_command_args(EVENTS_LIST, args)
    if parsed.positionals:
        print(f"Unexpected argument: {parsed.positionals[0]}")
        print(_usage("events", "list"))
        raise SystemExit(1)
    domain_filter = parsed.value(F.FLAG_EVENTS_DOMAIN)

    catalog = _build_default_catalog()
    schemas = catalog.list_all()
    if domain_filter:
        schemas = [s for s in schemas if s.domain == domain_filter]

    if not schemas:
        print("No event schemas found.")
        return

    col_widths = [55, 8, 24, 8, 50, 12]
    headers = ["EVENT TYPE", "LEVEL", "DOMAIN", "VISIBLE", "DESCRIPTION", "ACTIONABLE"]
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_row)
    print("-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))
    for s in schemas:
        row = "  ".join(
            [
                str(s.event_type).ljust(col_widths[0]),
                str(s.default_level).ljust(col_widths[1]),
                str(s.domain).ljust(col_widths[2]),
                str(s.default_visibility.value).ljust(col_widths[3]),
                str(s.description).ljust(col_widths[4]),
                ("yes" if s.actionable else "no").ljust(col_widths[5]),
            ]
        )
        print(row)
    print()
    print(_EVENTS_LIST_SCHEMA_FOOTER)


def _handle_events_schema(args: list[str]) -> None:
    """Show the registry declaration for one event type."""
    parsed = parse_command_args(EVENTS_SCHEMA, args)
    if len(parsed.positionals) != 1:
        print(_SCHEMA_EVENT_USAGE, file=sys.stderr)
        raise SystemExit(1)
    event_type = parsed.positionals[0]
    schema = _build_default_catalog().get(event_type)
    if schema is None:
        print(_EVENT_SCHEMA_NOT_FOUND.format(event=event_type), file=sys.stderr)
        raise SystemExit(1)

    print(
        _SCHEMA_HEADER_TEMPLATE.format(
            event_type=schema.event_type,
            description=schema.description,
            level=schema.default_level,
            domain=schema.domain,
            visibility=schema.default_visibility.value,
            actionable=schema.actionable,
        )
    )
    print(
        _SCHEMA_ASSIGNMENT_TEMPLATE.format(
            kinds=_COMMA_SEPARATOR.join(kind.value for kind in schema.subject_assignment.kinds),
            about=schema.subject_assignment.about,
        )
    )
    if not schema.payload_fields:
        print(_SCHEMA_FIELDS_EMPTY)
        return
    for field in schema.payload_fields:
        print(
            _SCHEMA_FIELD_TEMPLATE.format(
                name=field.name,
                kind=field.kind.value,
                nullable=field.nullable,
            )
        )


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
