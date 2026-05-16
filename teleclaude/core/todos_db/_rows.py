"""Typed row definitions for todos_db query results."""

from __future__ import annotations

from typing import TypedDict


class RoadmapRow(TypedDict):
    """A single roadmap entry as returned by list_roadmap."""

    id: str
    slug: str
    position: int
    group_slug: str | None
    description: str | None
    status: str
    delivered_at: str | None
    delivered_commit: str | None
    children: list[str] | None


class ArtifactVersionRow(TypedDict):
    """A single artifact version history entry."""

    content: str
    digest: str
    updated_by: str
    created_at: str


class ArtifactRemovalResult(TypedDict):
    """Result from deleting one named todo artifact."""

    removed: bool
    versions_deleted: int
