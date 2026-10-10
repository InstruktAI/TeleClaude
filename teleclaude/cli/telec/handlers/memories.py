"""Handlers for telec memories commands."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import NoReturn

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    MEMORIES_ADD,
    MEMORIES_ADVANCE,
    MEMORIES_DELETE,
    MEMORIES_LIST,
    MEMORIES_PROSPECT,
    MEMORIES_RETIRE,
    MEMORIES_SAVE,
    MEMORIES_SCOPE,
    MEMORIES_SEARCH,
    MEMORIES_TIMELINE,
    MEMORIES_UPDATE,
)
from teleclaude.memory.types import ObservationType

__all__ = [
    "_handle_memories",
    "_handle_memories_add",
    "_handle_memories_advance",
    "_handle_memories_delete",
    "_handle_memories_list",
    "_handle_memories_prospect",
    "_handle_memories_retire",
    "_handle_memories_save",
    "_handle_memories_scope",
    "_handle_memories_search",
    "_handle_memories_timeline",
    "_handle_memories_update",
]

_REQUEST_FAILURE_TEMPLATE = "Error: {detail}"
_SESSION_REQUIRED = "--session is required."
_TYPE_REQUIRED = "--type is required."
_TEXT_REQUIRED = "Text is required."
_MEMORY_ID_REQUIRED = "Memory ID is required."
_TO_REQUIRED = "--to is required."
_SCOPE_SESSION_TEMPLATE = "Session: {session_id}"
_SCOPE_PERSON_TEMPLATE = "Person: {person} (registered: {registered})"
_SCOPE_NAMESPACE_TEMPLATE = "Namespace: {namespace}"
_SCOPE_DESK_TEMPLATE = "Help-desk conversation: {desk} (home: {home})"
_SCOPE_READ_POINT_TEMPLATE = "Read point: {read_point}"
_SCOPE_HEADING_TEMPLATE = "{heading} ({count}):"
_SCOPE_ENTRY_TEMPLATE = "  #{id} [{type}] {text}"
_SCOPE_MEMORIES_HEADING = "Current memories"
_SCOPE_PROSPECTS_HEADING = "Prospects recorded from this session"
_ADDED_TEMPLATE = "Added memory #{id} — {title} (namespace: {namespace})"
_UPDATED_TEMPLATE = "Updated memory #{id}"
_RETIRED_TEMPLATE = "Retired memory #{id}"
_PROSPECT_TEMPLATE = "Recorded prospect #{id} for {namespace}"
_READ_POINT_TEMPLATE = "Read point: {read_point}"
_SCOPE_SESSION_KEY = "session_id"
_SCOPE_PERSON_KEY = "person"
_SCOPE_REGISTERED_KEY = "registered"
_SCOPE_NAMESPACE_KEY = "namespace"
_SCOPE_DESK_KEY = "desk"
_SCOPE_HOME_KEY = "home"
_SCOPE_READ_POINT_KEY = "read_point"
_SCOPE_MEMORIES_KEY = "memories"
_SCOPE_PROSPECTS_KEY = "prospects"
_ROW_ID_KEY = "id"
_ROW_TYPE_KEY = "type"
_ROW_TEXT_KEY = "text"
_RESULT_TITLE_KEY = "title"
_RESULT_PROJECT_KEY = "project"


def _fail_memories_request(exc: APIError) -> NoReturn:
    """Exit non-zero on a failed memories request; a daemon that did not accept it says how to run it again."""
    exc.exit_if_not_accepted()
    print(_REQUEST_FAILURE_TEMPLATE.format(detail=exc.detail))
    raise SystemExit(1) from exc


def _memories_usage_error(subcommand: str, message: str) -> NoReturn:
    """Print a memories subcommand usage error and exit."""
    print(message)
    print(_usage("memories", subcommand))
    raise SystemExit(1)


def _parse_observation_type(obs_type: str, subcommand: str) -> str:
    """Validate observation type values accepted by the memories API."""
    valid_types_set = {member.value for member in ObservationType}
    if obs_type not in valid_types_set:
        valid_types = ", ".join(sorted(valid_types_set))
        _memories_usage_error(subcommand, f"Invalid type '{obs_type}'. Valid types: {valid_types}")
    return obs_type


def _parse_integer_option(value: str, option: str, subcommand: str) -> int:
    """Parse a required integer option value."""
    try:
        return int(value)
    except ValueError:
        _memories_usage_error(subcommand, f"Invalid value for {option}: {value}")


def _parse_numeric_id(raw_id: str, subcommand: str) -> int:
    """Parse a numeric observation id."""
    try:
        return int(raw_id)
    except ValueError:
        _memories_usage_error(subcommand, f"Invalid ID '{raw_id}': must be a number.")


async def _memory_search(
    query: str, limit: int, obs_type: str | None, project: str | None
) -> list[dict[str, object]]:  # guard: loose-dict - JSON API response
    """Run a memory search request."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_search(query, limit=limit, obs_type=obs_type, project=project)
    finally:
        await api.close()


async def _memory_save(
    text: str, title: str | None, obs_type: str | None, project: str | None
) -> dict[str, object]:  # guard: loose-dict - JSON API response
    """Save a memory observation."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_save(text, title=title, obs_type=obs_type, project=project)
    finally:
        await api.close()


async def _memory_delete(obs_id: int) -> dict[str, object]:  # guard: loose-dict - JSON API response
    """Delete a memory observation."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_delete(obs_id)
    finally:
        await api.close()


async def _memory_timeline(
    anchor_id: int, before: int, after: int, project: str | None
) -> list[dict[str, object]]:  # guard: loose-dict - JSON API response
    """Load a timeline around an observation."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_timeline(anchor_id, before=before, after=after, project=project)
    finally:
        await api.close()


def _print_memory_table(
    results: list[dict[str, object]],  # guard: loose-dict - JSON API response
    heading: str,
    *,
    anchor_id: int | None = None,  # guard: loose-dict - dynamic payload
) -> None:  # guard: loose-dict - JSON API response
    """Render memory search or timeline rows in a shared table format."""
    print(heading)
    print(f"{'ID':>6} | {'Type':<12} | {'Project':<16} | {'Title':<40} | Snippet")
    print("-" * 110)
    for result in results:
        obs_id = str(result.get("id", ""))
        marker = ""
        if anchor_id is not None:
            try:
                marker = " ◀" if int(obs_id) == anchor_id else ""
            except (ValueError, TypeError):
                marker = ""
        obs_type = str(result.get("type", ""))
        project = str(result.get("project", ""))
        title = str(result.get("title", ""))[:40]
        narrative = str(result.get("narrative", "") or result.get("text", ""))[:60]
        print(f"{obs_id:>6} | {obs_type:<12} | {project:<16} | {title:<40} | {narrative}…{marker}")


def _parse_memories_list_args(args: list[str]) -> tuple[int, str | None, str | None]:
    """Parse `telec memories list` arguments."""
    parsed = parse_command_args(MEMORIES_LIST, args)
    if parsed.positionals:
        _memories_usage_error("list", f"Unexpected argument: {parsed.positionals[0]}")

    limit_raw = parsed.value(F.FLAG_MEMORIES_LIMIT)
    limit = _parse_integer_option(limit_raw, "--limit", "list") if limit_raw is not None else 50
    type_raw = parsed.value(F.FLAG_MEMORIES_TYPE)
    obs_type = _parse_observation_type(type_raw, "list") if type_raw is not None else None
    project = parsed.value(F.FLAG_PROJECT_FILTER)

    return limit, obs_type, project


def _parse_memories_search_args(args: list[str]) -> tuple[str, int, str | None, str | None]:
    """Parse `telec memories search` arguments."""
    parsed = parse_command_args(MEMORIES_SEARCH, args)
    query = " ".join(parsed.positionals)
    if not query:
        _memories_usage_error("search", "Query is required.")

    limit_raw = parsed.value(F.FLAG_LIMIT_20)
    limit = _parse_integer_option(limit_raw, "--limit", "search") if limit_raw is not None else 20
    type_raw = parsed.value(F.FLAG_MEMORIES_TYPE)
    obs_type = _parse_observation_type(type_raw, "search") if type_raw is not None else None
    project = parsed.value(F.FLAG_PROJECT_FILTER)

    return query, limit, obs_type, project


def _parse_memories_save_args(args: list[str]) -> tuple[str, str | None, str | None, str | None]:
    """Parse `telec memories save` arguments."""
    parsed = parse_command_args(MEMORIES_SAVE, args)
    text = " ".join(parsed.positionals)
    if not text:
        _memories_usage_error("save", "Text is required.")

    title = parsed.value(F.FLAG_MEMORIES_SAVE_TITLE)
    type_raw = parsed.value(F.FLAG_MEMORIES_SAVE_TYPE)
    obs_type = _parse_observation_type(type_raw, "save") if type_raw is not None else None
    project = parsed.value(F.FLAG_MEMORIES_SAVE_PROJECT)

    return text, title, obs_type, project


def _parse_memories_delete_args(args: list[str]) -> int:
    """Parse `telec memories delete` arguments."""
    parsed = parse_command_args(MEMORIES_DELETE, args)
    positionals = parsed.positionals
    if len(positionals) != 1:
        _memories_usage_error("delete", "Observation ID is required.")
    return _parse_numeric_id(positionals[0], "delete")


def _parse_memories_timeline_args(args: list[str]) -> tuple[int, int, int, str | None]:
    """Parse `telec memories timeline` arguments."""
    parsed = parse_command_args(MEMORIES_TIMELINE, args)
    positionals = parsed.positionals
    if len(positionals) != 1:
        _memories_usage_error("timeline", "Anchor ID is required.")
    anchor_id = _parse_numeric_id(positionals[0], "timeline")

    before_raw = parsed.value(F.FLAG_MEMORIES_BEFORE)
    before = _parse_integer_option(before_raw, "--before", "timeline") if before_raw is not None else 3
    after_raw = parsed.value(F.FLAG_MEMORIES_AFTER)
    after = _parse_integer_option(after_raw, "--after", "timeline") if after_raw is not None else 3
    project = parsed.value(F.FLAG_PROJECT_FILTER)

    return anchor_id, before, after, project


def _handle_memories(args: list[str]) -> None:
    """Handle telec memories commands."""
    if not args:
        print(_usage("memories"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("memories"))
        return

    subcommand = args[0]
    if subcommand == "list":
        _handle_memories_list(args[1:])
    elif subcommand == "search":
        _handle_memories_search(args[1:])
    elif subcommand == "save":
        _handle_memories_save(args[1:])
    elif subcommand == "delete":
        _handle_memories_delete(args[1:])
    elif subcommand == "timeline":
        _handle_memories_timeline(args[1:])
    elif subcommand == "scope":
        _handle_memories_scope(args[1:])
    elif subcommand == "add":
        _handle_memories_add(args[1:])
    elif subcommand == "update":
        _handle_memories_update(args[1:])
    elif subcommand == "retire":
        _handle_memories_retire(args[1:])
    elif subcommand == "prospect":
        _handle_memories_prospect(args[1:])
    elif subcommand == "advance":
        _handle_memories_advance(args[1:])
    else:
        print(f"Unknown memories subcommand: {subcommand}")
        print(_usage("memories"))
        raise SystemExit(1)


def _handle_memories_list(args: list[str]) -> None:
    """Handle telec memories list."""
    limit, obs_type, project = _parse_memories_list_args(args)

    try:
        results = asyncio.run(_memory_search("", limit, obs_type, project))
    except APIError as exc:
        _fail_memories_request(exc)

    if not results:
        print("No memories found.")
        return

    _print_memory_table(results, f"\nMemories ({len(results)} found):\n")


def _handle_memories_search(args: list[str]) -> None:
    """Handle telec memories search."""
    query, limit, obs_type, project = _parse_memories_search_args(args)

    try:
        results = asyncio.run(_memory_search(query, limit, obs_type, project))
    except APIError as exc:
        _fail_memories_request(exc)

    if not results:
        print(f"No memories found for '{query}'")
        return

    _print_memory_table(results, f"\nSearch results for '{query}' ({len(results)} found):\n")


def _handle_memories_save(args: list[str]) -> None:
    """Handle telec memories save."""
    text, title, obs_type, project = _parse_memories_save_args(args)

    try:
        result = asyncio.run(_memory_save(text, title, obs_type, project))
    except APIError as exc:
        _fail_memories_request(exc)

    print(f"Saved observation #{result.get('id')} — {result.get('title')} (project: {result.get('project')})")


def _handle_memories_delete(args: list[str]) -> None:
    """Handle telec memories delete."""
    numeric_id = _parse_memories_delete_args(args)

    try:
        asyncio.run(_memory_delete(numeric_id))
    except APIError as exc:
        _fail_memories_request(exc)

    print(f"Deleted observation #{numeric_id}")


def _handle_memories_timeline(args: list[str]) -> None:
    """Handle telec memories timeline."""
    numeric_anchor, before, after, project = _parse_memories_timeline_args(args)

    try:
        results = asyncio.run(_memory_timeline(numeric_anchor, before, after, project))
    except APIError as exc:
        _fail_memories_request(exc)

    if not results:
        print(f"No observations found around #{numeric_anchor}")
        return

    _print_memory_table(
        results,
        f"\nTimeline around observation #{numeric_anchor}:\n",
        anchor_id=numeric_anchor,
    )


def _curation_session(parsed_session: str | None, subcommand: str) -> str:
    """The conversation session a curation verb names."""
    if not parsed_session:
        _memories_usage_error(subcommand, _SESSION_REQUIRED)
    return parsed_session


def _curation_text(positionals: Sequence[str], subcommand: str) -> str:
    """The statement a curation verb carries."""
    text = " ".join(positionals)
    if not text:
        _memories_usage_error(subcommand, _TEXT_REQUIRED)
    return text


def _curation_type(parsed_type: str | None, subcommand: str) -> str:
    """The observation type a curation verb records."""
    if not parsed_type:
        _memories_usage_error(subcommand, _TYPE_REQUIRED)
    return _parse_observation_type(parsed_type, subcommand)


async def _curation_request(
    call: Callable[[TelecAPIClient], Awaitable[dict[str, object]]],  # guard: loose-dict - JSON API response
) -> dict[str, object]:  # guard: loose-dict - JSON API response
    """Run one curation request against the daemon."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await call(api)
    finally:
        await api.close()


def _run_curation(
    call: Callable[[TelecAPIClient], Awaitable[dict[str, object]]],  # guard: loose-dict - JSON API response
) -> dict[str, object]:  # guard: loose-dict - JSON API response
    """Run a curation request, exiting non-zero on a refusal."""
    try:
        return asyncio.run(_curation_request(call))
    except APIError as exc:
        _fail_memories_request(exc)


def _print_scope_entries(heading: str, entries: object) -> None:
    """Print a scope's memories or prospects, one per line."""
    rows = entries if isinstance(entries, list) else []
    print(_SCOPE_HEADING_TEMPLATE.format(heading=heading, count=len(rows)))
    for row in rows:
        if isinstance(row, dict):
            print(
                _SCOPE_ENTRY_TEMPLATE.format(
                    id=row.get(_ROW_ID_KEY), type=row.get(_ROW_TYPE_KEY), text=row.get(_ROW_TEXT_KEY)
                )
            )


def _handle_memories_scope(args: list[str]) -> None:
    """Handle telec memories scope."""
    parsed = parse_command_args(MEMORIES_SCOPE, args)
    session_id = _curation_session(parsed.value(F.FLAG_MEMORIES_CURATION_SESSION), "scope")
    scope = _run_curation(lambda api: api.memory_curation_scope(session_id))
    print(_SCOPE_SESSION_TEMPLATE.format(session_id=scope.get(_SCOPE_SESSION_KEY)))
    print(
        _SCOPE_PERSON_TEMPLATE.format(person=scope.get(_SCOPE_PERSON_KEY), registered=scope.get(_SCOPE_REGISTERED_KEY))
    )
    print(_SCOPE_NAMESPACE_TEMPLATE.format(namespace=scope.get(_SCOPE_NAMESPACE_KEY)))
    print(_SCOPE_DESK_TEMPLATE.format(desk=scope.get(_SCOPE_DESK_KEY), home=scope.get(_SCOPE_HOME_KEY)))
    print(_SCOPE_READ_POINT_TEMPLATE.format(read_point=scope.get(_SCOPE_READ_POINT_KEY)))
    _print_scope_entries(_SCOPE_MEMORIES_HEADING, scope.get(_SCOPE_MEMORIES_KEY))
    if scope.get(_SCOPE_DESK_KEY):
        _print_scope_entries(_SCOPE_PROSPECTS_HEADING, scope.get(_SCOPE_PROSPECTS_KEY))


def _handle_memories_add(args: list[str]) -> None:
    """Handle telec memories add."""
    parsed = parse_command_args(MEMORIES_ADD, args)
    session_id = _curation_session(parsed.value(F.FLAG_MEMORIES_CURATION_SESSION), "add")
    obs_type = _curation_type(parsed.value(F.FLAG_MEMORIES_CURATION_TYPE), "add")
    text = _curation_text(parsed.positionals, "add")
    result = _run_curation(lambda api: api.memory_curation_add(session_id, obs_type, text))
    print(
        _ADDED_TEMPLATE.format(
            id=result.get(_ROW_ID_KEY), title=result.get(_RESULT_TITLE_KEY), namespace=result.get(_RESULT_PROJECT_KEY)
        )
    )


def _handle_memories_update(args: list[str]) -> None:
    """Handle telec memories update."""
    parsed = parse_command_args(MEMORIES_UPDATE, args)
    session_id = _curation_session(parsed.value(F.FLAG_MEMORIES_CURATION_SESSION), "update")
    if not parsed.positionals:
        _memories_usage_error("update", _MEMORY_ID_REQUIRED)
    observation_id = _parse_numeric_id(parsed.positionals[0], "update")
    text = _curation_text(parsed.positionals[1:], "update")
    _run_curation(lambda api: api.memory_curation_update(session_id, observation_id, text))
    print(_UPDATED_TEMPLATE.format(id=observation_id))


def _handle_memories_retire(args: list[str]) -> None:
    """Handle telec memories retire."""
    parsed = parse_command_args(MEMORIES_RETIRE, args)
    session_id = _curation_session(parsed.value(F.FLAG_MEMORIES_CURATION_SESSION), "retire")
    if len(parsed.positionals) != 1:
        _memories_usage_error("retire", _MEMORY_ID_REQUIRED)
    observation_id = _parse_numeric_id(parsed.positionals[0], "retire")
    _run_curation(lambda api: api.memory_curation_retire(session_id, observation_id))
    print(_RETIRED_TEMPLATE.format(id=observation_id))


def _handle_memories_prospect(args: list[str]) -> None:
    """Handle telec memories prospect."""
    parsed = parse_command_args(MEMORIES_PROSPECT, args)
    session_id = _curation_session(parsed.value(F.FLAG_MEMORIES_CURATION_SESSION), "prospect")
    obs_type = _curation_type(parsed.value(F.FLAG_MEMORIES_CURATION_TYPE), "prospect")
    text = _curation_text(parsed.positionals, "prospect")
    result = _run_curation(lambda api: api.memory_curation_prospect(session_id, obs_type, text))
    print(_PROSPECT_TEMPLATE.format(id=result.get(_ROW_ID_KEY), namespace=result.get(_RESULT_PROJECT_KEY)))


def _handle_memories_advance(args: list[str]) -> None:
    """Handle telec memories advance."""
    parsed = parse_command_args(MEMORIES_ADVANCE, args)
    session_id = _curation_session(parsed.value(F.FLAG_MEMORIES_CURATION_SESSION), "advance")
    newest_entry_read = parsed.value(F.FLAG_MEMORIES_ADVANCE_TO)
    if not newest_entry_read:
        _memories_usage_error("advance", _TO_REQUIRED)
    result = _run_curation(lambda api: api.memory_curation_advance(session_id, newest_entry_read))
    print(_READ_POINT_TEMPLATE.format(read_point=result.get(_SCOPE_READ_POINT_KEY)))
