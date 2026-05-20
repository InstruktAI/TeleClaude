"""Sectioned dependency-tree projection for the roadmap.

Single owner of roadmap shape: takes the flat ``list[TodoDTO]`` from
``assemble_roadmap_from_db`` and returns ``active``/``delivered``/``icebox``
sections, each a dependency tree. Every consumer (TUI, ``telec roadmap list``)
renders these — no consumer re-derives hierarchy.

Re-root rule falls out of per-section visibility: a section's tree is built
over only that section's members, so a delivered parent is simply not visible
in ``active`` and its not-yet-delivered children re-root there. The same
mechanism keeps the delivered hierarchy intact among delivered items.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from teleclaude.api_models import TodoDTO
from teleclaude.constants import RoadmapStatus


@dataclass
class RoadmapNode:
    """A todo and its nested children within one section's dependency tree."""

    todo: TodoDTO
    children: list[RoadmapNode] = field(default_factory=list)
    is_holder: bool = False
    """True only when other todos group-reference this slug (real holder).

    Children attached via ``after``-dependencies do NOT make a node a holder —
    a dep-parent has its own status and must render it. Only real holders
    (todos that other todos point at via ``group_slug``) suppress status.
    """


@dataclass
class RoadmapSections:
    """The roadmap split into independent dependency trees by status."""

    active: list[RoadmapNode] = field(default_factory=list)
    delivered: list[RoadmapNode] = field(default_factory=list)
    icebox: list[RoadmapNode] = field(default_factory=list)


@dataclass
class FlatRow:
    """A DFS-flattened node carrying the visual properties renderers need."""

    todo: TodoDTO
    depth: int
    is_last: bool
    tree_lines: list[bool]
    is_holder: bool


def _has_cycle_to(parent_map: dict[str, str | None], slug: str, target: str) -> bool:
    """Return True if following parent_map upward from slug reaches target."""
    seen: set[str] = set()
    current: str | None = slug
    while current is not None:
        if current == target:
            return True
        if current in seen:
            return False
        seen.add(current)
        current = parent_map.get(current)
    return False


def _resolve_parent(
    todo: TodoDTO,
    visible: set[str],
    parent_map: dict[str, str | None],
) -> str | None:
    """Visual parent: explicit group, else first cycle-free after entry, within the visible set."""
    if todo.group and todo.group in visible and todo.group != todo.slug:
        return todo.group
    for candidate in todo.after:
        if candidate in visible and candidate != todo.slug and not _has_cycle_to(parent_map, candidate, todo.slug):
            return candidate
    return None


def _topo_sort_siblings(slugs: list[str], after_map: dict[str, list[str]]) -> list[str]:
    """Stable topological sort of a sibling set by after-deps; input order breaks ties."""
    sibling_set = set(slugs)
    in_degree: dict[str, int] = {s: 0 for s in slugs}
    dependents: dict[str, list[str]] = {s: [] for s in slugs}
    for slug in slugs:
        for dep in after_map.get(slug, []):
            if dep in sibling_set:
                in_degree[slug] += 1
                dependents[dep].append(slug)
    queue: deque[str] = deque(s for s in slugs if in_degree[s] == 0)
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for dep in sorted(dependents[current], key=slugs.index):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)
    if len(order) < len(slugs):
        seen = set(order)
        order.extend(s for s in slugs if s not in seen)
    return order


def _build_tree(todos: list[TodoDTO]) -> list[RoadmapNode]:
    """Build one section's dependency forest. Hierarchy is restricted to ``todos``."""
    if not todos:
        return []
    by_slug = {t.slug: t for t in todos}
    visible = set(by_slug)
    after_map = {t.slug: t.after for t in todos}
    # Holder set is data-driven: a slug is a holder iff some OTHER todo in this
    # section group-references it. After-deps never make a node a holder — the
    # visual nesting of after-children under their dep is purely presentational;
    # status suppression must NOT follow nesting. Self-references (group == slug)
    # are not holder relationships either — a todo cannot hold itself.
    holder_slugs = {t.group for t in todos if t.group and t.group in visible and t.group != t.slug}

    parent_map: dict[str, str | None] = {}
    children_map: dict[str, list[str]] = {}
    for todo in todos:
        parent = _resolve_parent(todo, visible, parent_map)
        parent_map[todo.slug] = parent
        if parent is not None:
            children_map.setdefault(parent, []).append(todo.slug)

    roots = [t.slug for t in todos if parent_map[t.slug] is None]

    def _root_of(slug: str) -> str:
        current = slug
        parent = parent_map.get(current)
        while parent is not None:
            current = parent
            parent = parent_map.get(current)
        return current

    for parent_slug, kids in children_map.items():
        children_map[parent_slug] = _topo_sort_siblings(kids, after_map)

    root_after: dict[str, list[str]] = {r: [] for r in roots}
    for todo in todos:
        todo_root = _root_of(todo.slug)
        for dep in todo.after:
            if dep in visible:
                dep_root = _root_of(dep)
                if dep_root != todo_root and dep_root in root_after and todo_root in root_after:
                    root_after[todo_root].append(dep_root)
    ordered_roots = _topo_sort_siblings(roots, root_after)

    def _node(slug: str) -> RoadmapNode:
        return RoadmapNode(
            todo=by_slug[slug],
            children=[_node(child) for child in children_map.get(slug, [])],
            is_holder=slug in holder_slugs,
        )

    return [_node(root) for root in ordered_roots]


def build_roadmap_sections(todos: list[TodoDTO]) -> RoadmapSections:
    """Split the flat roadmap into active/delivered/icebox dependency trees.

    Each section's tree is built over only its own members, so cross-section
    edges (e.g. a delivered parent of an active child) drop out automatically.
    """
    active: list[TodoDTO] = []
    delivered: list[TodoDTO] = []
    icebox: list[TodoDTO] = []
    for todo in todos:
        if todo.status == RoadmapStatus.DELIVERED:
            delivered.append(todo)
        elif todo.status == RoadmapStatus.ICEBOX:
            icebox.append(todo)
        else:
            active.append(todo)
    return RoadmapSections(
        active=_build_tree(active),
        delivered=_build_tree(delivered),
        icebox=_build_tree(icebox),
    )


def flatten(
    nodes: list[RoadmapNode],
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
