"""Handlers for telec memories commands."""

from __future__ import annotations

import asyncio
from typing import NoReturn

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    MEMORIES_DELETE,
    MEMORIES_LIST,
    MEMORIES_SAVE,
    MEMORIES_SEARCH,
    MEMORIES_TIMELINE,
)

__all__ = [
    "_VALID_OBS_TYPES",
    "_handle_memories",
    "_handle_memories_delete",
    "_handle_memories_list",
    "_handle_memories_save",
    "_handle_memories_search",
    "_handle_memories_timeline",
]

_VALID_OBS_TYPES = {"preference", "decision", "discovery", "gotcha", "pattern", "friction", "context"}


def _memories_usage_error(subcommand: str, message: str) -> NoReturn:
    """Print a memories subcommand usage error and exit."""
    print(message)
    print(_usage("memories", subcommand))
    raise SystemExit(1)


def _parse_observation_type(obs_type: str, subcommand: str) -> str:
    """Validate observation type values accepted by the memories API."""
    if obs_type not in _VALID_OBS_TYPES:
        valid_types = ", ".join(sorted(_VALID_OBS_TYPES))
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
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

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
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

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
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

    print(f"Saved observation #{result.get('id')} — {result.get('title')} (project: {result.get('project')})")


def _handle_memories_delete(args: list[str]) -> None:
    """Handle telec memories delete."""
    numeric_id = _parse_memories_delete_args(args)

    try:
        asyncio.run(_memory_delete(numeric_id))
    except APIError as exc:
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc

    print(f"Deleted observation #{numeric_id}")


def _handle_memories_timeline(args: list[str]) -> None:
    """Handle telec memories timeline."""
    numeric_anchor, before, after, project = _parse_memories_timeline_args(args)

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
