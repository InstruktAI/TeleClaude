"""Tests for roadmap projection of draft todos."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from teleclaude.core.roadmap import RECENTLY_DELIVERED_HOURS, assemble_roadmap_from_db
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import TodoState


@pytest.mark.asyncio
async def test_roadmap_projection_returns_pending_status_for_draft_todos(tmp_path: Path) -> None:
    """Draft todos must appear as status='pending' in the roadmap projection, not 'in_progress'."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("draft-item", description="A draft idea")
        await database.write_state(
            "draft-item",
            {"kind": "draft", "schema_version": 1, "phase": "pending"},
        )
        await database.write_artifact("draft-item", "input", "some content")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "draft-item"
    assert todos[0].status == "pending"
    assert todos[0].lifecycle_phase == "draft"


@pytest.mark.asyncio
async def test_roadmap_projection_returns_pending_status_for_feature_drafts(tmp_path: Path) -> None:
    """Feature draft todos created without input artifacts must not appear in progress."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()
    state = TodoState.defaults()
    state.kind = "feature"

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("feature-draft", description="A feature skeleton")
        await database.write_state("feature-draft", state.model_dump(exclude_none=True))
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "feature-draft"
    assert todos[0].status == state.phase
    assert todos[0].lifecycle_phase == state.lifecycle_phase


@pytest.mark.asyncio
async def test_roadmap_projection_uses_canonical_lifecycle_phase_for_prepare_display(tmp_path: Path) -> None:
    """Roadmap projection must expose the canonical lifecycle phase directly."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("prepared-item", description="Prepared work")
        await database.write_state(
            "prepared-item",
            {
                "schema_version": 1,
                "phase": "in_progress",
                "lifecycle_phase": "prepared",
            },
        )
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "prepared-item"
    assert todos[0].lifecycle_phase == "prepared"
    assert todos[0].status == "ready"


@pytest.mark.asyncio
async def test_roadmap_projection_omits_legacy_dor_field(tmp_path: Path) -> None:
    """Roadmap projection must not surface the legacy DOR field."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("bug-item", description="Bug work")
        await database.write_state(
            "bug-item",
            {
                "schema_version": 2,
                "kind": "bug",
                "phase": "in_progress",
                "lifecycle_phase": "prepared",
                "dor": {"score": 8, "status": "pass"},
            },
        )
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "bug-item"
    assert "dor_score" not in todos[0].model_dump()


@pytest.mark.asyncio
async def test_roadmap_projection_lazy_upcycles_legacy_v1_without_lifecycle_phase(tmp_path: Path) -> None:
    """Roadmap assembly must decode legacy v1 rows without a stored lifecycle pointer."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("legacy-item", description="Legacy row")
        await database.write_state("legacy-item", {"lifecycle_phase": "input_assessment"})
        conn = database._sync_conn()  # pylint: disable=protected-access
        try:
            conn.execute(
                "UPDATE todo_state SET state = ? WHERE slug = ?",  # guard: raw-sql
                (
                    json.dumps(
                        {
                            "schema_version": 1,
                            "phase": "pending",
                            "kind": "todo",
                        }
                    ),
                    "legacy-item",
                ),
            )
            conn.commit()
        finally:
            conn.close()
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "legacy-item"
    assert todos[0].lifecycle_phase == "draft"


@pytest.mark.asyncio
async def test_roadmap_normalizes_legacy_active_integration_phase_to_started(tmp_path: Path) -> None:
    """Active slugs with old 12-phase mirror values must normalize to 'started'."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("active-item", description="In integration")
        await database.write_state(
            "active-item",
            {
                "schema_version": 2,
                "phase": "in_progress",
                "lifecycle_phase": "handed_off",
                "integration_phase": "delivery_bookkeeping",
            },
        )
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "active-item"
    assert todos[0].integration_phase == "started"


@pytest.mark.asyncio
async def test_roadmap_normalizes_delivered_stale_integration_phase_to_delivered(tmp_path: Path) -> None:
    """Delivered slugs with any stale integration_phase must normalize to 'delivered'."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("delivered-item", description="Done")
        await database.write_state(
            "delivered-item",
            {
                "schema_version": 2,
                "phase": "in_progress",
                "lifecycle_phase": "handed_off",
                "integration_phase": "delivery_bookkeeping",
            },
        )
        await database.deliver("delivered-item", commit="abc123")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_delivered=True)

    delivered = [t for t in todos if t.slug == "delivered-item"]
    assert len(delivered) == 1
    assert delivered[0].integration_phase == "delivered"


@pytest.mark.asyncio
async def test_include_delivered_returns_all_delivered_regardless_of_age(tmp_path: Path) -> None:
    """`--include-delivered` (no window) must return delivered entries of any age.

    Regression: a 72h `delivered_at` window meant for the default/TUI list view
    leaked into the explicit include_delivered branch and hid older deliveries.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    old_delivered_at = (datetime.now(UTC) - timedelta(hours=RECENTLY_DELIVERED_HOURS + 48)).isoformat()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("old-delivered", description="Delivered long ago")
        await database.write_state("old-delivered", {"schema_version": 2, "phase": "in_progress"})
        await database.deliver("old-delivered", commit="old123", delivered_at=old_delivered_at)
    finally:
        await database.close()

    all_delivered = assemble_roadmap_from_db(str(project), include_delivered=True)
    assert [t.slug for t in all_delivered if t.slug == "old-delivered"] == ["old-delivered"]

    windowed = assemble_roadmap_from_db(
        str(project),
        include_delivered=True,
        delivered_window_hours=RECENTLY_DELIVERED_HOURS,
    )
    assert "old-delivered" not in [t.slug for t in windowed]


@pytest.mark.asyncio
async def test_roadmap_projection_defaults_missing_state_row_to_draft(tmp_path: Path) -> None:
    """Roadmap assembly must tolerate roadmap entries that have no todo_state row yet."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("stateless-item", description="No state row")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "stateless-item"
    assert todos[0].lifecycle_phase == "draft"
