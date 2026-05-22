"""Tests for derived sibling ordering in roadmap trees."""

from __future__ import annotations

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.constants import RoadmapStatus
from teleclaude.core.roadmap import IN_PREP_BAND, READY_BAND
from teleclaude.core.roadmap_tree import build_roadmap_sections

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
_PREP_OLDER_UPDATED = "2026-05-18T00:00:00+00:00"
_PREP_NEWER_UPDATED = "2026-05-22T00:00:00+00:00"
_DELIVERED_OLDER_AT = "2026-05-19T00:00:00+00:00"
_DELIVERED_NEWER_AT = "2026-05-21T00:00:00+00:00"
_ICEBOX_OLDER_UPDATED = "2026-05-17T00:00:00+00:00"
_ICEBOX_NEWER_UPDATED = "2026-05-22T00:00:00+00:00"


def _todo(
    slug: str,
    status: RoadmapStatus,
    *,
    group: str | None = None,
    ready_since: str | None = None,
    updated_at: str | None = None,
    delivered_at: str | None = None,
    band: str | None = None,
) -> TodoDTO:
    return TodoDTO(
        slug=slug,
        status=status,
        has_requirements=False,
        has_impl_plan=False,
        group=group,
        ready_since=ready_since,
        updated_at=updated_at,
        delivered_at=delivered_at,
        band=band,
    )


def test_active_holder_children_use_band_ordering() -> None:
    """Grouped active children use ready/in-prep section ordering."""
    sections = build_roadmap_sections(
        [
            _todo(_HOLDER, RoadmapStatus.IN_PROGRESS),
            _todo(
                _PREP_NEWER, RoadmapStatus.IN_PROGRESS, group=_HOLDER, updated_at=_PREP_NEWER_UPDATED, band=IN_PREP_BAND
            ),
            _todo(_READY_NEWER, RoadmapStatus.READY, group=_HOLDER, ready_since=_READY_NEWER_SINCE, band=READY_BAND),
            _todo(
                _PREP_OLDER, RoadmapStatus.IN_PROGRESS, group=_HOLDER, updated_at=_PREP_OLDER_UPDATED, band=IN_PREP_BAND
            ),
            _todo(_READY_OLDER, RoadmapStatus.READY, group=_HOLDER, ready_since=_READY_OLDER_SINCE, band=READY_BAND),
        ]
    )

    assert [child.todo.slug for child in sections.active[0].children] == [
        _READY_OLDER,
        _READY_NEWER,
        _PREP_OLDER,
        _PREP_NEWER,
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
