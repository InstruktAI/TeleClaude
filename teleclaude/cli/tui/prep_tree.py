"""Pure tree-building logic for preparation view dependency graph."""

from __future__ import annotations

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


def build_dep_tree(items: list[TodoItem]) -> list[TreeRenderNode]:
    """Build a dependency tree from TodoItems using their `after` field.

    Args:
        items: Flat list of TodoItems with `after` dependencies

    Returns:
        List of TreeRenderNode in DFS order (parent before children)

    The tree structure is derived entirely from `after` dependencies:
    - Items with no resolvable `after` are roots
    - Items with `after=[X]` nest under X (first resolvable entry is visual parent)
    - Roadmap ordering is irrelevant to tree structure
    - Siblings preserve their relative order from the input list
    """
    if not items:
        return []

    # Build lookup structures
    todo_by_slug = {t.slug: t for t in items}
    visible_slugs = set(todo_by_slug.keys())

    # Build parent-child relationships from `after` dependencies
    parent_map: dict[str, str | None] = {}
    children_map: dict[str, list[str]] = {}

    # Helper to detect cycles when finding parent
    def _has_cycle_to(slug: str, target: str) -> bool:
        """Check if following parents from slug leads to target (cycle)."""
        visited_chain: set[str] = set()
        current = slug
        while current is not None:
            if current == target:
                return True
            if current in visited_chain:
                # Hit a cycle in the chain but not involving target
                break
            visited_chain.add(current)
            current = parent_map.get(current)
        return False

    for item in items:
        # Find first resolvable parent from `after` list that doesn't create a cycle
        parent_slug = None
        if item.after:
            for candidate in item.after:
                if candidate in visible_slugs and not _has_cycle_to(candidate, item.slug):
                    parent_slug = candidate
                    break

        parent_map[item.slug] = parent_slug
        if parent_slug is not None:
            if parent_slug not in children_map:
                children_map[parent_slug] = []
            children_map[parent_slug].append(item.slug)

    # Identify roots (items with no parent)
    roots = [item.slug for item in items if parent_map[item.slug] is None]

    # Track visited to break cycles
    visited: set[str] = set()

    # DFS traversal to build render order
    result: list[TreeRenderNode] = []

    def _walk(slug: str, depth: int, ancestors: list[str]) -> None:
        """Walk tree in DFS order, computing visual properties."""
        # Check for cycles (slug already in ancestors chain)
        if slug in ancestors or slug in visited:
            # Cycle detected or already visited - skip this branch
            return
        visited.add(slug)

        # Get children and determine if this is the last sibling
        parent_slug = parent_map[slug]
        if parent_slug is None:
            # Root item - check if last among roots
            is_last = slug == roots[-1]
        else:
            # Child item - check if last among siblings
            siblings = children_map.get(parent_slug, [])
            is_last = slug == siblings[-1]

        # Build tree_lines: for each ancestor level, check if continuation is needed
        tree_lines: list[bool] = []
        for ancestor_slug in ancestors:
            # Check if ancestor has a next sibling
            ancestor_parent = parent_map[ancestor_slug]
            if ancestor_parent is None:
                # Ancestor is a root - always continue (GroupSeparator closes)
                tree_lines.append(True)
            else:
                # Ancestor is a child - check if it has a next sibling
                ancestor_siblings = children_map.get(ancestor_parent, [])
                ancestor_is_last = ancestor_slug == ancestor_siblings[-1]
                tree_lines.append(not ancestor_is_last)

        # Add node to result
        result.append(
            TreeRenderNode(
                slug=slug,
                depth=depth,
                is_last=is_last,
                tree_lines=tree_lines,
                todo=todo_by_slug[slug],
            )
        )

        # Recurse into children
        children = children_map.get(slug, [])
        for child_slug in children:
            _walk(child_slug, depth + 1, ancestors + [slug])

    # Walk all roots in their original order
    for root_slug in roots:
        _walk(root_slug, 0, [])

    return result
