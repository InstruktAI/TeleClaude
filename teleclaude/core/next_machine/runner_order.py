"""Ordering helpers for lifecycle runner dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol


class DependencyOrderedTodo(Protocol):
    @property
    def after(self) -> Sequence[str]: ...


def dependency_first_order[T: DependencyOrderedTodo](todos: Mapping[str, T]) -> list[str]:
    """Return slugs ordered so dependencies are considered before dependents."""
    ordered: list[str] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(slug: str) -> None:
        if slug in seen or slug in visiting:
            return
        visiting.add(slug)
        todo = todos.get(slug)
        if todo is not None:
            for dep in todo.after:
                if dep in todos:
                    visit(dep)
        visiting.remove(slug)
        seen.add(slug)
        ordered.append(slug)

    for slug in todos:
        visit(slug)
    return ordered
