"""Handlers for telec memories commands."""
from __future__ import annotations

import asyncio

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.telec.help import _usage


__all__ = [
    "_handle_memories",
    "_handle_memories_search",
    "_handle_memories_save",
    "_handle_memories_delete",
    "_handle_memories_timeline",
    "_VALID_OBS_TYPES",
]

_VALID_OBS_TYPES = {"preference", "decision", "discovery", "gotcha", "pattern", "friction", "context"}


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
    limit = 20
    obs_type: str | None = None
    project: str | None = None
    query: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("memories", "search"))
            return
        elif arg == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print(f"Invalid value for --limit: {args[i + 1]}")
                raise SystemExit(1)
            i += 2
        elif arg == "--limit":
            print("Missing value for --limit.")
            print(_usage("memories", "search"))
            raise SystemExit(1)
        elif arg == "--type" and i + 1 < len(args):
            obs_type = args[i + 1]
            if obs_type not in _VALID_OBS_TYPES:
                print(f"Invalid type '{obs_type}'. Valid types: {', '.join(sorted(_VALID_OBS_TYPES))}")
                raise SystemExit(1)
            i += 2
        elif arg == "--type":
            print("Missing value for --type.")
            print(_usage("memories", "search"))
            raise SystemExit(1)
        elif arg == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif arg == "--project":
            print("Missing value for --project.")
            print(_usage("memories", "search"))
            raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("memories", "search"))
            raise SystemExit(1)
        else:
            if query is None:
                query = arg
            else:
                query = f"{query} {arg}"
            i += 1

    if not query:
        print("Query is required.")
        print(_usage("memories", "search"))
        raise SystemExit(1)

    async def _search() -> list[dict[str, object]]:  # guard: loose-dict - JSON response from daemon memory API
        api = TelecAPIClient()
        await api.connect()
        try:
            return await api.memory_search(query, limit=limit, obs_type=obs_type, project=project)  # type: ignore[arg-type]
        finally:
            await api.close()

    try:
        results = asyncio.run(_search())
    except APIError as e:
        print(f"Error: {e.detail}")
        raise SystemExit(1)

    if not results:
        print(f"No memories found for '{query}'")
        return

    print(f"\nSearch results for '{query}' ({len(results)} found):\n")
    print(f"{'ID':>6} | {'Type':<12} | {'Project':<16} | {'Title':<40} | Snippet")
    print("-" * 110)
    for r in results:
        obs_id = str(r.get("id", ""))
        r_type = str(r.get("type", ""))
        r_project = str(r.get("project", ""))
        r_title = str(r.get("title", ""))[:40]
        narrative = str(r.get("narrative", "") or r.get("text", ""))[:60]
        print(f"{obs_id:>6} | {r_type:<12} | {r_project:<16} | {r_title:<40} | {narrative}…")


def _handle_memories_save(args: list[str]) -> None:
    """Handle telec memories save."""
    title: str | None = None
    obs_type: str | None = None
    project: str | None = None
    text: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("memories", "save"))
            return
        elif arg == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif arg == "--title":
            print("Missing value for --title.")
            print(_usage("memories", "save"))
            raise SystemExit(1)
        elif arg == "--type" and i + 1 < len(args):
            obs_type = args[i + 1]
            if obs_type not in _VALID_OBS_TYPES:
                print(f"Invalid type '{obs_type}'. Valid types: {', '.join(sorted(_VALID_OBS_TYPES))}")
                raise SystemExit(1)
            i += 2
        elif arg == "--type":
            print("Missing value for --type.")
            print(_usage("memories", "save"))
            raise SystemExit(1)
        elif arg == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif arg == "--project":
            print("Missing value for --project.")
            print(_usage("memories", "save"))
            raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("memories", "save"))
            raise SystemExit(1)
        else:
            if text is None:
                text = arg
            else:
                text = f"{text} {arg}"
            i += 1

    if not text:
        print("Text is required.")
        print(_usage("memories", "save"))
        raise SystemExit(1)

    async def _save() -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        api = TelecAPIClient()
        await api.connect()
        try:
            return await api.memory_save(text, title=title, obs_type=obs_type, project=project)  # type: ignore[arg-type]
        finally:
            await api.close()

    try:
        result = asyncio.run(_save())
    except APIError as e:
        print(f"Error: {e.detail}")
        raise SystemExit(1)

    print(f"Saved observation #{result.get('id')} — {result.get('title')} (project: {result.get('project')})")


def _handle_memories_delete(args: list[str]) -> None:
    """Handle telec memories delete."""
    obs_id: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("memories", "delete"))
            return
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("memories", "delete"))
            raise SystemExit(1)
        else:
            if obs_id is None:
                obs_id = arg
            else:
                print(f"Unexpected argument: {arg}")
                print(_usage("memories", "delete"))
                raise SystemExit(1)
            i += 1

    if not obs_id:
        print("Observation ID is required.")
        print(_usage("memories", "delete"))
        raise SystemExit(1)

    try:
        numeric_id = int(obs_id)
    except ValueError:
        print(f"Invalid ID '{obs_id}': must be a number.")
        raise SystemExit(1)

    async def _delete() -> dict[str, object]:  # guard: loose-dict - JSON response from daemon memory API
        api = TelecAPIClient()
        await api.connect()
        try:
            return await api.memory_delete(numeric_id)
        finally:
            await api.close()

    try:
        asyncio.run(_delete())
    except APIError as e:
        print(f"Error: {e.detail}")
        raise SystemExit(1)

    print(f"Deleted observation #{numeric_id}")


def _handle_memories_timeline(args: list[str]) -> None:
    """Handle telec memories timeline."""
    before = 3
    after = 3
    project: str | None = None
    anchor_id: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("memories", "timeline"))
            return
        elif arg == "--before" and i + 1 < len(args):
            try:
                before = int(args[i + 1])
            except ValueError:
                print(f"Invalid value for --before: {args[i + 1]}")
                raise SystemExit(1)
            i += 2
        elif arg == "--before":
            print("Missing value for --before.")
            print(_usage("memories", "timeline"))
            raise SystemExit(1)
        elif arg == "--after" and i + 1 < len(args):
            try:
                after = int(args[i + 1])
            except ValueError:
                print(f"Invalid value for --after: {args[i + 1]}")
                raise SystemExit(1)
            i += 2
        elif arg == "--after":
            print("Missing value for --after.")
            print(_usage("memories", "timeline"))
            raise SystemExit(1)
        elif arg == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif arg == "--project":
            print("Missing value for --project.")
            print(_usage("memories", "timeline"))
            raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("memories", "timeline"))
            raise SystemExit(1)
        else:
            if anchor_id is None:
                anchor_id = arg
            else:
                print(f"Unexpected argument: {arg}")
                print(_usage("memories", "timeline"))
                raise SystemExit(1)
            i += 1

    if not anchor_id:
        print("Anchor ID is required.")
        print(_usage("memories", "timeline"))
        raise SystemExit(1)

    try:
        numeric_anchor = int(anchor_id)
    except ValueError:
        print(f"Invalid ID '{anchor_id}': must be a number.")
        raise SystemExit(1)

    async def _timeline() -> list[dict[str, object]]:  # guard: loose-dict - JSON response from daemon memory API
        api = TelecAPIClient()
        await api.connect()
        try:
            return await api.memory_timeline(numeric_anchor, before=before, after=after, project=project)
        finally:
            await api.close()

    try:
        results = asyncio.run(_timeline())
    except APIError as e:
        print(f"Error: {e.detail}")
        raise SystemExit(1)

    if not results:
        print(f"No observations found around #{numeric_anchor}")
        return

    print(f"\nTimeline around observation #{numeric_anchor}:\n")
    print(f"{'ID':>6} | {'Type':<12} | {'Project':<16} | {'Title':<40} | Snippet")
    print("-" * 110)
    for r in results:
        obs_id = str(r.get("id", ""))
        try:
            marker = " ◀" if int(obs_id) == numeric_anchor else ""
        except (ValueError, TypeError):
            marker = ""
        r_type = str(r.get("type", ""))
        r_project = str(r.get("project", ""))
        r_title = str(r.get("title", ""))[:40]
        narrative = str(r.get("narrative", "") or r.get("text", ""))[:60]
        print(f"{obs_id:>6} | {r_type:<12} | {r_project:<16} | {r_title:<40} | {narrative}…{marker}")
