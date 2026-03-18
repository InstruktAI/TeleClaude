"""Handlers for telec memories commands."""

from __future__ import annotations

import asyncio

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.telec.help import _usage

__all__ = [
    "_VALID_OBS_TYPES",
    "_handle_memories",
    "_handle_memories_delete",
    "_handle_memories_save",
    "_handle_memories_search",
    "_handle_memories_timeline",
]

_VALID_OBS_TYPES = {"preference", "decision", "discovery", "gotcha", "pattern", "friction", "context"}


def _memories_usage_error(subcommand: str, message: str) -> None:
    """Print a memories subcommand usage error and exit."""
    print(message)
    print(_usage("memories", subcommand))
    raise SystemExit(1)


def _read_memories_option_value(args: list[str], index: int, option: str, subcommand: str) -> tuple[str, int]:
    """Read an option value or exit with the subcommand usage."""
    if index + 1 >= len(args):
        _memories_usage_error(subcommand, f"Missing value for {option}.")
    return args[index + 1], index + 2


def _parse_observation_type(obs_type: str) -> str:
    """Validate observation type values accepted by the memories API."""
    if obs_type not in _VALID_OBS_TYPES:
        valid_types = ", ".join(sorted(_VALID_OBS_TYPES))
        print(f"Invalid type '{obs_type}'. Valid types: {valid_types}")
        raise SystemExit(1)
    return obs_type


def _parse_integer_option(value: str, option: str) -> int:
    """Parse a required integer option value."""
    try:
        return int(value)
    except ValueError as exc:
        print(f"Invalid value for {option}: {value}")
        raise SystemExit(1) from exc


def _parse_numeric_id(raw_id: str) -> int:
    """Parse a numeric observation id."""
    try:
        return int(raw_id)
    except ValueError as exc:
        print(f"Invalid ID '{raw_id}': must be a number.")
        raise SystemExit(1) from exc


async def _memory_search(query: str, limit: int, obs_type: str | None, project: str | None) -> list[dict[str, object]]:
    """Run a memory search request."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_search(query, limit=limit, obs_type=obs_type, project=project)
    finally:
        await api.close()


async def _memory_save(text: str, title: str | None, obs_type: str | None, project: str | None) -> dict[str, object]:
    """Save a memory observation."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_save(text, title=title, obs_type=obs_type, project=project)
    finally:
        await api.close()


async def _memory_delete(obs_id: int) -> dict[str, object]:
    """Delete a memory observation."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_delete(obs_id)
    finally:
        await api.close()


async def _memory_timeline(anchor_id: int, before: int, after: int, project: str | None) -> list[dict[str, object]]:
    """Load a timeline around an observation."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.memory_timeline(anchor_id, before=before, after=after, project=project)
    finally:
        await api.close()


def _print_memory_table(results: list[dict[str, object]], heading: str, *, anchor_id: int | None = None) -> None:
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


def _parse_memories_search_args(args: list[str]) -> tuple[str, int, str | None, str | None] | None:
    """Parse `telec memories search` arguments."""
    limit = 20
    obs_type: str | None = None
    project: str | None = None
    query_parts: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("memories", "search"))
            return None
        if arg == "--limit":
            value, i = _read_memories_option_value(args, i, "--limit", "search")
            limit = _parse_integer_option(value, "--limit")
            continue
        if arg == "--type":
            value, i = _read_memories_option_value(args, i, "--type", "search")
            obs_type = _parse_observation_type(value)
            continue
        if arg == "--project":
            project, i = _read_memories_option_value(args, i, "--project", "search")
            continue
        if arg.startswith("-"):
            _memories_usage_error("search", f"Unknown option: {arg}")
        query_parts.append(arg)
        i += 1

    if not query_parts:
        _memories_usage_error("search", "Query is required.")

    return " ".join(query_parts), limit, obs_type, project


def _parse_memories_save_args(args: list[str]) -> tuple[str, str | None, str | None, str | None] | None:
    """Parse `telec memories save` arguments."""
    title: str | None = None
    obs_type: str | None = None
    project: str | None = None
    text_parts: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("memories", "save"))
            return None
        if arg == "--title":
            title, i = _read_memories_option_value(args, i, "--title", "save")
            continue
        if arg == "--type":
            value, i = _read_memories_option_value(args, i, "--type", "save")
            obs_type = _parse_observation_type(value)
            continue
        if arg == "--project":
            project, i = _read_memories_option_value(args, i, "--project", "save")
            continue
        if arg.startswith("-"):
            _memories_usage_error("save", f"Unknown option: {arg}")
        text_parts.append(arg)
        i += 1

    if not text_parts:
        _memories_usage_error("save", "Text is required.")

    return " ".join(text_parts), title, obs_type, project


def _parse_memories_delete_args(args: list[str]) -> int | None:
    """Parse `telec memories delete` arguments."""
    if not args:
        _memories_usage_error("delete", "Observation ID is required.")

    if args[0] in ("-h", "--help"):
        print(_usage("memories", "delete"))
        return None

    for extra_arg in args[1:]:
        if extra_arg.startswith("-"):
            _memories_usage_error("delete", f"Unknown option: {extra_arg}")
        _memories_usage_error("delete", f"Unexpected argument: {extra_arg}")

    obs_id = args[0]
    if obs_id.startswith("-"):
        _memories_usage_error("delete", f"Unknown option: {obs_id}")
    return _parse_numeric_id(obs_id)


def _parse_memories_timeline_args(args: list[str]) -> tuple[int, int, int, str | None] | None:
    """Parse `telec memories timeline` arguments."""
    before = 3
    after = 3
    project: str | None = None
    anchor_id: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("memories", "timeline"))
            return None
        if arg == "--before":
            value, i = _read_memories_option_value(args, i, "--before", "timeline")
            before = _parse_integer_option(value, "--before")
            continue
        if arg == "--after":
            value, i = _read_memories_option_value(args, i, "--after", "timeline")
            after = _parse_integer_option(value, "--after")
            continue
        if arg == "--project":
            project, i = _read_memories_option_value(args, i, "--project", "timeline")
            continue
        if arg.startswith("-"):
            _memories_usage_error("timeline", f"Unknown option: {arg}")
        if anchor_id is not None:
            _memories_usage_error("timeline", f"Unexpected argument: {arg}")
        anchor_id = arg
        i += 1

    if not anchor_id:
        _memories_usage_error("timeline", "Anchor ID is required.")

    return _parse_numeric_id(anchor_id), before, after, project


def _handle_memories(args: list[str]) -> None:
    """Handle telec memories commands."""
    if not args:
        print(_usage("memories"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("memories"))
        return

    subcommand = args[0]
    if subcommand == "search":
        _handle_memories_search(args[1:])
    elif subcommand == "save":
        _handle_memories_save(args[1:])
    elif subcommand == "delete":
        _handle_memories_delete(args[1:])
    elif subcommand == "timeline":
        _handle_memories_timeline(args[1:])
    else:
        print(f"Unknown memories subcommand: {subcommand}")
        print(_usage("memories"))
        raise SystemExit(1)


def _handle_memories_search(args: list[str]) -> None:
    """Handle telec memories search."""
    parsed = _parse_memories_search_args(args)
    if parsed is None:
        return
    query, limit, obs_type, project = parsed

    try:
        results = asyncio.run(_memory_search(query, limit, obs_type, project))
    except APIError as exc:
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

    if not results:
        print(f"No memories found for '{query}'")
        return

    _print_memory_table(results, f"\nSearch results for '{query}' ({len(results)} found):\n")


def _handle_memories_save(args: list[str]) -> None:
    """Handle telec memories save."""
    parsed = _parse_memories_save_args(args)
    if parsed is None:
        return
    text, title, obs_type, project = parsed

    try:
        result = asyncio.run(_memory_save(text, title, obs_type, project))
    except APIError as exc:
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

    print(f"Saved observation #{result.get('id')} — {result.get('title')} (project: {result.get('project')})")


def _handle_memories_delete(args: list[str]) -> None:
    """Handle telec memories delete."""
    numeric_id = _parse_memories_delete_args(args)
    if numeric_id is None:
        return

    try:
        asyncio.run(_memory_delete(numeric_id))
    except APIError as exc:
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

    print(f"Deleted observation #{numeric_id}")


def _handle_memories_timeline(args: list[str]) -> None:
    """Handle telec memories timeline."""
    parsed = _parse_memories_timeline_args(args)
    if parsed is None:
        return
    numeric_anchor, before, after, project = parsed

    try:
        results = asyncio.run(_memory_timeline(numeric_anchor, before, after, project))
    except APIError as exc:
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

    if not results:
        print(f"No observations found around #{numeric_anchor}")
        return

    _print_memory_table(
        results,
        f"\nTimeline around observation #{numeric_anchor}:\n",
        anchor_id=numeric_anchor,
    )
