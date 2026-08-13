"""Sectioned dependency-tree projection for the todo.

Single owner of todo shape: takes the flat ``list[TodoDTO]`` from
``assemble_todo_from_db`` and returns ``active``/``delivered``/``icebox``
sections, each a dependency tree. Every consumer (TUI, ``telec todo list``)
renders these — no consumer re-derives hierarchy.

Re-root rule falls out of per-section visibility: a section's tree is built
over only that section's members, so a delivered parent is simply not visible
in ``active`` and its not-yet-delivered children re-root there. The same
mechanism keeps the delivered hierarchy intact among delivered items.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from teleclaude.api_models import TodoDTO
from teleclaude.constants import TodoStatus
from teleclaude.core.todo import section_sort_key

SiblingKey = Callable[[TodoDTO], Any]


@dataclass
class TodoNode:
    """A todo and its nested children within one section's dependency tree."""

    todo: TodoDTO
    children: list[TodoNode] = field(default_factory=list)
    is_holder: bool = False
    """True only when other todos group-reference this row by durable id (real holder).

    Children attached via ``after``-dependencies do NOT make a node a holder —
    a dep-parent has its own status and must render it. Only real holders
    (todos that other todos point at via ``group_id``) suppress status.
    """


@dataclass
class TodoSections:
    """The todo list split into independent dependency trees by status."""

    active: list[TodoNode] = field(default_factory=list)
    delivered: list[TodoNode] = field(default_factory=list)
    icebox: list[TodoNode] = field(default_factory=list)
    removed: list[TodoNode] = field(default_factory=list)


@dataclass
class FlatRow:
    """A DFS-flattened node carrying the visual properties renderers need."""

    todo: TodoDTO
    depth: int
    is_last: bool
    tree_lines: list[bool]
    is_holder: bool


def _has_cycle_to(parent_map: dict[str, str | None], node_id: str, target_id: str) -> bool:
    """Return True if following parent_map upward from node_id reaches target_id."""
    seen: set[str] = set()
    current: str | None = node_id
    while current is not None:
        if current == target_id:
            return True
        if current in seen:
            return False
        seen.add(current)
        current = parent_map.get(current)
    return False


def _resolve_parent(
    todo: TodoDTO,
    visible_ids: set[str],
    parent_map: dict[str, str | None],
    group_id_of: dict[str, str | None],
    id_by_slug: dict[str, str],
) -> str | None:
    """Visual parent (by durable id) of a node, within the visible set.

    A grouped node nests under the innermost same-group after-dependency when one
    is visible — so an intra-group dependency renders as nesting, not a flat
    sibling — and otherwise under its group holder. An after edge crossing into
    another group does not re-home the node out of its group. An ungrouped node
    nests under its first cycle-free after entry.

    Resolved by durable id, never by slug: a retained delivered/removed row
    may legitimately share a slug with a live holder's synthetic label node
    (project/spec/feature/workflow/todo-management#known-caveats), so slug
    matching would misattribute the wrong row as parent.
    """
    group_id = (
        todo.group_id if todo.group_id and todo.group_id in visible_ids and todo.group_id != todo.todo_id else None
    )
    if group_id is not None:
        for candidate_slug in todo.after:
            candidate_id = id_by_slug.get(candidate_slug)
            if (
                candidate_id
                and candidate_id in visible_ids
                and candidate_id != todo.todo_id
                and group_id_of.get(candidate_id) == group_id
                and not _has_cycle_to(parent_map, candidate_id, todo.todo_id or "")
            ):
                return candidate_id
        return group_id
    for candidate_slug in todo.after:
        candidate_id = id_by_slug.get(candidate_slug)
        if (
            candidate_id
            and candidate_id in visible_ids
            and candidate_id != todo.todo_id
            and not _has_cycle_to(parent_map, candidate_id, todo.todo_id or "")
        ):
            return candidate_id
    return None


def _topo_sort_siblings(
    ids: list[str],
    after_map: dict[str, list[str]],
    *,
    by_id: dict[str, TodoDTO] | None = None,
    sibling_key: SiblingKey | None = None,
) -> list[str]:
    """Stable topological sort of a sibling set (by durable id) by after-deps; input order breaks ties."""
    sibling_set = set(ids)
    input_order = {node_id: index for index, node_id in enumerate(ids)}

    def _sort_key(node_id: str) -> Any:
        if sibling_key is not None and by_id is not None:
            todo = by_id.get(node_id)
            if todo is not None:
                return sibling_key(todo)
        return input_order[node_id]

    in_degree: dict[str, int] = {s: 0 for s in ids}
    dependents: dict[str, list[str]] = {s: [] for s in ids}
    for node_id in ids:
        for dep in after_map.get(node_id, []):
            if dep in sibling_set:
                in_degree[node_id] += 1
                dependents[dep].append(node_id)
    queue: deque[str] = deque(sorted((s for s in ids if in_degree[s] == 0), key=_sort_key))
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for dep in sorted(dependents[current], key=_sort_key):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
        queue = deque(sorted(queue, key=_sort_key))
    if len(order) < len(ids):
        seen = set(order)
        order.extend(sorted((s for s in ids if s not in seen), key=_sort_key))
    return order


def _build_tree(todos: list[TodoDTO], *, sibling_key: SiblingKey | None = None) -> list[TodoNode]:
    """Build one section's dependency forest. Hierarchy is restricted to ``todos``.

    Nesting (group and after) is resolved by durable id (``todo_id``/
    ``group_id``) throughout — never by slug. A retained delivered or
    removed row may legitimately share a slug with a live holder's synthetic
    label node, and only id-keyed identity survives that collision without
    dropping or misattributing either row. ``after``-dependency slugs are
    resolved to ids via a first-seen mapping — unambiguous in practice since
    an after-edge never targets a synthetic holder label.
    """
    if not todos:
        return []
    by_id = {t.todo_id: t for t in todos if t.todo_id}
    visible_ids = set(by_id)
    id_by_slug: dict[str, str] = {}
    for t in todos:
        if t.todo_id:
            id_by_slug.setdefault(t.slug, t.todo_id)
    after_map = {t.todo_id: [id_by_slug[d] for d in t.after if d in id_by_slug] for t in todos if t.todo_id}
    # Holder set is data-driven: an id is a holder iff some OTHER todo in this
    # section group-references it by durable id. After-deps never make a node
    # a holder — the visual nesting of after-children under their dep is purely
    # presentational; status suppression must NOT follow nesting. Self-references
    # (group_id == todo_id) are not holder relationships either.
    holder_ids = {t.group_id for t in todos if t.group_id and t.group_id in visible_ids and t.group_id != t.todo_id}
    group_id_of = {t.todo_id: t.group_id for t in todos if t.todo_id}

    parent_map: dict[str, str | None] = {}
    children_map: dict[str, list[str]] = {}
    for todo in todos:
        if not todo.todo_id:
            continue
        parent = _resolve_parent(todo, visible_ids, parent_map, group_id_of, id_by_slug)
        parent_map[todo.todo_id] = parent
        if parent is not None:
            children_map.setdefault(parent, []).append(todo.todo_id)

    roots = [node_id for node_id in by_id if parent_map[node_id] is None]

    def _root_of(node_id: str) -> str:
        current = node_id
        parent = parent_map.get(current)
        while parent is not None:
            current = parent
            parent = parent_map.get(current)
        return current

    for parent_id, kids in children_map.items():
        children_map[parent_id] = _topo_sort_siblings(kids, after_map, by_id=by_id, sibling_key=sibling_key)

    root_after: dict[str, list[str]] = {r: [] for r in roots}
    for todo in todos:
        if not todo.todo_id:
            continue
        todo_root = _root_of(todo.todo_id)
        for dep_slug in todo.after:
            dep_id = id_by_slug.get(dep_slug)
            if dep_id and dep_id in visible_ids:
                dep_root = _root_of(dep_id)
                if dep_root != todo_root and dep_root in root_after and todo_root in root_after:
                    root_after[todo_root].append(dep_root)
    ordered_roots = _topo_sort_siblings(roots, root_after, by_id=by_id, sibling_key=sibling_key)

    def _node(node_id: str) -> TodoNode:
        return TodoNode(
            todo=by_id[node_id],
            children=[_node(child) for child in children_map.get(node_id, [])],
            is_holder=node_id in holder_ids,
        )

    return [_node(root) for root in ordered_roots]


def build_todo_sections(todos: list[TodoDTO]) -> TodoSections:
    """Split the flat todo list into active/delivered/icebox dependency trees.

    Each section's tree is built over only its own members, so cross-section
    edges (e.g. a delivered parent of an active child) drop out automatically.
    """
    active: list[TodoDTO] = []
    delivered: list[TodoDTO] = []
    icebox: list[TodoDTO] = []
    removed: list[TodoDTO] = []
    for todo in todos:
        if todo.status == TodoStatus.DELIVERED:
            delivered.append(todo)
        elif todo.status == TodoStatus.ICEBOX:
            icebox.append(todo)
        elif todo.status == TodoStatus.REMOVED:
            removed.append(todo)
        else:
            active.append(todo)
    return TodoSections(
        active=_build_tree(active, sibling_key=section_sort_key),
        delivered=_build_tree(
            delivered,
            sibling_key=lambda todo: section_sort_key(todo, raw_status=TodoStatus.DELIVERED),
        ),
        icebox=_build_tree(
            icebox,
            sibling_key=lambda todo: section_sort_key(todo, raw_status=TodoStatus.ICEBOX),
        ),
        removed=_build_tree(
            removed,
            sibling_key=lambda todo: section_sort_key(todo, raw_status=TodoStatus.REMOVED),
        ),
    )


def flatten(
    nodes: list[TodoNode],
    _tree_lines: list[bool] | None = None,
    *,
    force_root_branch: bool = False,
) -> list[FlatRow]:
    """DFS-flatten a forest into rows with depth/is_last/tree_lines for rendering.

    ``force_root_branch`` keeps every root rendered as a continued branch
    (``├─`` with a vertical line through its subtree). The TUI sets this
    because a section separator always closes the section below the roots; the
    CLI leaves it off so the last root terminates with ``└─``.
    """
    tree_lines = _tree_lines or []
    is_root_level = _tree_lines is None
    rows: list[FlatRow] = []
    for index, node in enumerate(nodes):
        last = index == len(nodes) - 1
        if is_root_level and force_root_branch:
            row_is_last, child_continues = False, True
        else:
            row_is_last, child_continues = last, not last
        rows.append(
            FlatRow(
                todo=node.todo,
                depth=len(tree_lines),
                is_last=row_is_last,
                tree_lines=tree_lines,
                is_holder=node.is_holder,
            )
        )
        if node.children:
            rows.extend(flatten(node.children, [*tree_lines, child_continues]))
    return rows
