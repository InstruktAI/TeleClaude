"""Tests for the sectioned dependency-tree roadmap projection."""

from __future__ import annotations

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.constants import RoadmapStatus
from teleclaude.core.roadmap_tree import build_roadmap_sections, flatten

pytestmark = pytest.mark.unit


def _todo(slug: str, status: RoadmapStatus, *, group: str | None = None, after: list[str] | None = None) -> TodoDTO:
    return TodoDTO(
        slug=slug,
        status=status,
        has_requirements=False,
        has_impl_plan=False,
        group=group,
        after=after or [],
    )


def test_delivered_parent_detaches_and_child_reroots_in_active() -> None:
    """A delivered parent leaves the active tree; its non-delivered child becomes an active root."""
    todos = [
        _todo("parent", RoadmapStatus.DELIVERED),
        _todo("child", RoadmapStatus.IN_PROGRESS, group="parent"),
    ]

    sections = build_roadmap_sections(todos)

    active_roots = [n.todo.slug for n in sections.active]
    assert active_roots == ["child"]
    assert sections.active[0].children == []
    assert [n.todo.slug for n in sections.delivered] == ["parent"]
    assert sections.delivered[0].children == []


def test_delivered_section_preserves_hierarchy_among_delivered() -> None:
    """A delivered child nests under its delivered parent in the delivered tree."""
    todos = [
        _todo("parent", RoadmapStatus.DELIVERED),
        _todo("child", RoadmapStatus.DELIVERED, group="parent"),
    ]

    sections = build_roadmap_sections(todos)

    assert sections.active == []
    assert [n.todo.slug for n in sections.delivered] == ["parent"]
    assert [c.todo.slug for c in sections.delivered[0].children] == ["child"]


def test_icebox_is_a_tree_not_flat() -> None:
    """Icebox uses the same hierarchy logic — a grouped icebox child nests."""
    todos = [
        _todo("ice-parent", RoadmapStatus.ICEBOX),
        _todo("ice-child", RoadmapStatus.ICEBOX, group="ice-parent"),
    ]

    sections = build_roadmap_sections(todos)

    assert [n.todo.slug for n in sections.icebox] == ["ice-parent"]
    assert [c.todo.slug for c in sections.icebox[0].children] == ["ice-child"]


def test_after_dependency_renders_as_visual_cascade() -> None:
    """`after` nests the dependent under its dependency (cascade), not as a sibling."""
    todos = [
        _todo("b", RoadmapStatus.READY, after=["a"]),
        _todo("a", RoadmapStatus.READY),
    ]

    sections = build_roadmap_sections(todos)

    assert [n.todo.slug for n in sections.active] == ["a"]
    assert [c.todo.slug for c in sections.active[0].children] == ["b"]


def test_is_holder_set_only_when_other_todos_group_reference_the_node() -> None:
    """`is_holder` is data-driven (group_slug refs), NOT a side-effect of having children.

    A group-referenced parent is a holder (renderer suppresses its status).
    A node nested only via after-deps is NOT a holder — it has its own status.
    """
    todos = [
        _todo("group-parent", RoadmapStatus.IN_PROGRESS),
        _todo("group-child", RoadmapStatus.IN_PROGRESS, group="group-parent"),
        _todo("after-keystone", RoadmapStatus.READY),
        _todo("after-follower", RoadmapStatus.READY, after=["after-keystone"]),
    ]

    sections = build_roadmap_sections(todos)
    by_slug = {n.todo.slug: n for n in sections.active} | {c.todo.slug: c for n in sections.active for c in n.children}

    assert by_slug["group-parent"].is_holder is True
    assert by_slug["group-child"].is_holder is False
    assert by_slug["after-keystone"].is_holder is False
    assert by_slug["after-follower"].is_holder is False


def test_self_grouped_todo_is_not_a_holder() -> None:
    """A degenerate self-reference (group == slug) does not make the todo a holder.

    Holder semantics require another todo to point at the slug. A self-reference
    is structurally a no-op (parent-resolution already excludes self-cycles) and
    must not flip the status suppression flag on the todo itself.
    """
    todos = [_todo("self-ref", RoadmapStatus.READY, group="self-ref")]

    sections = build_roadmap_sections(todos)

    assert [n.todo.slug for n in sections.active] == ["self-ref"]
    assert sections.active[0].is_holder is False


def test_flatten_yields_depth_and_last_flags() -> None:
    """flatten emits DFS rows with depth and is_last for renderers."""
    todos = [
        _todo("root", RoadmapStatus.IN_PROGRESS),
        _todo("kid", RoadmapStatus.IN_PROGRESS, group="root"),
    ]

    rows = flatten(build_roadmap_sections(todos).active)

    assert [(r.todo.slug, r.depth, r.is_last) for r in rows] == [
        ("root", 0, True),
        ("kid", 1, True),
    ]
