"""Typed row definitions for todos_db query results."""

from __future__ import annotations

from typing import TypedDict


class TodoRow(TypedDict):
    """A single todo entry as returned by list_todo."""

    id: str
    slug: str
    ready_since: str | None
    schedule: str | None
    group_slug: str | None
    description: str | None
    status: str
    delivered_at: str | None
    delivered_commit: str | None
    removed_at: str | None
    children: list[str] | None
    created_by_principal: str | None
    created_by_agent: str | None


class ArtifactVersionRow(TypedDict):
    """A single artifact version history entry."""

    content: str
    digest: str
    updated_by: str
    created_at: str


class ArtifactMetadataRow(TypedDict):
    """Current metadata for one stored artifact body."""

    name: str
    digest: str
    updated_by: str
    updated_at: str


class ArtifactRemovalResult(TypedDict):
    """Result from deleting one named todo artifact."""

    removed: bool
    versions_deleted: int
