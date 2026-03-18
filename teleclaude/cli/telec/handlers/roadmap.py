"""Handlers for telec roadmap commands."""

from __future__ import annotations

import json
import subprocess
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from teleclaude.cli.telec.handlers._arg_parsing import parse_slug_after_args
from teleclaude.cli.telec.help import _usage

if TYPE_CHECKING:
    from teleclaude.core.models import TodoInfo

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


def _load_core_roadmap_module():
    return import_module("teleclaude.core.roadmap")


def _load_next_machine_core_module():
    return import_module("teleclaude.core.next_machine.core")


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

    roadmap_module = _load_core_roadmap_module()
    todos = roadmap_module.assemble_roadmap(
        str(Path.cwd()),
        include_icebox=parsed["include_icebox"],
        icebox_only=parsed["icebox_only"],
        include_delivered=parsed["include_delivered"],
        delivered_only=parsed["delivered_only"],
    )

    if not todos:
        if parsed["json_output"]:
            print("[]")
        else:
            print("Roadmap is empty.")
        return

    if parsed["json_output"]:
        print(json.dumps([t.to_dict() for t in todos], indent=2))
        return

    _print_grouped_roadmap(todos)


def _parse_roadmap_show_args(args: list[str]) -> dict[str, bool]:
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
    parsed = {
        "include_icebox": False,
        "icebox_only": False,
        "include_delivered": False,
        "delivered_only": False,
        "json_output": False,
    }
    for arg in args:
        option = options.get(arg)
        if option:
            parsed[option] = True
            continue
        error_kind = "option" if arg.startswith("-") else "argument"
        print(f"Unknown {error_kind}: {arg}")
        print(_usage("roadmap", "list"))
        raise SystemExit(1)
    return parsed


def _todo_extras(todo: TodoInfo) -> str:
    extras = []
    if todo.dor_score is not None:
        extras.append(f"DOR:{todo.dor_score}")
    if todo.findings_count > 0:
        extras.append(f"Findings:{todo.findings_count}")
    if todo.build_status and todo.build_status != "pending":
        extras.append(f"Build:{todo.build_status}")
    if todo.review_status and todo.review_status != "pending":
        extras.append(f"Review:{todo.review_status}")
    if todo.delivered_at:
        extras.append(f"Delivered:{todo.delivered_at}")
    return f" [{', '.join(extras)}]" if extras else ""


def _print_grouped_roadmap(todos: list[TodoInfo]) -> None:
    groups: dict[str, list[TodoInfo]] = {}
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
            deps_str = f" (after: {', '.join(todo.after)})" if todo.after else ""
            print(f"    {todo.slug} [{todo.status}]{_todo_extras(todo)}{deps_str}")


def _handle_roadmap_add(args: list[str]) -> None:
    """Handle telec roadmap add <slug> [--group <slug>] [--after d1,d2] [--description T] [--before S]."""
    if not args:
        print(_usage("roadmap", "add"))
        return

    slug: str | None = None
    project_root = Path.cwd()
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

    core_module = _load_next_machine_core_module()
    if core_module.add_to_roadmap(
        str(project_root), slug, group=group, after=after, description=description, before=before
    ):
        print(f"Added {slug} to roadmap.")
    else:
        print(f"Slug already exists in roadmap: {slug}")


def _handle_roadmap_remove(args: list[str]) -> None:
    """Handle telec roadmap remove <slug>."""
    if not args:
        print(_usage("roadmap", "remove"))
        return

    project_root = Path.cwd()
    slug = _parse_single_slug_args(args, "remove")

    core_module = _load_next_machine_core_module()
    if core_module.remove_from_roadmap(str(project_root), slug):
        print(f"Removed {slug} from roadmap.")
        return
    print(f"Slug not found in roadmap: {slug}")
    raise SystemExit(1)


def _handle_roadmap_move(args: list[str]) -> None:
    """Handle telec roadmap move <slug> --before <s> | --after <s>."""
    if not args:
        print(_usage("roadmap", "move"))
        return

    slug: str | None = None
    project_root = Path.cwd()
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

    core_module = _load_next_machine_core_module()
    if core_module.move_in_roadmap(str(project_root), slug, before=before, after=after):
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

    project_root = Path.cwd()
    slug, after = _parse_roadmap_deps_args(args)

    cwd = str(project_root)
    core_module = _load_next_machine_core_module()
    entries = core_module.load_roadmap(cwd)
    found = False
    for entry in entries:
        if entry.slug == slug:
            entry.after = after
            found = True
            break

    if not found:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)

    core_module.save_roadmap(cwd, entries)
    if after:
        print(f"Set dependencies for {slug}: {', '.join(after)}")
    else:
        print(f"Cleared dependencies for {slug}.")


def _handle_roadmap_freeze(args: list[str]) -> None:
    """Handle telec roadmap freeze <slug>."""
    if not args:
        print(_usage("roadmap", "freeze"))
        return

    project_root = Path.cwd()
    slug = _parse_single_slug_args(args, "freeze")

    core_module = _load_next_machine_core_module()
    if core_module.freeze_to_icebox(str(project_root), slug):
        print(f"Froze {slug} → icebox.yaml")
        return
    print(f"Slug not found in roadmap: {slug}")
    raise SystemExit(1)


def _handle_roadmap_unfreeze(args: list[str]) -> None:
    """Handle telec roadmap unfreeze <slug>."""
    if not args:
        print(_usage("roadmap", "unfreeze"))
        return

    project_root = Path.cwd()
    slug = _parse_single_slug_args(args, "unfreeze")

    core_module = _load_next_machine_core_module()
    if core_module.unfreeze_from_icebox(str(project_root), slug):
        print(f"Unfroze {slug} → roadmap.yaml")
        return
    print(f"Slug not found in icebox: {slug}")
    raise SystemExit(1)


def _handle_roadmap_migrate_icebox(_args: list[str]) -> None:
    """Handle telec roadmap migrate-icebox."""
    project_root = Path.cwd()
    core_module = _load_next_machine_core_module()
    count = core_module.migrate_icebox_to_subfolder(str(project_root))
    if count == 0:
        print("Already migrated (nothing to move).")
    else:
        print(f"Migrated {count} icebox item(s) to todos/_icebox/.")


def _handle_roadmap_deliver(args: list[str]) -> None:
    """Handle telec roadmap deliver <slug> [--commit SHA].

    Full idempotent delivery: moves YAML entry, cleans up worktree/branch/todo dir, commits.
    """
    if not args:
        print(_usage("roadmap", "deliver"))
        return

    slug: str | None = None
    project_root = Path.cwd()
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

    cwd = str(project_root)
    core_module = _load_next_machine_core_module()

    # 1. Move YAML entry (idempotent — returns True if already delivered)
    if not core_module.deliver_to_delivered(cwd, slug, commit=commit):
        print(f"Slug not found in roadmap or delivered: {slug}")
        raise SystemExit(1)

    # 2. Physical cleanup (idempotent — each step no-ops if already done)
    core_module.cleanup_delivered_slug(cwd, slug)

    # 3. Stage and commit all delivery artifacts
    subprocess.run(
        ["git", "add", "todos/roadmap.yaml", "todos/delivered.yaml", f"todos/{slug}"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    # Only commit if there are staged changes
    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if diff_result.returncode != 0:
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                (f"chore({slug}): deliver and cleanup\n\nCo-Authored-By: TeleClaude <noreply@instrukt.ai>"),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd,
        )

    print(f"Delivered {slug} → delivered.yaml (cleanup complete)")


def _parse_single_slug_args(args: list[str], subcommand: str) -> str:
    slug: str | None = None
    for arg in args:
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", subcommand))
            raise SystemExit(1)
        if slug is not None:
            print("Only one slug is allowed.")
            raise SystemExit(1)
        slug = arg

    if slug:
        return slug

    print("Missing required slug.")
    print(_usage("roadmap", subcommand))
    raise SystemExit(1)


def _parse_roadmap_deps_args(args: list[str]) -> tuple[str, list[str]]:
    slug, after = parse_slug_after_args(args, lambda: _usage("roadmap", "deps"))
    if after is None:
        print("--after is required.")
        print(_usage("roadmap", "deps"))
        raise SystemExit(1)
    return slug, after
