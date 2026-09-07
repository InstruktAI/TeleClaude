"""Handlers and renderers for ``telec todo list``."""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import TypedDict

from teleclaude.api_models import TodoDTO
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import TODO_LIST
from teleclaude.core.todo import parse_since_to_cutoff
from teleclaude.core.todo_tree import TodoNode, build_todo_sections, flatten
from teleclaude.project_root import resolve_invocation_project_root
from teleclaude.services.work import get_work_service

__all__ = ["_handle_todo_list"]


def _resolve_project_root_or_exit() -> Path:
    """Resolve the invocation project root, or exit with a clean CLI error.

    ``resolve_invocation_project_root`` raises ``FileNotFoundError`` when the
    invocation cwd does not resolve to a project checkout; surfaced as a raw
    traceback otherwise, unlike the daemon API's equivalent clean 400.
    """
    try:
        return resolve_invocation_project_root()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


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
    project_root = _resolve_project_root_or_exit()

    since_cutoff = parsed["since_cutoff"]
    show_delivered = parsed["include_delivered"] or parsed["delivered_only"] or bool(since_cutoff)
    show_icebox = parsed["include_icebox"] or parsed["icebox_only"]
    show_removed = parsed["include_removed"] or parsed["removed_only"]

    svc = get_work_service(str(project_root))
    todos = svc.todo.entries(
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

    sections = build_todo_sections(todos)
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
    parsed_args = parse_command_args(TODO_LIST, args)
    if parsed_args.positionals:
        print(f"Unknown argument: {parsed_args.positionals[0]}")
        print(_usage("todo", "list"))
        raise SystemExit(1)

    since_cutoff = ""
    since_raw = parsed_args.value(F.FLAG_TODO_LIST_SINCE)
    if since_raw is not None:
        try:
            since_cutoff = parse_since_to_cutoff(since_raw)
        except ValueError as exc:
            print(str(exc))
            print(_usage("todo", "list"))
            raise SystemExit(1) from exc

    return {
        "include_icebox": parsed_args.has(F.FLAG_TODO_LIST_INCLUDE_ICEBOX),
        "icebox_only": parsed_args.has(F.FLAG_TODO_LIST_ICEBOX_ONLY),
        "include_delivered": parsed_args.has(F.FLAG_TODO_LIST_INCLUDE_DELIVERED),
        "delivered_only": parsed_args.has(F.FLAG_TODO_LIST_DELIVERED_ONLY),
        "include_removed": parsed_args.has(F.FLAG_TODO_LIST_INCLUDE_REMOVED),
        "removed_only": parsed_args.has(F.FLAG_TODO_LIST_REMOVED_ONLY),
        "json_output": parsed_args.has(F.FLAG_TODO_LIST_JSON),
        "since_cutoff": since_cutoff,
    }


def _print_sectioned_todo_list(sections: list[tuple[str, list[TodoNode]]]) -> None:
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


def _node_to_dict(node: TodoNode) -> _TrimmedTodoDict:
    result = _todo_to_trimmed_dict(node.todo)
    if node.children:
        result["children"] = [_node_to_dict(child) for child in node.children]
    return result
