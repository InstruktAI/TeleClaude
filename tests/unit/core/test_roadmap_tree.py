"""Tests for the sectioned dependency-tree roadmap projection."""

from __future__ import annotations

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.constants import RoadmapStatus
from teleclaude.core.roadmap import IN_PREP_BAND, READY_BAND
from teleclaude.core.roadmap_tree import build_roadmap_sections, flatten

pytestmark = pytest.mark.unit

_HOLDER = "holder"
_READY_OLDER = "ready-older"
_READY_NEWER = "ready-newer"
_PREP_OLDER = "prep-older"
_PREP_NEWER = "prep-newer"
_DELIVERED_OLDER = "delivered-older"
_DELIVERED_NEWER = "delivered-newer"
_ICEBOX_OLDER = "icebox-older"
_ICEBOX_NEWER = "icebox-newer"

_READY_OLDER_SINCE = "2026-05-20T00:00:00+00:00"
_READY_NEWER_SINCE = "2026-05-21T00:00:00+00:00"
_PREP_OLDER_CREATED = "2026-05-18T00:00:00+00:00"
_PREP_NEWER_CREATED = "2026-05-22T00:00:00+00:00"
_DELIVERED_OLDER_AT = "2026-05-19T00:00:00+00:00"
_DELIVERED_NEWER_AT = "2026-05-21T00:00:00+00:00"
_ICEBOX_OLDER_UPDATED = "2026-05-17T00:00:00+00:00"
_ICEBOX_NEWER_UPDATED = "2026-05-22T00:00:00+00:00"


def _todo(
    slug: str,
    status: RoadmapStatus,
    *,
    group: str | None = None,
    after: list[str] | None = None,
    ready_since: str | None = None,
    updated_at: str | None = None,
    delivered_at: str | None = None,
    created_at: str | None = None,
    band: str | None = None,
) -> TodoDTO:
    return TodoDTO(
        slug=slug,
        status=status,
        has_requirements=False,
        has_impl_plan=False,
        group=group,
        after=after or [],
        ready_since=ready_since,
        updated_at=updated_at,
        delivered_at=delivered_at,
        created_at=created_at,
        band=band,
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

    assert len(sections.active) == 1
    assert sections.active[0].todo == todos[0]
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


def test_active_holder_children_group_ready_then_newest_first() -> None:
    """Grouped active children put the Ready band above In-prep, newest-first within each."""
    sections = build_roadmap_sections(
        [
            _todo(_HOLDER, RoadmapStatus.IN_PROGRESS),
            _todo(
                _PREP_NEWER,
                RoadmapStatus.IN_PROGRESS,
                group=_HOLDER,
                created_at=_PREP_NEWER_CREATED,
                band=IN_PREP_BAND,
            ),
            _todo(_READY_NEWER, RoadmapStatus.READY, group=_HOLDER, ready_since=_READY_NEWER_SINCE, band=READY_BAND),
            _todo(
                _PREP_OLDER,
                RoadmapStatus.IN_PROGRESS,
                group=_HOLDER,
                created_at=_PREP_OLDER_CREATED,
                band=IN_PREP_BAND,
            ),
            _todo(_READY_OLDER, RoadmapStatus.READY, group=_HOLDER, ready_since=_READY_OLDER_SINCE, band=READY_BAND),
        ]
    )

    # Ready band first (newest ready_since), then In-prep band (newest created_at).
    assert [child.todo.slug for child in sections.active[0].children] == [
        _READY_NEWER,
        _READY_OLDER,
        _PREP_NEWER,
        _PREP_OLDER,
    ]


def test_delivered_roots_use_newest_delivery_first() -> None:
    """Delivered root siblings use delivered_at descending."""
    sections = build_roadmap_sections(
        [
            _todo(_DELIVERED_OLDER, RoadmapStatus.DELIVERED, delivered_at=_DELIVERED_OLDER_AT),
            _todo(_DELIVERED_NEWER, RoadmapStatus.DELIVERED, delivered_at=_DELIVERED_NEWER_AT),
        ]
    )

    assert [node.todo.slug for node in sections.delivered] == [_DELIVERED_NEWER, _DELIVERED_OLDER]


def test_delivered_holder_children_use_newest_delivery_first() -> None:
    sections = build_roadmap_sections(
        [
            _todo(_HOLDER, RoadmapStatus.DELIVERED),
            _todo(_DELIVERED_OLDER, RoadmapStatus.DELIVERED, group=_HOLDER, delivered_at=_DELIVERED_OLDER_AT),
            _todo(_DELIVERED_NEWER, RoadmapStatus.DELIVERED, group=_HOLDER, delivered_at=_DELIVERED_NEWER_AT),
        ]
    )

    assert [child.todo.slug for child in sections.delivered[0].children] == [_DELIVERED_NEWER, _DELIVERED_OLDER]


def test_icebox_roots_use_newest_update_first() -> None:
    """Icebox root siblings use updated_at descending."""
    sections = build_roadmap_sections(
        [
            _todo(_ICEBOX_OLDER, RoadmapStatus.ICEBOX, updated_at=_ICEBOX_OLDER_UPDATED),
            _todo(_ICEBOX_NEWER, RoadmapStatus.ICEBOX, updated_at=_ICEBOX_NEWER_UPDATED),
        ]
    )

    assert [node.todo.slug for node in sections.icebox] == [_ICEBOX_NEWER, _ICEBOX_OLDER]


def test_icebox_holder_children_use_newest_update_first() -> None:
    sections = build_roadmap_sections(
        [
            _todo(_HOLDER, RoadmapStatus.ICEBOX),
            _todo(_ICEBOX_OLDER, RoadmapStatus.ICEBOX, group=_HOLDER, updated_at=_ICEBOX_OLDER_UPDATED),
            _todo(_ICEBOX_NEWER, RoadmapStatus.ICEBOX, group=_HOLDER, updated_at=_ICEBOX_NEWER_UPDATED),
        ]
    )

    assert [child.todo.slug for child in sections.icebox[0].children] == [_ICEBOX_NEWER, _ICEBOX_OLDER]
