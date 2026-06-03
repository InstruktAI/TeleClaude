"""Tests for roadmap projection of draft todos."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import select

from teleclaude.constants import RoadmapStatus
from teleclaude.core.roadmap import (
    RECENTLY_DELIVERED_HOURS,
    assemble_roadmap_from_db,
    parse_since_to_cutoff,
)
from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._models import TodoRoadmap
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
async def test_iceboxed_draft_todo_projects_as_icebox_not_pending(tmp_path: Path) -> None:
    """A frozen draft must keep ``status='icebox'`` — the DRAFT lifecycle pointer
    (the default for never-prepared todos) must not clobber the authoritative
    icebox bucket in projection.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("ice-draft", description="A frozen draft")
        await database.write_state("ice-draft", {"kind": "draft", "schema_version": 1, "phase": "pending"})
        assert await database.freeze("ice-draft") is True
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_icebox=True)

    assert len(todos) == 1
    assert todos[0].status == RoadmapStatus.ICEBOX


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
                "lifecycle_phase": "finalize_ready",
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
                "lifecycle_phase": "finalize_ready",
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

    cutoff = (datetime.now(UTC) - timedelta(hours=RECENTLY_DELIVERED_HOURS)).isoformat()
    windowed = assemble_roadmap_from_db(
        str(project),
        include_delivered=True,
        delivered_since=cutoff,
    )
    assert "old-delivered" not in [t.slug for t in windowed]


@pytest.mark.asyncio
async def test_delivered_since_scopes_delivered_entries(tmp_path: Path) -> None:
    """`delivered_since` keeps entries delivered at/after the cutoff, drops older ones."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    recent_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    old_at = (datetime.now(UTC) - timedelta(days=30)).isoformat()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        for slug, at in (("recent-d", recent_at), ("old-d", old_at)):
            await database.add_to_roadmap(slug, description=slug)
            await database.write_state(slug, {"schema_version": 2, "phase": "in_progress"})
            await database.deliver(slug, commit=f"{slug}-sha", delivered_at=at)
    finally:
        await database.close()

    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    scoped = assemble_roadmap_from_db(str(project), include_delivered=True, delivered_since=cutoff)
    slugs = {t.slug for t in scoped}
    assert "recent-d" in slugs
    assert "old-d" not in slugs


def test_parse_since_to_cutoff_duration_units() -> None:
    """`--since` duration units (h/d/w) resolve to the right past offset."""
    now = datetime.now(UTC)

    h72 = datetime.fromisoformat(parse_since_to_cutoff("72h"))
    assert timedelta(hours=71) < now - h72 < timedelta(hours=73)

    d7 = datetime.fromisoformat(parse_since_to_cutoff("7d"))
    assert timedelta(days=6, hours=23) < now - d7 < timedelta(days=7, hours=1)

    w2 = datetime.fromisoformat(parse_since_to_cutoff("2w"))
    assert timedelta(days=13, hours=23) < now - w2 < timedelta(days=14, hours=1)


def test_parse_since_to_cutoff_iso_date_is_utc() -> None:
    """A bare ISO date is interpreted as midnight UTC."""
    iso = datetime.fromisoformat(parse_since_to_cutoff("2026-05-01"))
    assert iso == datetime(2026, 5, 1, tzinfo=UTC)


def test_parse_since_to_cutoff_normalises_tz_aware_to_utc() -> None:
    """Regression: a non-UTC offset must be normalised to UTC.

    Stored delivered_at values are UTC ISO strings compared lexicographically
    in SQLite. A preserved +05:00 offset would make the string comparison
    disagree with chronological order and wrongly exclude rows.
    """
    cutoff = parse_since_to_cutoff("2026-05-01T00:00:00+05:00")
    # 2026-05-01T00:00:00+05:00 == 2026-04-30T19:00:00Z, normalised to UTC.
    assert datetime.fromisoformat(cutoff) == datetime(2026, 4, 30, 19, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_delivered_since_tz_offset_filters_chronologically(tmp_path: Path) -> None:
    """Regression: a tz-offset --since must filter by real chronology, not raw ISO text.

    delivered_at is stored as a UTC ISO string and compared lexicographically
    in SQLite. An entry delivered 2026-04-30T20:00:00Z is chronologically
    after the cutoff 2026-05-01T00:00:00+05:00 (== 2026-04-30T19:00:00Z), so it
    MUST be returned. Without UTC normalisation the cutoff string sorts after
    the row and the entry is wrongly excluded.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("after-cutoff", description="delivered 20:00Z")
        await database.write_state("after-cutoff", {"schema_version": 2, "phase": "in_progress"})
        await database.deliver("after-cutoff", commit="ac-sha", delivered_at="2026-04-30T20:00:00+00:00")
    finally:
        await database.close()

    cutoff = parse_since_to_cutoff("2026-05-01T00:00:00+05:00")
    scoped = assemble_roadmap_from_db(str(project), include_delivered=True, delivered_since=cutoff)
    assert "after-cutoff" in {t.slug for t in scoped}


def test_parse_since_to_cutoff_rejects_invalid_input() -> None:
    """Empty, non-numeric, unknown-unit, negative, and bad-date input all raise."""
    for bad in ("", "soon", "7y", "-3d", "2026-13-99"):
        with pytest.raises(ValueError):
            parse_since_to_cutoff(bad)


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
async def test_delivered_draft_kind_todo_projects_delivered_not_pending(tmp_path: Path) -> None:
    """Regression: a delivered todo whose kind is still 'draft' must project status
    'delivered' (filled square), not 'pending' (empty square).

    The status projection must reflect lifecycle position, not the kind triage
    attribute. Previously a `kind == "draft"` gate forced status='pending' even
    after full delivery, desyncing the square glyph from the I:delivered column.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("delivered-draft-kind", description="Done, never kind-upgraded")
        await database.write_state(
            "delivered-draft-kind",
            {
                "schema_version": 2,
                "kind": "draft",
                "phase": "delivered",
                "lifecycle_phase": "finalize_ready",
                "integration_phase": "delivered",
            },
        )
        await database.deliver("delivered-draft-kind", commit="abc123")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_delivered=True)

    match = [t for t in todos if t.slug == "delivered-draft-kind"]
    assert len(match) == 1
    assert match[0].status == "delivered"
    assert match[0].integration_phase == "delivered"


@pytest.mark.asyncio
async def test_in_prepare_draft_kind_todo_projects_in_progress_not_pending(tmp_path: Path) -> None:
    """Regression: a draft-kind todo that has started the prepare lifecycle must
    project status 'in_progress', not 'pending'.

    A brain-dump todo keeps kind='draft' until triaged; once prepare starts its
    lifecycle_phase advances past DRAFT. The status projection must follow the
    lifecycle pointer, not the stale kind.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("preparing-draft-kind", description="Brain dump, prepare started")
        await database.write_state(
            "preparing-draft-kind",
            {
                "schema_version": 2,
                "kind": "draft",
                "phase": "in_progress",
                "lifecycle_phase": "prd_drafting",
            },
        )
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    assert len(todos) == 1
    assert todos[0].slug == "preparing-draft-kind"
    assert todos[0].status == "in_progress"
    assert todos[0].lifecycle_phase == "prd_drafting"


@pytest.mark.asyncio
async def test_holder_and_children_survive_delivered_window_together(tmp_path: Path) -> None:
    """A holder's delivered children ride along regardless of cutoff age.

    The holder has no own ``delivered_at`` — its delivered status is derived
    from its children. Filtering the children out by age would orphan the
    holder row from the work that produced its derived status. The cutoff applies to standalone
    delivered leaves only; children of a still-visible holder are exempt.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    old_at = (datetime.now(UTC) - timedelta(days=30)).isoformat()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("old-holder", description="Container, children long delivered")
        for child in ("old-child-a", "old-child-b"):
            await database.add_to_roadmap(child, description=child, group_slug="old-holder")
            await database.write_state(
                child, {"schema_version": 2, "phase": "delivered", "lifecycle_phase": "finalize_ready"}
            )
            await database.deliver(child, commit=f"{child}-sha", delivered_at=old_at)
    finally:
        await database.close()

    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    todos = assemble_roadmap_from_db(str(project), include_delivered=True, delivered_since=cutoff)

    by_slug = {t.slug: t for t in todos}
    assert by_slug["old-holder"].status == "delivered"
    assert by_slug["old-child-a"].status == "delivered"
    assert by_slug["old-child-b"].status == "delivered"


@pytest.mark.asyncio
async def test_delivered_wins_over_never_advanced_draft_lifecycle(tmp_path: Path) -> None:
    """Regression: a delivered todo whose lifecycle_phase never left 'draft'
    must project status 'delivered', not 'pending'.

    A brain-dump delivered without lifecycle progression keeps
    lifecycle_phase='draft'; the draft gate must not override the delivered
    roadmap status / delivered state phase.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("delivered-draft-lifecycle", description="Shipped, never triaged")
        await database.write_state(
            "delivered-draft-lifecycle",
            {"schema_version": 2, "kind": "draft", "phase": "delivered", "lifecycle_phase": "draft"},
        )
        await database.deliver("delivered-draft-lifecycle", commit="def456")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_delivered=True)

    match = [t for t in todos if t.slug == "delivered-draft-lifecycle"]
    assert len(match) == 1
    assert match[0].status == "delivered"
    assert match[0].integration_phase == "delivered"


@pytest.mark.asyncio
async def test_holder_status_is_derived_from_leaf_children(tmp_path: Path) -> None:
    """A holder has no status of its own — it is the aggregate of its leaf
    children. All children delivered ⇒ the holder projects 'delivered' without
    any lifecycle state row on the holder.
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("holder", description="Container")
        for child in ("child-a", "child-b"):
            await database.add_to_roadmap(child, description=child, group_slug="holder")
            await database.write_state(
                child,
                {"schema_version": 2, "phase": "delivered", "lifecycle_phase": "finalize_ready"},
            )
            await database.deliver(child, commit=f"{child}-sha")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_delivered=True)
    holder = next(t for t in todos if t.slug == "holder")
    assert holder.status == "delivered"


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
                "lifecycle_phase": "finalize_ready",
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


@pytest.mark.asyncio
async def test_assemble_roadmap_excludes_removed_entries(tmp_path: Path) -> None:
    """A soft-removed todo (state retained) must not appear in the roadmap projection."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("kept", description="stays")
        await database.write_state("kept", {"kind": "todo", "lifecycle_phase": "prepared"})
        await database.add_to_roadmap("gone", description="removed")
        await database.write_state("gone", {"kind": "todo", "lifecycle_phase": "prepared"})
        with database._sync_session() as session:
            entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == "gone").limit(1)).one()
            entry.prev_status = entry.status
            entry.status = "removed"
            entry.removed_at = "2026-05-19T00:00:00+00:00"
            session.add(entry)
            session.commit()
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_icebox=True, include_delivered=True)

    assert [t.slug for t in todos] == ["kept"]


@pytest.mark.asyncio
async def test_roadmap_projection_supports_removed_visibility_opt_in(tmp_path: Path) -> None:
    """Roadmap projection must support explicit removed-row visibility opt-in."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("removed-item", description="A removed item")
        # Soft-remove it
        async with database._session() as session:
            entry = await database._active_entry(session, "removed-item")
            assert entry is not None
            entry.status = "removed"
            entry.removed_at = datetime.now(UTC).isoformat()
            session.add(entry)
            await session.commit()
    finally:
        await database.close()

    # Default: excluded
    todos = assemble_roadmap_from_db(str(project))
    assert len(todos) == 0

    # include_removed=True: interleaved
    todos = assemble_roadmap_from_db(str(project), include_removed=True)
    assert len(todos) == 1
    assert todos[0].slug == "removed-item"
    assert todos[0].status == RoadmapStatus.REMOVED

    # removed_only=True: exclusive
    todos = assemble_roadmap_from_db(str(project), removed_only=True)
    assert len(todos) == 1
    assert todos[0].slug == "removed-item"


@pytest.mark.asyncio
async def test_roadmap_projection_returns_duplicate_slug_removed_rows(tmp_path: Path) -> None:
    """Roadmap projection must return ALL removed rows for a slug, not just one."""
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        # Create and remove first copy
        await database.add_to_roadmap("reused-slug", description="First copy")
        async with database._session() as session:
            entry = await database._active_entry(session, "reused-slug")
            assert entry is not None
            id1 = entry.id
            entry.status = "removed"
            entry.removed_at = "2026-05-01T10:00:00Z"
            session.add(entry)
            await session.commit()

        # Create and remove second copy
        await database.add_to_roadmap("reused-slug", description="Second copy")
        async with database._session() as session:
            entry = await database._active_entry(session, "reused-slug")
            assert entry is not None
            id2 = entry.id
            entry.status = "removed"
            entry.removed_at = "2026-05-02T10:00:00Z"
            session.add(entry)
            await session.commit()

        assert id1 != id2
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_removed=True)

    # Both should be present with their distinct IDs and descriptions
    assert len(todos) == 2
    assert {t.roadmap_id for t in todos} == {id1, id2}
    assert {t.description for t in todos} == {"First copy", "Second copy"}


# --- Section ordering (newest-first) ---

_ORD_READY_OLDER = "ready-older"
_ORD_READY_NEWER = "ready-newer"
_ORD_READY_HOLDER = "ready-holder"
_ORD_READY_HOLDER_CHILD = "ready-holder-child"
_ORD_PREP_OLDER = "prep-older"
_ORD_PREP_NEWER = "prep-newer"
_ORD_DELIVERED_OLDER = "ord-delivered-older"
_ORD_DELIVERED_NEWER = "ord-delivered-newer"
_ORD_ICEBOX_OLDER = "ord-icebox-older"
_ORD_ICEBOX_NEWER = "ord-icebox-newer"

_ORD_READY_OLDER_SINCE = "2026-05-20T00:00:00+00:00"
_ORD_READY_NEWER_SINCE = "2026-05-21T00:00:00+00:00"
_ORD_PREP_OLDER_CREATED = "2026-05-18T00:00:00+00:00"
_ORD_PREP_NEWER_CREATED = "2026-05-22T00:00:00+00:00"
_ORD_DELIVERED_OLDER_AT = "2026-05-19T00:00:00+00:00"
_ORD_DELIVERED_NEWER_AT = "2026-05-21T00:00:00+00:00"
_ORD_ICEBOX_OLDER_UPDATED = "2026-05-17T00:00:00+00:00"
_ORD_ICEBOX_NEWER_UPDATED = "2026-05-22T00:00:00+00:00"


def _ordering_project(tmp_path: Path) -> Path:
    project = tmp_path / "ordering-project"
    project.mkdir()
    (project / ".teleclaude").mkdir()
    return project


def _ordering_db(project: Path) -> TodosDb:
    return TodosDb(str(project / ".teleclaude" / "todos.db"))


def _set_ordering_fields(
    database: TodosDb,
    slug: str,
    *,
    ready_since: str | None = None,
    updated_at: str | None = None,
    created_at: str | None = None,
) -> None:
    with database._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == slug).limit(1)).one()
        entry.ready_since = ready_since
        if updated_at is not None:
            entry.updated_at = updated_at
        if created_at is not None:
            entry.created_at = created_at
        session.add(entry)
        session.commit()


async def _add_ordering_state(database: TodosDb, slug: str, *, lifecycle_phase: str) -> None:
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
async def test_active_roadmap_ordering_groups_ready_then_newest_first(tmp_path: Path) -> None:
    """Active rows group Ready above In-prep, newest-first within each group."""
    old_created = "2026-05-10T00:00:00+00:00"
    project = _ordering_project(tmp_path)
    database = _ordering_db(project)
    await database.initialize()
    try:
        await _add_ordering_state(database, _ORD_PREP_NEWER, lifecycle_phase="prd_drafting")
        await _add_ordering_state(database, _ORD_READY_NEWER, lifecycle_phase="prepared")
        await _add_ordering_state(database, _ORD_PREP_OLDER, lifecycle_phase="prd_drafting")
        await _add_ordering_state(database, _ORD_READY_OLDER, lifecycle_phase="prepared")
        _set_ordering_fields(database, _ORD_READY_NEWER, ready_since=_ORD_READY_NEWER_SINCE, created_at=old_created)
        _set_ordering_fields(database, _ORD_READY_OLDER, ready_since=_ORD_READY_OLDER_SINCE, created_at=old_created)
        _set_ordering_fields(database, _ORD_PREP_NEWER, ready_since=None, created_at=_ORD_PREP_NEWER_CREATED)
        _set_ordering_fields(database, _ORD_PREP_OLDER, ready_since=None, created_at=_ORD_PREP_OLDER_CREATED)
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))

    # Ready band (newest ready_since first), then In-prep band (newest created_at first).
    assert [todo.slug for todo in todos] == [_ORD_READY_NEWER, _ORD_READY_OLDER, _ORD_PREP_NEWER, _ORD_PREP_OLDER]


@pytest.mark.asyncio
async def test_active_roadmap_ordering_marks_derived_ready_holder_ready(tmp_path: Path) -> None:
    project = _ordering_project(tmp_path)
    database = _ordering_db(project)
    await database.initialize()
    try:
        await database.add_to_roadmap(_ORD_READY_HOLDER)
        await database.add_to_roadmap(_ORD_READY_HOLDER_CHILD, group_slug=_ORD_READY_HOLDER)
        await database.write_state(
            _ORD_READY_HOLDER_CHILD,
            {
                "schema_version": 2,
                "kind": "todo",
                "phase": "in_progress",
                "lifecycle_phase": "prepared",
            },
        )
        _set_ordering_fields(
            database,
            _ORD_READY_HOLDER_CHILD,
            ready_since=_ORD_READY_OLDER_SINCE,
            created_at="2026-05-10T00:00:00+00:00",
        )
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project))
    holder = next(todo for todo in todos if todo.slug == _ORD_READY_HOLDER)

    assert holder.status == RoadmapStatus.READY
    assert holder.ready_since == _ORD_READY_OLDER_SINCE


@pytest.mark.asyncio
async def test_delivered_roadmap_ordering_uses_newest_delivery_first(tmp_path: Path) -> None:
    """Delivered rows sort by delivered_at descending."""
    project = _ordering_project(tmp_path)
    database = _ordering_db(project)
    await database.initialize()
    try:
        for slug, delivered_at in (
            (_ORD_DELIVERED_OLDER, _ORD_DELIVERED_OLDER_AT),
            (_ORD_DELIVERED_NEWER, _ORD_DELIVERED_NEWER_AT),
        ):
            await _add_ordering_state(database, slug, lifecycle_phase="finalize_ready")
            await database.deliver(slug, commit=slug, delivered_at=delivered_at)
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), delivered_only=True)

    assert [todo.slug for todo in todos] == [_ORD_DELIVERED_NEWER, _ORD_DELIVERED_OLDER]


@pytest.mark.asyncio
async def test_icebox_roadmap_ordering_uses_newest_update_first(tmp_path: Path) -> None:
    """Icebox rows sort by updated_at descending."""
    project = _ordering_project(tmp_path)
    database = _ordering_db(project)
    await database.initialize()
    try:
        for slug, updated_at in (
            (_ORD_ICEBOX_OLDER, _ORD_ICEBOX_OLDER_UPDATED),
            (_ORD_ICEBOX_NEWER, _ORD_ICEBOX_NEWER_UPDATED),
        ):
            await _add_ordering_state(database, slug, lifecycle_phase="prd_drafting")
            assert await database.freeze(slug) is True
            _set_ordering_fields(database, slug, updated_at=updated_at)
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), icebox_only=True)

    assert [todo.status for todo in todos] == [RoadmapStatus.ICEBOX, RoadmapStatus.ICEBOX]
    assert [todo.slug for todo in todos] == [_ORD_ICEBOX_NEWER, _ORD_ICEBOX_OLDER]
