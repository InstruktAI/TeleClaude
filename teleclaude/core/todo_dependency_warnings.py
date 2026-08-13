"""Compose fail-open dependency warnings from todo status facts."""

from __future__ import annotations

from teleclaude.constants import TodoStatus
from teleclaude.types.todos import DependencyEntry

_FROZEN_DEPENDENCY_WARNING = "{slug} will not dispatch until iceboxed dependency '{dependency}' thaws"
_FROZEN_DEPENDENT_WARNING = "Open dependent '{dependent}' will not dispatch while '{slug}' is frozen"


def frozen_dep_warnings(slug: str, deps_with_status: list[DependencyEntry]) -> list[str]:
    """Warn when an open todo receives an iceboxed dependency."""
    return [
        _FROZEN_DEPENDENCY_WARNING.format(slug=slug, dependency=dependency.dep_slug)
        for dependency in deps_with_status
        if dependency.todo_status == TodoStatus.ICEBOX.value
    ]


def freeze_dependent_warnings(slug: str, open_dependents: list[str]) -> list[str]:
    """Warn when freezing strands active dependents."""
    return [_FROZEN_DEPENDENT_WARNING.format(slug=slug, dependent=dependent) for dependent in open_dependents]


def unfreeze_frozen_dep_warnings(slug: str, deps_with_status: list[DependencyEntry]) -> list[str]:
    """Warn when thawing leaves an active todo blocked by iceboxed dependencies."""
    return frozen_dep_warnings(slug, deps_with_status)
