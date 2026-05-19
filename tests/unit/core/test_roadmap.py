"""Tests for roadmap projection of draft todos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teleclaude.core.roadmap import assemble_roadmap_from_db
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.todos import TodoState

_ACTIVE_COLLISION_STATUS = "ready"
_DELIVERED_COLLISION_STATUS = "delivered"
_FIRST_ARTIFACT = "requirements"
_SECOND_ARTIFACT = "notes"
_TEST_SLUG = "artifact-count-item"
_VERSION_COUNT = 55


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


@pytest.mark.asyncio
async def test_roadmap_projection_exposes_uncapped_artifact_version_total(tmp_path: Path) -> None:
    """Roadmap assembly must expose artifact names and an uncapped row-id-scoped version total."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap(_TEST_SLUG, description="Count artifacts")
        await database.write_state(
            _TEST_SLUG,
            {
                "schema_version": 2,
                "kind": "todo",
                "phase": "in_progress",
                "lifecycle_phase": "prepared",
            },
        )
        for index in range(_VERSION_COUNT):
            await database.write_artifact(_TEST_SLUG, _FIRST_ARTIFACT, f"revision {index}")
        await database.write_artifact(_TEST_SLUG, _SECOND_ARTIFACT, "second artifact")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].files == [_SECOND_ARTIFACT, _FIRST_ARTIFACT]
    assert todos[0].version_total == _VERSION_COUNT + 1


@pytest.mark.asyncio
async def test_roadmap_projection_counts_follow_selected_row_id_when_slug_is_reused(tmp_path: Path) -> None:
    """A reused slug must not make active-row counts read from the delivered row."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap(_TEST_SLUG, description="Delivered copy")
        await database.write_state(
            _TEST_SLUG,
            {
                "schema_version": 2,
                "kind": "todo",
                "phase": "in_progress",
                "lifecycle_phase": "handed_off",
            },
        )
        await database.write_artifact(_TEST_SLUG, _FIRST_ARTIFACT, "delivered artifact")
        await database.deliver(_TEST_SLUG, commit="abc123")

        await database.add_to_roadmap(_TEST_SLUG, description="Active copy")
        await database.write_state(
            _TEST_SLUG,
            {
                "schema_version": 2,
                "kind": "todo",
                "phase": "in_progress",
                "lifecycle_phase": "prepared",
            },
        )
        await database.write_artifact(_TEST_SLUG, _FIRST_ARTIFACT, "active first revision")
        await database.write_artifact(_TEST_SLUG, _FIRST_ARTIFACT, "active second revision")
        await database.write_artifact(_TEST_SLUG, _SECOND_ARTIFACT, "active second artifact")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_delivered=True)

    active = next(todo for todo in todos if todo.status == _ACTIVE_COLLISION_STATUS)
    delivered = next(todo for todo in todos if todo.status == _DELIVERED_COLLISION_STATUS)
    assert active.files == [_SECOND_ARTIFACT, _FIRST_ARTIFACT]
    assert active.version_total == 3
    assert delivered.files == [_FIRST_ARTIFACT]
    assert delivered.version_total == 1
