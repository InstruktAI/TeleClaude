"""Tests for derived roadmap section ordering."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import select

from teleclaude.constants import RoadmapStatus
from teleclaude.core.roadmap import (
    IN_PREP_BAND,
    READY_BAND,
    assemble_roadmap_from_db,
)
from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._models import TodoRoadmap

_PROJECT_DIR = "project"
_DATABASE_DIR = ".teleclaude"
_DATABASE_FILE = "todos.db"

_READY_OLDER = "ready-older"
_READY_NEWER = "ready-newer"
_READY_HOLDER = "ready-holder"
_READY_HOLDER_CHILD = "ready-holder-child"
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


def _project_path(tmp_path: Path) -> Path:
    project = tmp_path / _PROJECT_DIR
    project.mkdir()
    (project / _DATABASE_DIR).mkdir()
    return project


def _database(project: Path) -> TodosDb:
    return TodosDb(str(project / _DATABASE_DIR / _DATABASE_FILE))


def _set_roadmap_fields(
    database: TodosDb,
    slug: str,
    *,
    ready_since: str | None = None,
    updated_at: str | None = None,
) -> None:
    with database._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == slug).limit(1)).one()
        entry.ready_since = ready_since
        if updated_at is not None:
            entry.updated_at = updated_at
        session.add(entry)
        session.commit()


async def _add_state(database: TodosDb, slug: str, *, lifecycle_phase: str) -> None:
    await database.add_to_roadmap(slug, description=slug)
    await database.write_state(
        slug,
        {
            "schema_version": 2,
            "kind": "todo",
            "phase": "in_progress",
            "lifecycle_phase": lifecycle_phase,
        },
    )


@pytest.mark.asyncio
async def test_active_roadmap_ordering_keeps_ready_before_in_prep(tmp_path: Path) -> None:
    """Active rows sort ready by slot time, then in-prep by stale update time."""
    project = _project_path(tmp_path)
    database = _database(project)
    await database.initialize()
    try:
        await _add_state(database, _PREP_NEWER, lifecycle_phase="prd_drafting")
        await _add_state(database, _READY_NEWER, lifecycle_phase="prepared")
        await _add_state(database, _PREP_OLDER, lifecycle_phase="prd_drafting")
        await _add_state(database, _READY_OLDER, lifecycle_phase="prepared")
        _set_roadmap_fields(database, _READY_NEWER, ready_since=_READY_NEWER_SINCE, updated_at=_PREP_OLDER_UPDATED)
        _set_roadmap_fields(database, _READY_OLDER, ready_since=_READY_OLDER_SINCE, updated_at=_PREP_NEWER_UPDATED)
        _set_roadmap_fields(database, _PREP_NEWER, updated_at=_PREP_NEWER_UPDATED)
        _set_roadmap_fields(database, _PREP_OLDER, updated_at=_PREP_OLDER_UPDATED)
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert [todo.slug for todo in todos] == [_READY_OLDER, _READY_NEWER, _PREP_OLDER, _PREP_NEWER]
    assert [todo.band for todo in todos] == [READY_BAND, READY_BAND, IN_PREP_BAND, IN_PREP_BAND]


@pytest.mark.asyncio
async def test_active_roadmap_ordering_marks_derived_ready_holder_ready(tmp_path: Path) -> None:
    project = _project_path(tmp_path)
    database = _database(project)
    await database.initialize()
    try:
        await database.add_to_roadmap(_READY_HOLDER)
        await database.add_to_roadmap(_READY_HOLDER_CHILD, group_slug=_READY_HOLDER)
        await database.write_state(
            _READY_HOLDER_CHILD,
            {
                "schema_version": 2,
                "kind": "todo",
                "phase": "in_progress",
                "lifecycle_phase": "prepared",
            },
        )
        _set_roadmap_fields(
            database,
            _READY_HOLDER_CHILD,
            ready_since=_READY_OLDER_SINCE,
            updated_at=_PREP_OLDER_UPDATED,
        )
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))
    holder = next(todo for todo in todos if todo.slug == _READY_HOLDER)

    assert holder.status == RoadmapStatus.READY
    assert holder.band == READY_BAND
    assert holder.ready_since == _READY_OLDER_SINCE


@pytest.mark.asyncio
async def test_delivered_roadmap_ordering_uses_newest_delivery_first(tmp_path: Path) -> None:
    """Delivered rows sort by delivered_at descending."""
    project = _project_path(tmp_path)
    database = _database(project)
    await database.initialize()
    try:
        for slug, delivered_at in (
            (_DELIVERED_OLDER, _DELIVERED_OLDER_AT),
            (_DELIVERED_NEWER, _DELIVERED_NEWER_AT),
        ):
            await _add_state(database, slug, lifecycle_phase="finalize_ready")
            await database.deliver(slug, commit=slug, delivered_at=delivered_at)
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), delivered_only=True)

    assert [todo.slug for todo in todos] == [_DELIVERED_NEWER, _DELIVERED_OLDER]


@pytest.mark.asyncio
async def test_icebox_roadmap_ordering_uses_newest_update_first(tmp_path: Path) -> None:
    """Icebox rows sort by updated_at descending."""
    project = _project_path(tmp_path)
    database = _database(project)
    await database.initialize()
    try:
        for slug, updated_at in (
            (_ICEBOX_OLDER, _ICEBOX_OLDER_UPDATED),
            (_ICEBOX_NEWER, _ICEBOX_NEWER_UPDATED),
        ):
            await _add_state(database, slug, lifecycle_phase="prd_drafting")
            assert await database.freeze(slug) is True
            _set_roadmap_fields(database, slug, updated_at=updated_at)
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), icebox_only=True)

    assert [todo.status for todo in todos] == [RoadmapStatus.ICEBOX, RoadmapStatus.ICEBOX]
    assert [todo.slug for todo in todos] == [_ICEBOX_NEWER, _ICEBOX_OLDER]
