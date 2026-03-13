"""Pure tree-building logic for preparation view dependency graph."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from teleclaude.cli.tui.todos import TodoItem


@dataclass
class TreeRenderNode:
    """A node in the rendered tree with computed visual properties."""

    slug: str
    depth: int
    is_last: bool
    tree_lines: list[bool]
    todo: TodoItem


def _topo_sort_siblings(slugs: list[str], after_map: dict[str, list[str]]) -> list[str]:
    """Topologically sort a sibling set by after-dependencies, stable on input order.

    Uses Kahn's algorithm restricted to the sibling set.
    Dependencies pointing outside the set are ignored.
    Original order is the tiebreaker for items with equal precedence.
    """
    sibling_set = set(slugs)
    # Build in-degree and adjacency restricted to this sibling set
    in_degree: dict[str, int] = {s: 0 for s in slugs}
    dependents: dict[str, list[str]] = {s: [] for s in slugs}

    for slug in slugs:
        for dep in after_map.get(slug, []):
            if dep in sibling_set:
                in_degree[slug] += 1
                dependents[dep].append(slug)

    # Seed queue with zero in-degree items, preserving input order
    queue: deque[str] = deque(s for s in slugs if in_degree[s] == 0)
    result: list[str] = []

    while queue:
        current = queue.popleft()
        result.append(current)
        # Release dependents in their original input order
        for dep in sorted(dependents[current], key=slugs.index):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    # Append any remaining items (cycle fallback) in original order
    if len(result) < len(slugs):
        seen = set(result)
        for s in slugs:
            if s not in seen:
                result.append(s)

    return result


def build_dep_tree(items: list[TodoItem]) -> list[TreeRenderNode]:
    """Build a dependency tree from TodoItems using `group` for hierarchy and `after` for ordering.

    Args:
        items: Flat list of TodoItems with `after` dependencies and optional `group`

    Returns:
        List of TreeRenderNode in DFS order (parent before children)

    Phase 1 - Hierarchy from `group`:
        - Items with `group=Y` (where Y is visible and not self) nest under Y
        - All others are roots

    Phase 2 - Ordering from `after`:
        - Siblings within each parent are topologically sorted by `after` deps
        - Cross-group `after` deps affect root ordering (A after B means A's root after B's root)

    Phase 3 - DFS walk:
        - Walk roots in sorted order, recurse into sorted children
        - Compute depth, is_last, tree_lines for rendering
    """
    if not items:
        return []

    todo_by_slug = {t.slug: t for t in items}
    visible_slugs = set(todo_by_slug.keys())
    after_map = {t.slug: t.after for t in items}

    # --- Phase 1: Hierarchy from group only ---
    parent_map: dict[str, str | None] = {}
    children_map: dict[str, list[str]] = {}

    for item in items:
        parent_slug = None
        if item.group and item.group in visible_slugs and item.group != item.slug:
            parent_slug = item.group

        parent_map[item.slug] = parent_slug
        if parent_slug is not None:
            children_map.setdefault(parent_slug, []).append(item.slug)

    roots = [item.slug for item in items if parent_map[item.slug] is None]

    # --- Phase 2: Topological sort for ordering ---

    # Helper: find which root group a slug belongs to
    def _root_of(slug: str) -> str:
        current = slug
        parent = parent_map.get(current)
        while parent is not None:
            current = parent
            parent = parent_map.get(current)
        return current

    # Sort children within each parent
    for parent_slug, children in children_map.items():
        children_map[parent_slug] = _topo_sort_siblings(children, after_map)

    # Sort roots: cross-group after-deps promote root ordering.
    # If slug A has after=[B] and B is in a different root group, A's root comes after B's root.
    root_after: dict[str, list[str]] = {r: [] for r in roots}
    for item in items:
        item_root = _root_of(item.slug)
        for dep in item.after:
            if dep in visible_slugs:
                dep_root = _root_of(dep)
                if dep_root != item_root and dep_root in root_after:
                    if dep_root not in root_after.get(item_root, []):
                        root_after.setdefault(item_root, []).append(dep_root)

    roots = _topo_sort_siblings(roots, root_after)

    # --- Phase 3: DFS walk ---
    visited: set[str] = set()
    result: list[TreeRenderNode] = []

    def _walk(slug: str, depth: int, ancestors: list[str]) -> None:
        if slug in visited:
            return
        visited.add(slug)

        parent_slug = parent_map[slug]
        if parent_slug is None:
            is_last = slug == roots[-1]
        else:
            siblings = children_map.get(parent_slug, [])
            is_last = slug == siblings[-1]

        tree_lines: list[bool] = []
        for ancestor_slug in ancestors:
            ancestor_parent = parent_map[ancestor_slug]
            if ancestor_parent is None:
                tree_lines.append(True)
            else:
                ancestor_siblings = children_map.get(ancestor_parent, [])
                ancestor_is_last = ancestor_slug == ancestor_siblings[-1]
                tree_lines.append(not ancestor_is_last)

        result.append(
            TreeRenderNode(
                slug=slug,
                depth=depth,
                is_last=is_last,
                tree_lines=tree_lines,
                todo=todo_by_slug[slug],
            )
        )

        children = children_map.get(slug, [])
        for child_slug in children:
            _walk(child_slug, depth + 1, [*ancestors, slug])

    for root_slug in roots:
        _walk(root_slug, 0, [])

    return result
