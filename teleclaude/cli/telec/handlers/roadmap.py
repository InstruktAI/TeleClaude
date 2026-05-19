"""Handlers for telec roadmap commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from teleclaude.cli.telec.help import _usage
from teleclaude.core.todos_db import TodosDb
from teleclaude.project_root import resolve_invocation_cwd, resolve_state_root
from teleclaude.slug import validate_slug

if TYPE_CHECKING:
    from teleclaude.api_models import TodoDTO
import asyncio
import json

from teleclaude.core.next_machine.delivery import cleanup_delivered_slug
from teleclaude.core.roadmap import parse_since_to_cutoff
from teleclaude.services.work import get_work_service

__all__ = [
    "_handle_roadmap",
    "_handle_roadmap_add",
    "_handle_roadmap_deliver",
    "_handle_roadmap_deps",
    "_handle_roadmap_freeze",
    "_handle_roadmap_migrate_icebox",
    "_handle_roadmap_move",
    "_handle_roadmap_remove",
    "_handle_roadmap_show",
    "_handle_roadmap_unfreeze",
]


def _handle_roadmap(args: list[str]) -> None:
    """Handle telec roadmap commands."""

    if not args:
        print(_usage("roadmap"))
        return

    subcommand = args[0]
    if subcommand == "list":
        _handle_roadmap_show(args[1:])
    elif subcommand == "add":
        _handle_roadmap_add(args[1:])
    elif subcommand == "remove":
        _handle_roadmap_remove(args[1:])
    elif subcommand == "move":
        _handle_roadmap_move(args[1:])
    elif subcommand == "deps":
        _handle_roadmap_deps(args[1:])
    elif subcommand == "freeze":
        _handle_roadmap_freeze(args[1:])
    elif subcommand == "unfreeze":
        _handle_roadmap_unfreeze(args[1:])
    elif subcommand == "migrate-icebox":
        _handle_roadmap_migrate_icebox(args[1:])
    elif subcommand == "deliver":
        _handle_roadmap_deliver(args[1:])
    else:
        print(f"Unknown roadmap subcommand: {subcommand}")
        print(_usage("roadmap"))
        raise SystemExit(1)


def _handle_roadmap_show(args: list[str]) -> None:
    """Display the roadmap grouped by group, with deps and state."""
    parsed = _parse_roadmap_show_args(args)
    project_root = _resolve_roadmap_project_root()

    since_cutoff = parsed["since_cutoff"]
    include_delivered = parsed["include_delivered"]
    # `--since` on its own means "delivered since X" — imply --include-delivered
    # so agents don't have to pass both flags for the obvious intent.
    if since_cutoff and not include_delivered and not parsed["delivered_only"]:
        include_delivered = True

    svc = get_work_service(str(project_root))
    todos = svc.roadmap.entries(
        include_icebox=parsed["include_icebox"],
        icebox_only=parsed["icebox_only"],
        include_delivered=include_delivered,
        delivered_only=parsed["delivered_only"],
        delivered_since=since_cutoff or None,
    )

    if not todos:
        if parsed["json_output"]:
            print("[]")
        else:
            print("Roadmap is empty.")
        return

    if parsed["json_output"]:
        print(json.dumps([_todo_to_trimmed_dict(t) for t in todos], indent=2))
        return

    _print_grouped_roadmap(todos)


class _RoadmapShowArgs(TypedDict):
    include_icebox: bool
    icebox_only: bool
    include_delivered: bool
    delivered_only: bool
    json_output: bool
    since_cutoff: str


def _parse_roadmap_show_args(args: list[str]) -> _RoadmapShowArgs:
    options = {
        "--include-icebox": "include_icebox",
        "-i": "include_icebox",
        "--icebox-only": "icebox_only",
        "-o": "icebox_only",
        "--include-delivered": "include_delivered",
        "-d": "include_delivered",
        "--delivered-only": "delivered_only",
        "--json": "json_output",
    }
    parsed: _RoadmapShowArgs = {
        "include_icebox": False,
        "icebox_only": False,
        "include_delivered": False,
        "delivered_only": False,
        "json_output": False,
        "since_cutoff": "",
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--since":
            if i + 1 >= len(args):
                print("--since requires a value (e.g. 7d, 72h, 2w, or 2026-05-01)")
                print(_usage("roadmap", "list"))
                raise SystemExit(1)
            try:
                parsed["since_cutoff"] = parse_since_to_cutoff(args[i + 1])
            except ValueError as exc:
                print(str(exc))
                print(_usage("roadmap", "list"))
                raise SystemExit(1) from exc
            i += 2
            continue
        option = options.get(arg)
        if option:
            parsed[option] = True  # type: ignore[literal-required]
            i += 1
            continue
        error_kind = "option" if arg.startswith("-") else "argument"
        print(f"Unknown {error_kind}: {arg}")
        print(_usage("roadmap", "list"))
        raise SystemExit(1)
    return parsed


def _print_grouped_roadmap(todos: list[TodoDTO]) -> None:
    groups: dict[str, list[TodoDTO]] = {}
    for todo in todos:
        groups.setdefault(todo.group or "", []).append(todo)

    first = True
    for group_name, group_todos in groups.items():
        if not first:
            print()
        first = False
        if group_name:
            print(f"  {group_name}")
            print(f"  {'─' * len(group_name)}")
        elif len(groups) > 1:
            print()

        for todo in group_todos:
            parts = [f"    {todo.slug} [{todo.status}]"]
            if todo.description:
                parts.append(f" {todo.description}")
            if todo.after:
                parts.append(f" (after: {', '.join(todo.after)})")
            print("".join(parts))


class _TrimmedTodoDict(TypedDict, total=False):
    """Minimal roadmap entry for JSON output."""

    slug: str
    status: str
    description: str
    after: list[str]
    group: str
    delivered_at: str


def _todo_to_trimmed_dict(todo: TodoDTO) -> _TrimmedTodoDict:
    """Build a minimal dict with only meaningful fields — no null values, no empty arrays."""
    result = _TrimmedTodoDict(slug=todo.slug, status=todo.status)
    if todo.description:
        result["description"] = todo.description
    if todo.after:
        result["after"] = todo.after
    if todo.group:
        result["group"] = todo.group
    if todo.delivered_at:
        result["delivered_at"] = todo.delivered_at
    return result


def _validate_slugs(*slugs: str | None) -> None:
    """Validate all non-None slug arguments; exit on invalid."""
    try:
        for slug in slugs:
            if slug is not None:
                validate_slug(slug)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1) from exc


def _resolve_roadmap_project_root() -> Path:
    """Resolve the canonical project root for roadmap commands."""
    return resolve_state_root(resolve_invocation_cwd())


def _run_db(project_root: Path, slug: str, method: str, **kwargs: object) -> object:
    """Run a TodosDb method synchronously via asyncio.run."""

    async def _execute() -> object:
        db = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
        await db.initialize()
        try:
            fn = getattr(db, method)
            return await fn(slug, **kwargs)
        finally:
            await db.close()

    return asyncio.run(_execute())


def _handle_roadmap_add(args: list[str]) -> None:
    """Handle telec roadmap add <slug> [--group <slug>] [--after d1,d2] [--description T] [--before S]."""

    if not args:
        print(_usage("roadmap", "add"))
        return

    slug: str | None = None
    group: str | None = None
    after: list[str] | None = None
    description: str | None = None
    before: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--group" and i + 1 < len(args):
            group = args[i + 1]
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            after = [p.strip() for p in args[i + 1].split(",") if p.strip()]
            i += 2
        elif arg == "--description" and i + 1 < len(args):
            description = args[i + 1]
            i += 2
        elif arg == "--before" and i + 1 < len(args):
            before = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "add"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("roadmap", "add"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "add"))
        raise SystemExit(1)

    _validate_slugs(slug, group, before, *(after or []))

    project_root = _resolve_roadmap_project_root()
    _run_db(project_root, slug, "add_to_roadmap", group_slug=group, after=after, description=description, before=before)
    print(f"Added {slug} to roadmap.")


def _handle_roadmap_remove(args: list[str]) -> None:
    """Handle telec roadmap remove <slug>."""

    if not args:
        print(_usage("roadmap", "remove"))
        return

    slug: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "remove"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "remove"))
        raise SystemExit(1)

    _validate_slugs(slug)

    project_root = _resolve_roadmap_project_root()
    if _run_db(project_root, slug, "remove_from_roadmap"):
        print(f"Removed {slug} from roadmap.")
    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_move(args: list[str]) -> None:
    """Handle telec roadmap move <slug> --before <s> | --after <s>."""

    if not args:
        print(_usage("roadmap", "move"))
        return

    slug: str | None = None
    before: str | None = None
    after: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--before" and i + 1 < len(args):
            before = args[i + 1]
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            after = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "move"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "move"))
        raise SystemExit(1)

    if not before and not after:
        print("Either --before or --after is required.")
        print(_usage("roadmap", "move"))
        raise SystemExit(1)

    _validate_slugs(slug, before, after)

    project_root = _resolve_roadmap_project_root()
    if _run_db(project_root, slug, "move_in_roadmap", before=before, after=after):
        target = before or after
        direction = "before" if before else "after"
        print(f"Moved {slug} {direction} {target}.")

    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_deps(args: list[str]) -> None:
    """Handle telec roadmap deps <slug> --after dep1,dep2."""
    if not args:
        print(_usage("roadmap", "deps"))
        return

    slug: str | None = None
    after: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [p.strip() for p in args[i + 1].split(",") if p.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "deps"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "deps"))
        raise SystemExit(1)

    if after is None:
        print("--after is required.")
        print(_usage("roadmap", "deps"))
        raise SystemExit(1)

    _validate_slugs(slug, *after)

    project_root = _resolve_roadmap_project_root()
    _run_db(project_root, slug, "set_deps", after=after)
    if after:
        print(f"Set dependencies for {slug}: {', '.join(after)}")
    else:
        print(f"Cleared dependencies for {slug}.")


def _handle_roadmap_freeze(args: list[str]) -> None:
    """Handle telec roadmap freeze <slug>."""

    if not args:
        print(_usage("roadmap", "freeze"))
        return

    slug: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "freeze"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "freeze"))
        raise SystemExit(1)

    _validate_slugs(slug)

    project_root = _resolve_roadmap_project_root()
    if _run_db(project_root, slug, "freeze"):
        print(f"Froze {slug} → icebox")

    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_unfreeze(args: list[str]) -> None:
    """Handle telec roadmap unfreeze <slug>."""

    if not args:
        print(_usage("roadmap", "unfreeze"))
        return

    slug: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "unfreeze"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "unfreeze"))
        raise SystemExit(1)

    _validate_slugs(slug)

    project_root = _resolve_roadmap_project_root()
    if _run_db(project_root, slug, "unfreeze"):
        print(f"Unfroze {slug} → roadmap")

    else:
        print(f"Slug not found in icebox: {slug}")
        raise SystemExit(1)


def _handle_roadmap_migrate_icebox(args: list[str]) -> None:
    """Handle telec roadmap migrate-icebox (deprecated — no-op after DB migration)."""
    print("No-op: icebox migration is no longer needed (data lives in todos.db).")


def _handle_roadmap_deliver(args: list[str]) -> None:
    """Handle telec roadmap deliver <slug> [--commit SHA].

    Marks as delivered in DB and cleans up worktree/branch.
    """
    if not args:
        print(_usage("roadmap", "deliver"))
        return

    slug: str | None = None
    commit: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--commit" and i + 1 < len(args):
            commit = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "deliver"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "deliver"))
        raise SystemExit(1)

    _validate_slugs(slug)

    project_root = _resolve_roadmap_project_root()
    if not _run_db(project_root, slug, "deliver", commit=commit):
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)

    cleanup_delivered_slug(str(project_root), slug)
    print(f"Delivered {slug} (cleanup complete)")
