"""Handlers and renderers for ``telec todo list``."""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import TypedDict

from teleclaude.api_models import TodoDTO
from teleclaude.cli.telec.help import _usage
from teleclaude.core.roadmap import parse_since_to_cutoff
from teleclaude.core.roadmap_tree import RoadmapNode, build_roadmap_sections, flatten
from teleclaude.project_root import resolve_invocation_project_root
from teleclaude.services.work import get_work_service

__all__ = ["_handle_todo_list"]


class _TodoListArgs(TypedDict):
    include_icebox: bool
    icebox_only: bool
    include_delivered: bool
    delivered_only: bool
    include_removed: bool
    removed_only: bool
    json_output: bool
    since_cutoff: str


def _handle_todo_list(args: list[str]) -> None:
    """Display todos as sectioned active/delivered/icebox/removed dependency trees."""
    parsed = _parse_todo_list_args(args)
    project_root = _resolve_todo_project_root()

    since_cutoff = parsed["since_cutoff"]
    show_delivered = parsed["include_delivered"] or parsed["delivered_only"] or bool(since_cutoff)
    show_icebox = parsed["include_icebox"] or parsed["icebox_only"]
    show_removed = parsed["include_removed"] or parsed["removed_only"]

    svc = get_work_service(str(project_root))
    todos = svc.roadmap.entries(
        include_icebox=True,
        include_delivered=True,
        include_removed=True,
        delivered_since=since_cutoff or None,
    )

    if not todos:
        if parsed["json_output"]:
            print("{}")
        else:
            print("Todo list is empty.")
        return

    sections = build_roadmap_sections(todos)
    if parsed["delivered_only"]:
        section_items = [("delivered", sections.delivered)]
    elif parsed["icebox_only"]:
        section_items = [("icebox", sections.icebox)]
    elif parsed["removed_only"]:
        section_items = [("removed", sections.removed)]
    else:
        section_items = [("active", sections.active)]
        if show_delivered:
            section_items.append(("delivered", sections.delivered))
        if show_icebox:
            section_items.append(("icebox", sections.icebox))
        if show_removed:
            section_items.append(("removed", sections.removed))

    if parsed["json_output"]:
        payload = {name: [_node_to_dict(n) for n in nodes] for name, nodes in section_items if nodes}
        print(_json.dumps(payload, indent=2))
        return

    _print_sectioned_todo_list(section_items)


def _parse_todo_list_args(args: list[str]) -> _TodoListArgs:
    options = {
        "--include-icebox": "include_icebox",
        "-i": "include_icebox",
        "--icebox-only": "icebox_only",
        "-o": "icebox_only",
        "--include-delivered": "include_delivered",
        "-d": "include_delivered",
        "--delivered-only": "delivered_only",
        "--include-removed": "include_removed",
        "-r": "include_removed",
        "--removed-only": "removed_only",
        "--json": "json_output",
    }
    parsed: _TodoListArgs = {
        "include_icebox": False,
        "icebox_only": False,
        "include_delivered": False,
        "delivered_only": False,
        "include_removed": False,
        "removed_only": False,
        "json_output": False,
        "since_cutoff": "",
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--since":
            if i + 1 >= len(args):
                print("--since requires a value (e.g. 7d, 72h, 2w, or 2026-05-01)")
                print(_usage("todo", "list"))
                raise SystemExit(1)
            try:
                parsed["since_cutoff"] = parse_since_to_cutoff(args[i + 1])
            except ValueError as exc:
                print(str(exc))
                print(_usage("todo", "list"))
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
        print(_usage("todo", "list"))
        raise SystemExit(1)
    return parsed


def _resolve_todo_project_root() -> Path:
    return resolve_invocation_project_root()


def _print_sectioned_todo_list(sections: list[tuple[str, list[RoadmapNode]]]) -> None:
    first = True
    for name, nodes in sections:
        if not nodes:
            continue
        if not first:
            print()
        first = False
        print(f"{name}:")
        for row in flatten(nodes):
            parts = [f"    {'  ' * row.depth}{row.todo.slug}"]
            if row.todo.description:
                parts.append(f" {row.todo.description}")
            if row.todo.after:
                parts.append(f" (after: {', '.join(row.todo.after)})")
            print("".join(parts))


class _TrimmedTodoDict(TypedDict, total=False):
    """Minimal todo list entry for JSON output."""

    slug: str
    status: str
    description: str
    after: list[str]
    group: str
    delivered_at: str
    removed_at: str
    children: list[_TrimmedTodoDict]


def _todo_to_trimmed_dict(todo: TodoDTO) -> _TrimmedTodoDict:
    result = _TrimmedTodoDict(slug=todo.slug, status=todo.status)
    if todo.description:
        result["description"] = todo.description
    if todo.after:
        result["after"] = todo.after
    if todo.group:
        result["group"] = todo.group
    if todo.delivered_at:
        result["delivered_at"] = todo.delivered_at
    if todo.removed_at:
        result["removed_at"] = todo.removed_at
    return result


def _node_to_dict(node: RoadmapNode) -> _TrimmedTodoDict:
    result = _todo_to_trimmed_dict(node.todo)
    if node.children:
        result["children"] = [_node_to_dict(child) for child in node.children]
    return result
