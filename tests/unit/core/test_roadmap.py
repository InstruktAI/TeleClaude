"""Tests for roadmap projection of draft todos."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from teleclaude.core.roadmap import (
    RECENTLY_DELIVERED_HOURS,
    assemble_roadmap_from_db,
    parse_since_to_cutoff,
)
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
                "lifecycle_phase": "handed_off",
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
    children. All children delivered ⇒ the holder projects 'delivered' even
    when its own roadmap/lifecycle row is stale ('active'/'prepared').
    """
    project = tmp_path / "project"
    project.mkdir()
    db_dir = project / ".teleclaude"
    db_dir.mkdir()

    database = TodosDb(str(db_dir / "todos.db"))
    await database.initialize()
    try:
        await database.add_to_roadmap("holder", description="Container")
        await database.write_state(
            "holder", {"schema_version": 2, "phase": "in_progress", "lifecycle_phase": "prepared"}
        )
        for child in ("child-a", "child-b"):
            await database.add_to_roadmap(child, description=child, group_slug="holder")
            await database.write_state(
                child,
                {"schema_version": 2, "phase": "delivered", "lifecycle_phase": "handed_off"},
            )
            await database.deliver(child, commit=f"{child}-sha")
    finally:
        await database.close()

    todos = assemble_roadmap_from_db(str(project), include_delivered=True)
    holder = next(t for t in todos if t.slug == "holder")
    assert holder.status == "delivered"
