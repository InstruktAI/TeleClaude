"""Dependency graph utilities — cycle detection and validation.

Pure logic, no filesystem or database access.
"""

from __future__ import annotations

from collections.abc import Mapping


def holder_ancestors(group_slugs: Mapping[str, str | None], slug: str) -> set[str]:
    """Return the holder chain for slug, starting with its direct holder."""
    ancestors: set[str] = set()
    seen = {slug}
    current = group_slugs.get(slug)

    while current is not None and current not in seen:
        ancestors.add(current)
        seen.add(current)
        current = group_slugs.get(current)

    return ancestors


def detect_circular_dependency(deps: dict[str, list[str]], slug: str, new_deps: list[str]) -> list[str] | None:
    """Detect if adding new_deps to slug would create a cycle.

    Args:
        deps: Current dependency graph
        slug: Item we're updating
        new_deps: New dependencies for slug

    Returns:
        List representing the cycle path if cycle detected, None otherwise
    """
    graph: dict[str, set[str]] = {k: set(v) for k, v in deps.items()}
    graph[slug] = set(new_deps)

    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        if node in path:
            cycle_start = path.index(node)
            return path[cycle_start:] + [node]

        if node in visited:
            return None

        visited.add(node)
        path.append(node)

        for dep in graph.get(node, set()):
            result = dfs(dep)
            if result:
                return result

        path.pop()
        return None

    for dep in new_deps:
        path = [slug]
        visited = {slug}
        result = dfs(dep)
        if result:
            return [slug] + result

    return None
