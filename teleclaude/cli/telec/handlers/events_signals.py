"""Handlers for telec events and signals commands."""

from __future__ import annotations

import asyncio
import importlib
import json
import math
import sys
from typing import Any, NoReturn, cast

from pydantic import JsonValue

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    EVENTS_LIST,
    EVENTS_SCHEMA,
    EVENTS_SUBSCRIBE,
    EVENTS_SUBSCRIPTIONS,
    EVENTS_UNSUBSCRIBE,
    EventCommand,
)
from teleclaude.cli.tool_client import print_json
from teleclaude.cli.tool_commands.event_subscriptions import (
    EventSubscriptionRequestBody,
    list_subscriptions,
    subscribe,
    unsubscribe,
)
from teleclaude.events.catalog import EventCatalog, EventSchema, PayloadField, PayloadValueKind
from teleclaude.paths import EVENTS_DB_PATH

__all__ = [
    "_handle_events",
    "_handle_events_list",
    "_handle_signals",
    "_handle_signals_status",
]


_EQUALS = "="
_TRUE_VALUE = "true"
_FALSE_VALUE = "false"
_JSON_NULL = "null"
_EVENT_SCHEMA_NOT_FOUND = "Unknown event type {event}; see telec events list."
_EVENT_FIELD_NOT_FOUND = "Event {event} has no declared payload field {field}; see telec events schema {event}."
_EVENTS_LIST_SUBSCRIBE_FOOTER = "Subscribe with: telec events subscribe <event> [--once] [--where <field>=<value>]"
_EVENTS_LIST_SCHEMA_FOOTER = "Inspect declared fields with: telec events schema <event>"
_SCHEMA_EVENT_USAGE = "telec events schema <event>"
_SUBSCRIBE_USAGE = "telec events subscribe <event> [--once] [--where <field>=<value>]..."
_SUBSCRIPTIONS_USAGE = "telec events subscriptions"
_UNSUBSCRIBE_USAGE = "telec events unsubscribe <subscription-id>"
_UNEXPECTED_ARGUMENT = "Unexpected argument: {argument}"
_UNKNOWN_EVENTS_SUBCOMMAND_TEMPLATE = "Unknown events subcommand: {subcommand}"
_MALFORMED_NARROWING = "Invalid --where value {value}; expected <field>=<value>."
_DUPLICATE_NARROWING = "Field {field} was narrowed more than once."
_UNPARSEABLE_NARROWING = "Value for field {field} is not a valid {kind}; expected {form}."
_NULL_NOT_ALLOWED = "Null is not allowed for field {field}."
_JSON_PARSE_CONSTANT_ERROR = "non-standard JSON numeric constant"
_SCHEMA_HEADER_TEMPLATE = "{event_type} — {description} (level: {level}; domain: {domain}; visibility: {visibility}; actionable: {actionable})"
_SCHEMA_ASSIGNMENT_TEMPLATE = "Subject assignment ({kinds}): {about}"
_SCHEMA_FIELD_TEMPLATE = "{name}: {kind} (nullable: {nullable}); {form}"
_SCHEMA_FIELDS_EMPTY = "No payload fields are declared."
_COMMA_SEPARATOR = ", "
_KIND_INPUT_FORMS: dict[PayloadValueKind, str] = {
    PayloadValueKind.STRING: "write text as-is",
    PayloadValueKind.INTEGER: "write a JSON integer",
    PayloadValueKind.NUMBER: "write a JSON number",
    PayloadValueKind.BOOLEAN: "write true or false",
    PayloadValueKind.ARRAY: "write a JSON array",
    PayloadValueKind.OBJECT: "write a JSON object",
    PayloadValueKind.ANY: "write any JSON value; strings must be JSON-quoted",
}


def _reject_json_constant(value: str) -> NoReturn:
    del value
    raise ValueError(_JSON_PARSE_CONSTANT_ERROR)


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
    elif subcommand == EventCommand.SUBSCRIBE.value:
        _handle_events_subscribe(args[1:])
    elif subcommand == EventCommand.SUBSCRIPTIONS.value:
        _handle_events_subscriptions(args[1:])
    elif subcommand == EventCommand.UNSUBSCRIBE.value:
        _handle_events_unsubscribe(args[1:])
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
    print(_EVENTS_LIST_SUBSCRIBE_FOOTER)
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
                form=_KIND_INPUT_FORMS[field.kind],
            )
        )


def _handle_events_subscribe(args: list[str]) -> None:
    """Validate declared event fields and create a caller-session subscription."""
    parsed = parse_command_args(EVENTS_SUBSCRIBE, args)
    if len(parsed.positionals) != 1:
        print(_SUBSCRIBE_USAGE, file=sys.stderr)
        raise SystemExit(1)
    event_type = parsed.positionals[0]
    schema = _build_default_catalog().get(event_type)
    if schema is None:
        print(_EVENT_SCHEMA_NOT_FOUND.format(event=event_type), file=sys.stderr)
        raise SystemExit(1)

    narrowing = _parse_narrowing(parsed.values(F.FLAG_EVENTS_WHERE), schema)
    request = EventSubscriptionRequestBody(
        event_type=event_type,
        once=parsed.has(F.FLAG_EVENTS_ONCE),
        narrowing=narrowing,
    )
    response = subscribe(request)
    print_json(response)


def _parse_narrowing(values: tuple[str, ...], schema: EventSchema) -> dict[str, JsonValue]:
    """Parse repeatable field filters against the event's declared value kinds."""
    declared_fields = {field.name: field for field in schema.payload_fields}
    narrowing: dict[str, JsonValue] = {}
    for value in values:
        field_name, separator, raw_value = value.partition(_EQUALS)
        if not separator or not field_name:
            print(_MALFORMED_NARROWING.format(value=value), file=sys.stderr)
            raise SystemExit(1)
        field = declared_fields.get(field_name)
        if field is None:
            print(_EVENT_FIELD_NOT_FOUND.format(event=schema.event_type, field=field_name), file=sys.stderr)
            raise SystemExit(1)
        if field_name in narrowing:
            print(_DUPLICATE_NARROWING.format(field=field_name), file=sys.stderr)
            raise SystemExit(1)
        narrowing[field_name] = _parse_declared_value(raw_value, field)
    return narrowing


def _parse_declared_value(value: str, field: PayloadField) -> JsonValue:
    """Parse one narrowing according to its registry-declared JSON kind."""
    kind = field.kind
    if value == _JSON_NULL:
        if field.nullable:
            return None
        print(_NULL_NOT_ALLOWED.format(field=field.name), file=sys.stderr)
        raise SystemExit(1)
    if kind is PayloadValueKind.STRING:
        return value
    if kind is PayloadValueKind.BOOLEAN:
        if value == _TRUE_VALUE:
            return True
        if value == _FALSE_VALUE:
            return False
        _raise_narrowing_error(field)

    try:
        parsed_value: JsonValue = json.loads(value, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        _raise_narrowing_error(field)

    if parsed_value is None:
        if field.nullable:
            return parsed_value
        print(_NULL_NOT_ALLOWED.format(field=field.name), file=sys.stderr)
        raise SystemExit(1)
    if kind is PayloadValueKind.INTEGER and type(parsed_value) is int:
        return parsed_value
    if kind is PayloadValueKind.NUMBER:
        if isinstance(parsed_value, int) and not isinstance(parsed_value, bool):
            return parsed_value
        if isinstance(parsed_value, float) and math.isfinite(parsed_value):
            return parsed_value
    if kind is PayloadValueKind.ARRAY and isinstance(parsed_value, list):
        return parsed_value
    if kind is PayloadValueKind.OBJECT and isinstance(parsed_value, dict):
        return parsed_value
    if kind is PayloadValueKind.ANY:
        return parsed_value
    _raise_narrowing_error(field)


def _raise_narrowing_error(field: PayloadField) -> NoReturn:
    """Refuse a value that does not match its declared JSON kind."""
    print(
        _UNPARSEABLE_NARROWING.format(
            field=field.name,
            kind=field.kind.value,
            form=_KIND_INPUT_FORMS[field.kind],
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)


def _handle_events_subscriptions(args: list[str]) -> None:
    """List the caller session's own live subscriptions."""
    parsed = parse_command_args(EVENTS_SUBSCRIPTIONS, args)
    if parsed.positionals:
        print(_UNEXPECTED_ARGUMENT.format(argument=parsed.positionals[0]), file=sys.stderr)
        raise SystemExit(1)
    print_json(list_subscriptions())


def _handle_events_unsubscribe(args: list[str]) -> None:
    """Withdraw one caller-owned event subscription."""
    parsed = parse_command_args(EVENTS_UNSUBSCRIBE, args)
    if len(parsed.positionals) != 1:
        print(_UNSUBSCRIBE_USAGE, file=sys.stderr)
        raise SystemExit(1)
    print_json(unsubscribe(parsed.positionals[0]))


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
